#include "vfscatalog.h"

#include "../fluorinepaths.h"

#include <QDir>

#include <blake3.h>
#include <sqlite3.h>
#ifdef FLUORINE_HAS_BSA_FFI
#include <bsa_ffi.h>
#endif

#include <array>
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <memory>
#include <map>
#include <mutex>
#include <optional>
#include <set>
#include <stdexcept>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>

namespace
{
namespace fs = std::filesystem;

constexpr int kSchemaVersion = 3;
constexpr size_t kHashBufferSize = 1024 * 1024;

struct DbCloser
{
  void operator()(sqlite3* db) const { if (db != nullptr) sqlite3_close(db); }
};
using DbPtr = std::unique_ptr<sqlite3, DbCloser>;

struct StmtCloser
{
  void operator()(sqlite3_stmt* stmt) const { if (stmt != nullptr) sqlite3_finalize(stmt); }
};
using StmtPtr = std::unique_ptr<sqlite3_stmt, StmtCloser>;

[[noreturn]] void throwDb(sqlite3* db, const std::string& operation)
{
  throw std::runtime_error(operation + ": " +
                           (db != nullptr ? sqlite3_errmsg(db) : "SQLite error"));
}

void exec(sqlite3* db, const char* sql)
{
  char* error = nullptr;
  if (sqlite3_exec(db, sql, nullptr, nullptr, &error) != SQLITE_OK) {
    const std::string message = error != nullptr ? error : sqlite3_errmsg(db);
    sqlite3_free(error);
    throw std::runtime_error(message);
  }
}

StmtPtr prepare(sqlite3* db, const char* sql)
{
  sqlite3_stmt* raw = nullptr;
  if (sqlite3_prepare_v2(db, sql, -1, &raw, nullptr) != SQLITE_OK) {
    throwDb(db, "Preparing VFS catalog statement");
  }
  return StmtPtr(raw);
}

void bindText(sqlite3* db, sqlite3_stmt* stmt, int index, const std::string& value)
{
  if (sqlite3_bind_text(stmt, index, value.data(), static_cast<int>(value.size()),
                        SQLITE_TRANSIENT) != SQLITE_OK) {
    throwDb(db, "Binding VFS catalog text");
  }
}

void bindDigest(sqlite3* db, sqlite3_stmt* stmt, int index,
                const VfsDigest& digest)
{
  if (sqlite3_bind_blob(stmt, index, digest.data(), digest.size(),
                        SQLITE_TRANSIENT) != SQLITE_OK) {
    throwDb(db, "Binding VFS catalog digest");
  }
}

std::vector<std::string> splitPath(const std::string& path)
{
  std::vector<std::string> parts;
  size_t start = 0;
  while (start < path.size()) {
    while (start < path.size() &&
           (path[start] == '/' || static_cast<unsigned char>(path[start]) == 92)) {
      ++start;
    }
    if (start >= path.size()) break;
    const size_t end = path.find_first_of("/\\", start);
    parts.push_back(path.substr(start, end == std::string::npos
                                          ? std::string::npos : end - start));
    if (end == std::string::npos) break;
    start = end + 1;
  }
  return parts;
}

std::string fastRelative(const std::string& path, const std::string& root)
{
  if (path.size() <= root.size()) return {};
  size_t start = root.size();
  while (start < path.size() &&
         (path[start] == '/' || static_cast<unsigned char>(path[start]) == 92)) {
    ++start;
  }
  return start < path.size() ? path.substr(start) : std::string{};
}

int64_t timespecNs(const timespec& value)
{
  return static_cast<int64_t>(value.tv_sec) * 1000000000LL + value.tv_nsec;
}

std::chrono::system_clock::time_point timePoint(const timespec& value)
{
  return std::chrono::system_clock::time_point(
      std::chrono::seconds(value.tv_sec) + std::chrono::nanoseconds(value.tv_nsec));
}

bool sameContentFingerprint(const struct stat& left, const struct stat& right)
{
  return left.st_dev == right.st_dev && left.st_ino == right.st_ino &&
         left.st_size == right.st_size &&
         timespecNs(left.st_mtim) == timespecNs(right.st_mtim) &&
         timespecNs(left.st_ctim) == timespecNs(right.st_ctim);
}

std::array<unsigned char, BLAKE3_OUT_LEN> hashFile(const fs::path& path)
{
  const int fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
  if (fd < 0) {
    throw std::runtime_error("Unable to hash " + path.string() + ": " +
                             std::strerror(errno));
  }

  blake3_hasher hasher;
  blake3_hasher_init(&hasher);
  std::array<unsigned char, kHashBufferSize> buffer{};
  for (;;) {
    const ssize_t count = ::read(fd, buffer.data(), buffer.size());
    if (count == 0) break;
    if (count < 0) {
      const int saved = errno;
      ::close(fd);
      throw std::runtime_error("Unable to hash " + path.string() + ": " +
                               std::strerror(saved));
    }
    blake3_hasher_update(&hasher, buffer.data(), static_cast<size_t>(count));
  }
  ::close(fd);

  std::array<unsigned char, BLAKE3_OUT_LEN> digest{};
  blake3_hasher_finalize(&hasher, digest.data(), digest.size());
  return digest;
}

uint64_t fnv1a(const std::string& value)
{
  uint64_t hash = 1469598103934665603ULL;
  for (const unsigned char c : value) {
    hash ^= c;
    hash *= 1099511628211ULL;
  }
  return hash;
}

bool isBethesdaArchive(const std::string& path)
{
  const std::string normalized = normalizeForLookup(path);
  return normalized.ends_with(".bsa") || normalized.ends_with(".ba2");
}

struct ArchiveCandidate
{
  std::string real_path;
  VfsDigest digest{};
};

struct Root
{
  std::string key;
  std::string path;
  std::string origin;
  bool backing = false;
};

void hashBytes(blake3_hasher& hasher, const void* data, size_t size)
{
  blake3_hasher_update(&hasher, data, size);
}

void hashString(blake3_hasher& hasher, const std::string& value)
{
  uint64_t size = static_cast<uint64_t>(value.size());
  std::array<unsigned char, sizeof(size)> encoded{};
  for (size_t i = 0; i < encoded.size(); ++i) {
    encoded[i] = static_cast<unsigned char>(size & 0xffu);
    size >>= 8;
  }
  hashBytes(hasher, encoded.data(), encoded.size());
  hashBytes(hasher, value.data(), value.size());
}

VfsDigest finishHash(blake3_hasher& hasher)
{
  VfsDigest digest{};
  static_assert(std::tuple_size_v<VfsDigest> == BLAKE3_OUT_LEN);
  blake3_hasher_finalize(&hasher, digest.data(), digest.size());
  return digest;
}

struct MerkleNode
{
  std::map<std::string, MerkleNode> directories;
  std::map<std::string, VfsDigest> files;
};

VfsDigest hashMerkleDirectory(const MerkleNode& node)
{
  blake3_hasher hasher;
  blake3_hasher_init(&hasher);
  constexpr char domain[] = "fluorine.vfs.directory.v1";
  hashBytes(hasher, domain, sizeof(domain) - 1);

  for (const auto& [name, directory] : node.directories) {
    const unsigned char type = 1;
    const VfsDigest child = hashMerkleDirectory(directory);
    hashBytes(hasher, &type, sizeof(type));
    hashString(hasher, name);
    hashBytes(hasher, child.data(), child.size());
  }
  for (const auto& [name, digest] : node.files) {
    const unsigned char type = 0;
    hashBytes(hasher, &type, sizeof(type));
    hashString(hasher, name);
    hashBytes(hasher, digest.data(), digest.size());
  }
  return finishHash(hasher);
}

VfsProviderRoot calculateProviderRoot(sqlite3* db, const Root& root)
{
  auto rows = prepare(db,
      "SELECT normalized_path,blake3 FROM catalog_files"
      " WHERE root_key=?1 ORDER BY normalized_path;");
  bindText(db, rows.get(), 1, root.key);

  MerkleNode merkle;
  uint64_t fileCount = 0;
  while (sqlite3_step(rows.get()) == SQLITE_ROW) {
    const auto* path = reinterpret_cast<const char*>(sqlite3_column_text(rows.get(), 0));
    const void* blob = sqlite3_column_blob(rows.get(), 1);
    const int bytes = sqlite3_column_bytes(rows.get(), 1);
    if (path == nullptr || blob == nullptr || bytes != BLAKE3_OUT_LEN) continue;

    const std::string normalized(path);
    const auto parts = splitPath(normalized);
    if (parts.empty()) continue;
    MerkleNode* directory = &merkle;
    for (size_t i = 0; i + 1 < parts.size(); ++i) {
      directory = &directory->directories[parts[i]];
    }

    VfsDigest content{};
    std::memcpy(content.data(), blob, content.size());
    blake3_hasher leaf;
    blake3_hasher_init(&leaf);
    constexpr char domain[] = "fluorine.vfs.file.v1";
    hashBytes(leaf, domain, sizeof(domain) - 1);
    hashString(leaf, normalized);
    hashBytes(leaf, content.data(), content.size());
    directory->files[parts.back()] = finishHash(leaf);
    ++fileCount;
  }

  return {root.key, root.origin, root.backing, fileCount,
          hashMerkleDirectory(merkle)};
}

VfsDigest calculateProfileRoot(const std::vector<VfsProviderRoot>& roots)
{
  blake3_hasher hasher;
  blake3_hasher_init(&hasher);
  constexpr char domain[] = "fluorine.vfs.profile.v1";
  hashBytes(hasher, domain, sizeof(domain) - 1);
  for (const auto& root : roots) {
    const unsigned char role = root.is_backing ? 1 : 0;
    hashBytes(hasher, &role, sizeof(role));
    hashString(hasher, root.origin);
    hashBytes(hasher, root.digest.data(), root.digest.size());
  }
  return finishHash(hasher);
}

void initializeSchema(sqlite3* db)
{
  exec(db, "PRAGMA journal_mode=WAL;");
  exec(db, "PRAGMA synchronous=NORMAL;");
  exec(db, "PRAGMA foreign_keys=ON;");
  exec(db, "PRAGMA temp_store=MEMORY;");
  exec(db,
       "CREATE TABLE IF NOT EXISTS catalog_meta("
       " key TEXT PRIMARY KEY, value INTEGER NOT NULL);"
       "CREATE TABLE IF NOT EXISTS catalog_files("
       " root_key TEXT NOT NULL, relative_path TEXT NOT NULL,"
       " normalized_path TEXT NOT NULL, origin TEXT NOT NULL,"
       " is_backing INTEGER NOT NULL, device INTEGER NOT NULL,"
       " inode INTEGER NOT NULL, size INTEGER NOT NULL, mode INTEGER NOT NULL,"
       " mtime_ns INTEGER NOT NULL, ctime_ns INTEGER NOT NULL,"
       " blake3 BLOB NOT NULL, seen_generation INTEGER NOT NULL,"
       " PRIMARY KEY(root_key, normalized_path));"
       "CREATE INDEX IF NOT EXISTS catalog_files_seen"
       " ON catalog_files(root_key, seen_generation);");
  exec(db,
       "CREATE TABLE IF NOT EXISTS catalog_roots("
       " root_key TEXT PRIMARY KEY, merkle_root BLOB NOT NULL,"
       " file_count INTEGER NOT NULL, generation INTEGER NOT NULL);");
  exec(db,
       "CREATE TABLE IF NOT EXISTS archive_catalogs("
       " digest BLOB PRIMARY KEY, member_count INTEGER NOT NULL,"
       " error TEXT NOT NULL DEFAULT '');"
       "CREATE TABLE IF NOT EXISTS archive_members("
       " digest BLOB NOT NULL, relative_path TEXT NOT NULL,"
       " normalized_path TEXT NOT NULL,"
       " PRIMARY KEY(digest,normalized_path)) WITHOUT ROWID;");
  exec(db,
       "CREATE TEMP TABLE IF NOT EXISTS catalog_seen("
       " root_key TEXT NOT NULL, normalized_path TEXT NOT NULL,"
       " PRIMARY KEY(root_key,normalized_path)) WITHOUT ROWID;");

  auto current = prepare(db,
      "SELECT value FROM catalog_meta WHERE key='schema_version';");
  if (sqlite3_step(current.get()) == SQLITE_ROW &&
      sqlite3_column_int(current.get(), 0) > kSchemaVersion) {
    throw std::runtime_error("VFS catalog was created by a newer Fluorine version");
  }

  auto stmt = prepare(db,
      "INSERT INTO catalog_meta(key,value) VALUES('schema_version',?1)"
      " ON CONFLICT(key) DO UPDATE SET value=excluded.value;");
  sqlite3_bind_int(stmt.get(), 1, kSchemaVersion);
  if (sqlite3_step(stmt.get()) != SQLITE_DONE) throwDb(db, "Writing catalog schema");
}

int64_t nextGeneration(sqlite3* db)
{
  exec(db, "INSERT OR IGNORE INTO catalog_meta(key,value) VALUES('generation',0);");
  exec(db, "UPDATE catalog_meta SET value=value+1 WHERE key='generation';");
  auto stmt = prepare(db, "SELECT value FROM catalog_meta WHERE key='generation';");
  if (sqlite3_step(stmt.get()) != SQLITE_ROW) throwDb(db, "Reading catalog generation");
  return sqlite3_column_int64(stmt.get(), 0);
}

std::shared_ptr<const VfsArchiveMemberIndex> reconcileArchiveManifests(
    sqlite3* db,
    const std::map<VfsDigest, std::string>& archive_candidates,
    const std::map<std::string, VfsDigest>& visible_archives,
    VfsCatalogProgress& state)
{
  auto findCatalog = prepare(db,
      "SELECT member_count,error FROM archive_catalogs WHERE digest=?1;");
  std::vector<ArchiveCandidate> uncached;
  uncached.reserve(archive_candidates.size());
  for (const auto& [digest, path] : archive_candidates) {
    sqlite3_reset(findCatalog.get());
    sqlite3_clear_bindings(findCatalog.get());
    bindDigest(db, findCatalog.get(), 1, digest);
    if (sqlite3_step(findCatalog.get()) == SQLITE_ROW) {
      ++state.archives_reused;
      const auto* error = reinterpret_cast<const char*>(
          sqlite3_column_text(findCatalog.get(), 1));
      if (error != nullptr && *error != '\0') ++state.archive_errors;
      continue;
    }
    uncached.push_back({path, digest});
  }

#ifdef FLUORINE_HAS_BSA_FFI
  if (!uncached.empty()) {
    std::atomic<std::size_t> next{0};
    std::atomic<uint64_t> indexed{0};
    std::atomic<uint64_t> errors{0};
    std::mutex dbMutex;
    std::mutex errorMutex;
    std::exception_ptr workerError;
    std::atomic<bool> stop{false};

    const unsigned int hardware = std::max(1u, std::thread::hardware_concurrency());
    const std::size_t workerCount =
        std::min<std::size_t>(uncached.size(), hardware);
    std::vector<std::thread> workers;
    workers.reserve(workerCount);
    for (std::size_t worker = 0; worker < workerCount; ++worker) {
      workers.emplace_back([&]() {
        while (!stop.load(std::memory_order_relaxed)) {
          const std::size_t index = next.fetch_add(1, std::memory_order_relaxed);
          if (index >= uncached.size()) return;
          const ArchiveCandidate& candidate = uncached[index];
          BsaFfiStringList list = bsa_ffi_list_files(candidate.real_path.c_str());
          const std::string parseError = list.error != nullptr ? list.error : "";

          try {
            std::scoped_lock lock(dbMutex);
            auto removeMembers = prepare(
                db, "DELETE FROM archive_members WHERE digest=?1;");
            bindDigest(db, removeMembers.get(), 1, candidate.digest);
            if (sqlite3_step(removeMembers.get()) != SQLITE_DONE) {
              throwDb(db, "Clearing archive manifest members");
            }

            uint64_t memberCount = 0;
            if (parseError.empty()) {
              auto insertMember = prepare(db,
                  "INSERT OR IGNORE INTO archive_members("
                  "digest,relative_path,normalized_path) VALUES(?1,?2,?3);");
              for (std::size_t item = 0; item < list.count; ++item) {
                if (list.items == nullptr || list.items[item] == nullptr) continue;
                std::string relative(list.items[item]);
                std::replace(relative.begin(), relative.end(), '\\', '/');
                const std::string normalized = normalizeForLookup(relative);
                if (normalized.empty()) continue;
                sqlite3_reset(insertMember.get());
                sqlite3_clear_bindings(insertMember.get());
                bindDigest(db, insertMember.get(), 1, candidate.digest);
                bindText(db, insertMember.get(), 2, relative);
                bindText(db, insertMember.get(), 3, normalized);
                if (sqlite3_step(insertMember.get()) != SQLITE_DONE) {
                  throwDb(db, "Adding archive manifest member");
                }
                if (sqlite3_changes(db) != 0) ++memberCount;
              }
            }

            auto insertCatalog = prepare(db,
                "INSERT OR REPLACE INTO archive_catalogs("
                "digest,member_count,error) VALUES(?1,?2,?3);");
            bindDigest(db, insertCatalog.get(), 1, candidate.digest);
            sqlite3_bind_int64(insertCatalog.get(), 2,
                               static_cast<sqlite3_int64>(memberCount));
            bindText(db, insertCatalog.get(), 3, parseError);
            if (sqlite3_step(insertCatalog.get()) != SQLITE_DONE) {
              throwDb(db, "Publishing archive manifest");
            }
            indexed.fetch_add(1, std::memory_order_relaxed);
            if (!parseError.empty()) errors.fetch_add(1, std::memory_order_relaxed);
          } catch (...) {
            stop.store(true, std::memory_order_relaxed);
            std::scoped_lock lock(errorMutex);
            if (workerError == nullptr) workerError = std::current_exception();
          }
          bsa_ffi_string_list_free(list);
        }
      });
    }
    for (auto& worker : workers) worker.join();
    if (workerError != nullptr) std::rethrow_exception(workerError);
    state.archives_indexed += indexed.load(std::memory_order_relaxed);
    state.archive_errors += errors.load(std::memory_order_relaxed);
  }
#else
  // Archive support is optional at build time. Keep the filesystem catalog
  // usable without pretending the archives were successfully indexed.
  state.archive_errors += uncached.size();
#endif

  std::set<VfsDigest> visibleDigests;
  for (const auto& [path, digest] : visible_archives) {
    (void)path;
    visibleDigests.insert(digest);
  }

  std::size_t memberCount = 0;
  std::size_t archiveCount = 0;
  for (const VfsDigest& digest : visibleDigests) {
    sqlite3_reset(findCatalog.get());
    sqlite3_clear_bindings(findCatalog.get());
    bindDigest(db, findCatalog.get(), 1, digest);
    if (sqlite3_step(findCatalog.get()) != SQLITE_ROW) continue;
    const auto* error = reinterpret_cast<const char*>(
        sqlite3_column_text(findCatalog.get(), 1));
    if (error != nullptr && *error != '\0') continue;
    memberCount += static_cast<std::size_t>(
        sqlite3_column_int64(findCatalog.get(), 0));
    ++archiveCount;
  }

  auto index = std::make_shared<VfsArchiveMemberIndex>(
      memberCount, archiveCount, archiveCount == visibleDigests.size());
  auto members = prepare(db,
      "SELECT normalized_path FROM archive_members WHERE digest=?1;");
  for (const VfsDigest& digest : visibleDigests) {
    sqlite3_reset(members.get());
    sqlite3_clear_bindings(members.get());
    bindDigest(db, members.get(), 1, digest);
    while (sqlite3_step(members.get()) == SQLITE_ROW) {
      const auto* path = reinterpret_cast<const char*>(
          sqlite3_column_text(members.get(), 0));
      if (path != nullptr) index->add(path);
    }
  }
  state.archive_members = memberCount;
  return index;
}

}  // namespace

VfsCatalog::VfsCatalog(fs::path database_path)
    : m_database_path(std::move(database_path))
{}

fs::path VfsCatalog::databasePath(const std::string& data_dir)
{
  char name[48];
  std::snprintf(name, sizeof(name), "%016llx.catalog.sqlite",
                static_cast<unsigned long long>(fnv1a(data_dir)));
  return fs::path(fluorineVfsCacheDir().toStdString()) / name;
}

VfsCatalogResult VfsCatalog::reconcileAndBuild(
    const std::string& data_dir,
    const std::vector<std::pair<std::string, std::string>>& mods,
    const std::string& overwrite_dir,
    bool scan_base,
    ProgressCallback progress)
{
  const auto scanStart = std::chrono::steady_clock::now();
  std::error_code ec;
  fs::create_directories(m_database_path.parent_path(), ec);
  if (ec) {
    throw std::runtime_error("Unable to create local VFS catalog directory: " +
                             ec.message());
  }

  sqlite3* raw = nullptr;
  if (sqlite3_open_v2(m_database_path.c_str(), &raw,
                      SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE |
                          SQLITE_OPEN_FULLMUTEX,
                      nullptr) != SQLITE_OK) {
    DbPtr failed(raw);
    throwDb(raw, "Opening local VFS catalog");
  }
  DbPtr db(raw);
  sqlite3_busy_timeout(db.get(), 30000);
  initializeSchema(db.get());
  exec(db.get(), "BEGIN IMMEDIATE;");

  try {
    const int64_t generation = nextGeneration(db.get());
    VfsTree tree;
    tree.root.is_directory = true;
    tree.dir_count = 1;
    std::map<VfsDigest, std::string> archiveCandidates;
    std::map<std::string, VfsDigest> visibleArchives;
    VfsCatalogProgress state;

    std::vector<Root> roots;
    if (scan_base) roots.push_back({data_dir, data_dir, "_base_game", true});
    for (const auto& [name, path] : mods) roots.push_back({path, path, name, false});
    roots.push_back({overwrite_dir, overwrite_dir, "Overwrite", false});

    if (!scan_base) {
      auto base = prepare(db.get(),
          "SELECT relative_path,size,mtime_ns,mode,blake3 FROM catalog_files"
          " WHERE root_key=?1 ORDER BY normalized_path;");
      bindText(db.get(), base.get(), 1, data_dir);
      while (sqlite3_step(base.get()) == SQLITE_ROW) {
        const auto* rel = reinterpret_cast<const char*>(sqlite3_column_text(base.get(), 0));
        if (rel == nullptr) continue;
        const std::string relative(rel);
        tree.root.insertFile(
            splitPath(relative), relative,
            static_cast<uint64_t>(sqlite3_column_int64(base.get(), 1)),
            std::chrono::system_clock::time_point(
                std::chrono::nanoseconds(sqlite3_column_int64(base.get(), 2))),
            "_base_game", true,
            static_cast<mode_t>(sqlite3_column_int64(base.get(), 3)),
            [&]() -> std::optional<VfsDigest> {
              const void* blob = sqlite3_column_blob(base.get(), 4);
              const int bytes = sqlite3_column_bytes(base.get(), 4);
              if (blob == nullptr || bytes != BLAKE3_OUT_LEN) return std::nullopt;
              VfsDigest value{};
              std::memcpy(value.data(), blob, value.size());
              return value;
            }());
        ++tree.file_count;
        if (isBethesdaArchive(relative)) {
          const void* blob = sqlite3_column_blob(base.get(), 4);
          const int bytes = sqlite3_column_bytes(base.get(), 4);
          if (blob != nullptr && bytes == BLAKE3_OUT_LEN) {
            VfsDigest digest{};
            std::memcpy(digest.data(), blob, digest.size());
            const std::string full = (fs::path(data_dir) / relative).string();
            archiveCandidates.insert_or_assign(digest, full);
            visibleArchives.insert_or_assign(normalizeForLookup(relative), digest);
            ++state.archives_discovered;
          }
        }
      }
    }

    auto find = prepare(db.get(),
        "SELECT device,inode,size,mode,mtime_ns,ctime_ns,blake3"
        " FROM catalog_files WHERE root_key=?1 AND normalized_path=?2;");
    auto upsert = prepare(db.get(),
        "INSERT INTO catalog_files(root_key,relative_path,normalized_path,origin,"
        "is_backing,device,inode,size,mode,mtime_ns,ctime_ns,blake3,seen_generation)"
        " VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)"
        " ON CONFLICT(root_key,normalized_path) DO UPDATE SET"
        " relative_path=excluded.relative_path,origin=excluded.origin,"
        " is_backing=excluded.is_backing,device=excluded.device,inode=excluded.inode,"
        " size=excluded.size,mode=excluded.mode,mtime_ns=excluded.mtime_ns,"
        " ctime_ns=excluded.ctime_ns,blake3=excluded.blake3,"
        " seen_generation=excluded.seen_generation;");
    auto markSeen = prepare(db.get(),
        "INSERT OR IGNORE INTO catalog_seen(root_key,normalized_path) VALUES(?1,?2);");
    auto refreshOrigin = prepare(db.get(),
        "UPDATE catalog_files SET origin=?3,is_backing=?4"
        " WHERE root_key=?1 AND normalized_path=?2"
        " AND (origin<>?3 OR is_backing<>?4);");
    auto prune = prepare(db.get(),
        "DELETE FROM catalog_files WHERE root_key=?1 AND normalized_path NOT IN"
        " (SELECT normalized_path FROM catalog_seen WHERE root_key=?1);");
    auto findRoot = prepare(db.get(),
        "SELECT merkle_root FROM catalog_roots WHERE root_key=?1;");
    auto upsertRoot = prepare(db.get(),
        "INSERT INTO catalog_roots(root_key,merkle_root,file_count,generation)"
        " VALUES(?1,?2,?3,?4) ON CONFLICT(root_key) DO UPDATE SET"
        " merkle_root=excluded.merkle_root,file_count=excluded.file_count,"
        " generation=excluded.generation;");

    std::vector<VfsProviderRoot> providerRoots;
    providerRoots.reserve(roots.size() + (scan_base ? 0 : 1));
    if (!scan_base) {
      providerRoots.push_back(calculateProviderRoot(
          db.get(), Root{data_dir, data_dir, "_base_game", true}));
    }
    const auto reportProgress = [&]() {
      state.elapsed_ms = static_cast<uint64_t>(
          std::chrono::duration_cast<std::chrono::milliseconds>(
              std::chrono::steady_clock::now() - scanStart).count());
      state.hash_mib_per_second = state.elapsed_ms == 0 ? 0.0 :
          (static_cast<double>(state.bytes_hashed) / (1024.0 * 1024.0)) /
          (static_cast<double>(state.elapsed_ms) / 1000.0);
      if (progress) progress(state);
    };
    for (const Root& root : roots) {
      state.current_root = root.path;
      const std::string rootPrefix = fs::path(root.path).string();

      const bool rootExists = fs::exists(root.path, ec);
      if (ec) {
        throw std::runtime_error("Unable to inspect VFS provider " + root.path +
                                 ": " + ec.message());
      }
      if (rootExists) {
        for (auto it = fs::recursive_directory_iterator(
               root.path, fs::directory_options::skip_permission_denied, ec);
           !ec && it != fs::recursive_directory_iterator(); it.increment(ec)) {
        const fs::directory_entry& entry = *it;
        const std::string full = entry.path().string();
        const std::string relative = fastRelative(full, rootPrefix);
        if (relative.empty() || relative == "meta.ini") continue;

        struct stat st {};
        if (::lstat(full.c_str(), &st) != 0) continue;
        const auto components = splitPath(relative);
        if (S_ISDIR(st.st_mode)) {
          tree.root.insertDirectory(components);
          visibleArchives.erase(normalizeForLookup(relative));
          ++tree.dir_count;
          continue;
        }
        if (!S_ISREG(st.st_mode)) continue;

        ++state.files_scanned;
        const std::string normalized = normalizeForLookup(relative);
        sqlite3_reset(markSeen.get());
        sqlite3_clear_bindings(markSeen.get());
        bindText(db.get(), markSeen.get(), 1, root.key);
        bindText(db.get(), markSeen.get(), 2, normalized);
        if (sqlite3_step(markSeen.get()) != SQLITE_DONE) throwDb(db.get(), "Marking catalog file seen");
        int64_t mtimeNs = timespecNs(st.st_mtim);
        int64_t ctimeNs = timespecNs(st.st_ctim);
        std::array<unsigned char, BLAKE3_OUT_LEN> digest{};
        bool reuseHash = false;

        sqlite3_reset(find.get());
        sqlite3_clear_bindings(find.get());
        bindText(db.get(), find.get(), 1, root.key);
        bindText(db.get(), find.get(), 2, normalized);
        if (sqlite3_step(find.get()) == SQLITE_ROW) {
          const void* blob = sqlite3_column_blob(find.get(), 6);
          const int bytes = sqlite3_column_bytes(find.get(), 6);
          reuseHash = sqlite3_column_int64(find.get(), 0) == st.st_dev &&
                      sqlite3_column_int64(find.get(), 1) == st.st_ino &&
                      sqlite3_column_int64(find.get(), 2) == st.st_size &&
                      sqlite3_column_int64(find.get(), 3) == (st.st_mode & 07777) &&
                      sqlite3_column_int64(find.get(), 4) == mtimeNs &&
                      sqlite3_column_int64(find.get(), 5) == ctimeNs &&
                      blob != nullptr && bytes == BLAKE3_OUT_LEN;
          if (reuseHash) std::memcpy(digest.data(), blob, digest.size());
        }
        if (!reuseHash) {
          state.current_file = full;
          state.current_file_size = static_cast<uint64_t>(st.st_size);
          reportProgress();  // show the file before a long hash
          bool stable = false;
          for (int attempt = 0; attempt < 3; ++attempt) {
            const struct stat before = st;
            digest = hashFile(entry.path());
            struct stat after {};
            if (::lstat(full.c_str(), &after) != 0) {
              throw std::runtime_error("File disappeared while hashing: " + full);
            }
            st = after;
            mtimeNs = timespecNs(st.st_mtim);
            ctimeNs = timespecNs(st.st_ctim);
            if (sameContentFingerprint(before, after)) {
              stable = true;
              break;
            }
          }
          if (!stable) {
            throw std::runtime_error("File kept changing while hashing: " + full);
          }
          ++state.files_hashed;
          state.bytes_hashed += static_cast<uint64_t>(st.st_size);
          reportProgress();
        }

        if (!reuseHash) {
          sqlite3_reset(upsert.get());
          sqlite3_clear_bindings(upsert.get());
          bindText(db.get(), upsert.get(), 1, root.key);
          bindText(db.get(), upsert.get(), 2, relative);
          bindText(db.get(), upsert.get(), 3, normalized);
          bindText(db.get(), upsert.get(), 4, root.origin);
          sqlite3_bind_int(upsert.get(), 5, root.backing ? 1 : 0);
          sqlite3_bind_int64(upsert.get(), 6, st.st_dev);
          sqlite3_bind_int64(upsert.get(), 7, st.st_ino);
          sqlite3_bind_int64(upsert.get(), 8, st.st_size);
          sqlite3_bind_int64(upsert.get(), 9, st.st_mode & 07777);
          sqlite3_bind_int64(upsert.get(), 10, mtimeNs);
          sqlite3_bind_int64(upsert.get(), 11, ctimeNs);
          sqlite3_bind_blob(upsert.get(), 12, digest.data(), digest.size(), SQLITE_TRANSIENT);
          sqlite3_bind_int64(upsert.get(), 13, generation);
          if (sqlite3_step(upsert.get()) != SQLITE_DONE) throwDb(db.get(), "Updating catalog file");
        } else {
          sqlite3_reset(refreshOrigin.get());
          sqlite3_clear_bindings(refreshOrigin.get());
          bindText(db.get(), refreshOrigin.get(), 1, root.key);
          bindText(db.get(), refreshOrigin.get(), 2, normalized);
          bindText(db.get(), refreshOrigin.get(), 3, root.origin);
          sqlite3_bind_int(refreshOrigin.get(), 4, root.backing ? 1 : 0);
          if (sqlite3_step(refreshOrigin.get()) != SQLITE_DONE) throwDb(db.get(), "Refreshing catalog origin");
        }

        const std::string storedPath = root.backing ? relative : full;
        tree.root.insertFile(components, storedPath,
                             static_cast<uint64_t>(st.st_size),
                             timePoint(st.st_mtim), root.origin, root.backing,
                             st.st_mode & 07777, digest);
        ++tree.file_count;
        if (isBethesdaArchive(relative)) {
          archiveCandidates.insert_or_assign(digest, full);
          visibleArchives.insert_or_assign(normalized, digest);
          ++state.archives_discovered;
        }
        state.current_file.clear();
        state.current_file_size = 0;

        if (progress && (state.files_scanned % 2048 == 0)) reportProgress();
        }
      }
      ec.clear();

      sqlite3_reset(prune.get());
      sqlite3_clear_bindings(prune.get());
      bindText(db.get(), prune.get(), 1, root.key);
      if (sqlite3_step(prune.get()) != SQLITE_DONE) throwDb(db.get(), "Pruning catalog root");

      VfsProviderRoot providerRoot = calculateProviderRoot(db.get(), root);
      sqlite3_reset(findRoot.get());
      sqlite3_clear_bindings(findRoot.get());
      bindText(db.get(), findRoot.get(), 1, root.key);
      bool rootChanged = true;
      if (sqlite3_step(findRoot.get()) == SQLITE_ROW) {
        const void* old = sqlite3_column_blob(findRoot.get(), 0);
        const int bytes = sqlite3_column_bytes(findRoot.get(), 0);
        rootChanged = old == nullptr || bytes != static_cast<int>(providerRoot.digest.size()) ||
                      std::memcmp(old, providerRoot.digest.data(), providerRoot.digest.size()) != 0;
      }
      if (rootChanged) ++state.provider_roots_changed;

      sqlite3_reset(upsertRoot.get());
      sqlite3_clear_bindings(upsertRoot.get());
      bindText(db.get(), upsertRoot.get(), 1, root.key);
      sqlite3_bind_blob(upsertRoot.get(), 2, providerRoot.digest.data(),
                        providerRoot.digest.size(), SQLITE_TRANSIENT);
      sqlite3_bind_int64(upsertRoot.get(), 3, providerRoot.file_count);
      sqlite3_bind_int64(upsertRoot.get(), 4, generation);
      if (sqlite3_step(upsertRoot.get()) != SQLITE_DONE) {
        throwDb(db.get(), "Updating catalog Merkle root");
      }
      providerRoots.push_back(std::move(providerRoot));
    }

    auto archiveMemberIndex = reconcileArchiveManifests(
        db.get(), archiveCandidates, visibleArchives, state);

    std::vector<VfsCatalogDuplicate> duplicates;
    auto overwriteRows = prepare(db.get(),
        "SELECT relative_path,normalized_path,blake3 FROM catalog_files"
        " WHERE root_key=?1 ORDER BY normalized_path;");
    bindText(db.get(), overwriteRows.get(), 1, overwrite_dir);
    auto matchingProvider = prepare(db.get(),
        "SELECT blake3 FROM catalog_files"
        " WHERE root_key=?1 AND normalized_path=?2;");
    while (sqlite3_step(overwriteRows.get()) == SQLITE_ROW) {
      const auto* relative = reinterpret_cast<const char*>(
          sqlite3_column_text(overwriteRows.get(), 0));
      const auto* normalized = reinterpret_cast<const char*>(
          sqlite3_column_text(overwriteRows.get(), 1));
      const void* overwriteHash = sqlite3_column_blob(overwriteRows.get(), 2);
      const int overwriteHashSize = sqlite3_column_bytes(overwriteRows.get(), 2);
      if (relative == nullptr || normalized == nullptr || overwriteHash == nullptr ||
          overwriteHashSize != BLAKE3_OUT_LEN) {
        continue;
      }
      // Later providers have higher priority in the VFS tree, so report the
      // highest-priority enabled mod that contains the same path.
      for (auto mod = mods.rbegin(); mod != mods.rend(); ++mod) {
        sqlite3_reset(matchingProvider.get());
        sqlite3_clear_bindings(matchingProvider.get());
        bindText(db.get(), matchingProvider.get(), 1, mod->second);
        bindText(db.get(), matchingProvider.get(), 2, normalized);
        if (sqlite3_step(matchingProvider.get()) != SQLITE_ROW) continue;
        const void* modHash = sqlite3_column_blob(matchingProvider.get(), 0);
        const int modHashSize = sqlite3_column_bytes(matchingProvider.get(), 0);
        const bool identical = modHash != nullptr && modHashSize == BLAKE3_OUT_LEN &&
            std::memcmp(overwriteHash, modHash, BLAKE3_OUT_LEN) == 0;
        duplicates.push_back({relative, mod->first, mod->second,
                              identical ? VfsDuplicateState::Identical
                                        : VfsDuplicateState::Different});
        break;
      }
    }

    const VfsDigest profileRoot = calculateProfileRoot(providerRoots);
    exec(db.get(), "COMMIT;");
    state.current_file.clear();
    state.current_file_size = 0;
    reportProgress();
    return {std::move(tree), std::move(providerRoots), profileRoot,
            std::move(duplicates), std::move(archiveMemberIndex)};
  } catch (...) {
    sqlite3_exec(db.get(), "ROLLBACK;", nullptr, nullptr, nullptr);
    throw;
  }
}

VfsCatalogRefreshResult VfsCatalog::forceRefreshProviderFiles(
    const std::string& rootKey, const std::string& origin, bool isBacking,
    const std::vector<std::string>& relativePaths)
{
  std::error_code ec;
  fs::create_directories(m_database_path.parent_path(), ec);
  if (ec) {
    throw std::runtime_error("Unable to create local VFS catalog directory: " +
                             ec.message());
  }

  sqlite3* raw = nullptr;
  if (sqlite3_open_v2(m_database_path.c_str(), &raw,
                      SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE |
                          SQLITE_OPEN_FULLMUTEX,
                      nullptr) != SQLITE_OK) {
    DbPtr failed(raw);
    throwDb(raw, "Opening local VFS catalog");
  }
  DbPtr db(raw);
  sqlite3_busy_timeout(db.get(), 30000);
  initializeSchema(db.get());
  exec(db.get(), "BEGIN IMMEDIATE;");
  try {
    const int64_t generation = nextGeneration(db.get());
    auto upsert = prepare(db.get(),
        "INSERT INTO catalog_files(root_key,relative_path,normalized_path,origin,"
        "is_backing,device,inode,size,mode,mtime_ns,ctime_ns,blake3,seen_generation)"
        " VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)"
        " ON CONFLICT(root_key,normalized_path) DO UPDATE SET"
        " relative_path=excluded.relative_path,origin=excluded.origin,"
        " is_backing=excluded.is_backing,device=excluded.device,inode=excluded.inode,"
        " size=excluded.size,mode=excluded.mode,mtime_ns=excluded.mtime_ns,"
        " ctime_ns=excluded.ctime_ns,blake3=excluded.blake3,"
        " seen_generation=excluded.seen_generation;");
    auto remove = prepare(db.get(),
        "DELETE FROM catalog_files WHERE root_key=?1 AND normalized_path=?2;");

    VfsCatalogRefreshResult result;
    result.files.reserve(relativePaths.size());
    for (const std::string& relative : relativePaths) {
      const fs::path relativePath(relative);
      if (relativePath.empty() || relativePath.is_absolute() ||
          std::find(relativePath.begin(), relativePath.end(), fs::path("..")) !=
              relativePath.end()) {
        throw std::runtime_error("Unsafe catalog refresh path: " + relative);
      }
      const std::string normalized = normalizeForLookup(relativePath.generic_string());
      const fs::path full = fs::path(rootKey) / relativePath;
      struct stat st {};
      if (::lstat(full.c_str(), &st) != 0) {
        if (errno != ENOENT) {
          throw std::runtime_error("Unable to inspect catalog refresh path " +
                                   full.string() + ": " + std::strerror(errno));
        }
        sqlite3_reset(remove.get());
        sqlite3_clear_bindings(remove.get());
        bindText(db.get(), remove.get(), 1, rootKey);
        bindText(db.get(), remove.get(), 2, normalized);
        if (sqlite3_step(remove.get()) != SQLITE_DONE) {
          throwDb(db.get(), "Removing missing catalog file");
        }
        result.files.push_back({relativePath.generic_string(), false, {}});
        continue;
      }
      if (!S_ISREG(st.st_mode)) {
        throw std::runtime_error("Catalog refresh path is not a regular file: " +
                                 full.string());
      }

      VfsDigest digest{};
      bool stable = false;
      for (int attempt = 0; attempt < 3; ++attempt) {
        const struct stat before = st;
        digest = hashFile(full);
        if (::lstat(full.c_str(), &st) != 0) {
          throw std::runtime_error("File disappeared while force-hashing: " +
                                   full.string());
        }
        if (sameContentFingerprint(before, st)) {
          stable = true;
          break;
        }
      }
      if (!stable) {
        throw std::runtime_error("File kept changing while force-hashing: " +
                                 full.string());
      }

      sqlite3_reset(upsert.get());
      sqlite3_clear_bindings(upsert.get());
      bindText(db.get(), upsert.get(), 1, rootKey);
      bindText(db.get(), upsert.get(), 2, relativePath.generic_string());
      bindText(db.get(), upsert.get(), 3, normalized);
      bindText(db.get(), upsert.get(), 4, origin);
      sqlite3_bind_int(upsert.get(), 5, isBacking ? 1 : 0);
      sqlite3_bind_int64(upsert.get(), 6, st.st_dev);
      sqlite3_bind_int64(upsert.get(), 7, st.st_ino);
      sqlite3_bind_int64(upsert.get(), 8, st.st_size);
      sqlite3_bind_int64(upsert.get(), 9, st.st_mode & 07777);
      sqlite3_bind_int64(upsert.get(), 10, timespecNs(st.st_mtim));
      sqlite3_bind_int64(upsert.get(), 11, timespecNs(st.st_ctim));
      sqlite3_bind_blob(upsert.get(), 12, digest.data(), digest.size(), SQLITE_TRANSIENT);
      sqlite3_bind_int64(upsert.get(), 13, generation);
      if (sqlite3_step(upsert.get()) != SQLITE_DONE) {
        throwDb(db.get(), "Force-refreshing catalog file");
      }
      result.files.push_back({relativePath.generic_string(), true, digest});
    }

    const Root root{rootKey, rootKey, origin, isBacking};
    result.provider_root = calculateProviderRoot(db.get(), root);
    auto upsertRoot = prepare(db.get(),
        "INSERT INTO catalog_roots(root_key,merkle_root,file_count,generation)"
        " VALUES(?1,?2,?3,?4) ON CONFLICT(root_key) DO UPDATE SET"
        " merkle_root=excluded.merkle_root,file_count=excluded.file_count,"
        " generation=excluded.generation;");
    bindText(db.get(), upsertRoot.get(), 1, rootKey);
    sqlite3_bind_blob(upsertRoot.get(), 2, result.provider_root.digest.data(),
                      result.provider_root.digest.size(), SQLITE_TRANSIENT);
    sqlite3_bind_int64(upsertRoot.get(), 3, result.provider_root.file_count);
    sqlite3_bind_int64(upsertRoot.get(), 4, generation);
    if (sqlite3_step(upsertRoot.get()) != SQLITE_DONE) {
      throwDb(db.get(), "Updating force-refreshed catalog root");
    }
    exec(db.get(), "COMMIT;");
    return result;
  } catch (...) {
    sqlite3_exec(db.get(), "ROLLBACK;", nullptr, nullptr, nullptr);
    throw;
  }
}

void VfsCatalog::invalidateProviderFiles(
    const std::string& rootKey,
    const std::vector<std::string>& relativePaths) noexcept
{
  sqlite3* raw = nullptr;
  if (sqlite3_open_v2(m_database_path.c_str(), &raw,
                      SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX,
                      nullptr) != SQLITE_OK) {
    if (raw != nullptr) sqlite3_close(raw);
    return;
  }
  DbPtr db(raw);
  sqlite3_busy_timeout(db.get(), 30000);
  try {
    initializeSchema(db.get());
    exec(db.get(), "BEGIN IMMEDIATE;");
    auto remove = prepare(db.get(),
        "DELETE FROM catalog_files WHERE root_key=?1 AND normalized_path=?2;");
    for (const std::string& relative : relativePaths) {
      sqlite3_reset(remove.get());
      sqlite3_clear_bindings(remove.get());
      bindText(db.get(), remove.get(), 1, rootKey);
      bindText(db.get(), remove.get(), 2, normalizeForLookup(relative));
      if (sqlite3_step(remove.get()) != SQLITE_DONE) throwDb(db.get(), "Invalidating catalog file");
    }
    auto removeRoot = prepare(db.get(), "DELETE FROM catalog_roots WHERE root_key=?1;");
    bindText(db.get(), removeRoot.get(), 1, rootKey);
    if (sqlite3_step(removeRoot.get()) != SQLITE_DONE) throwDb(db.get(), "Invalidating catalog root");
    exec(db.get(), "COMMIT;");
  } catch (...) {
    sqlite3_exec(db.get(), "ROLLBACK;", nullptr, nullptr, nullptr);
  }
}

std::vector<CachedBaseFile> VfsCatalog::loadBaseSnapshot(
    const std::string& data_dir) const
{
  sqlite3* raw = nullptr;
  if (sqlite3_open_v2(m_database_path.c_str(), &raw,
                      SQLITE_OPEN_READONLY | SQLITE_OPEN_FULLMUTEX,
                      nullptr) != SQLITE_OK) {
    DbPtr failed(raw);
    throwDb(raw, "Opening VFS catalog base snapshot");
  }
  DbPtr db(raw);
  auto stmt = prepare(db.get(),
      "SELECT relative_path,size,mtime_ns,mode FROM catalog_files"
      " WHERE root_key=?1 ORDER BY normalized_path;");
  bindText(db.get(), stmt.get(), 1, data_dir);

  std::vector<CachedBaseFile> files;
  while (sqlite3_step(stmt.get()) == SQLITE_ROW) {
    const auto* path = reinterpret_cast<const char*>(sqlite3_column_text(stmt.get(), 0));
    if (path == nullptr) continue;
    CachedBaseFile file;
    file.relative_path = path;
    file.size = static_cast<uint64_t>(sqlite3_column_int64(stmt.get(), 1));
    file.mtime = std::chrono::system_clock::time_point(
        std::chrono::nanoseconds(sqlite3_column_int64(stmt.get(), 2)));
    file.mode = static_cast<mode_t>(sqlite3_column_int64(stmt.get(), 3));
    files.push_back(std::move(file));
  }
  return files;
}
