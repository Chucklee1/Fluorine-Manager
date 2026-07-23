#include "scancache.h"

#include "../fluorinepaths.h"

#include <QDir>
#include <QString>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <functional>
#include <system_error>

namespace fs = std::filesystem;

namespace
{
constexpr uint32_t kMagic   = 0x43564C46u;  // "FLVC"
constexpr uint32_t kVersion = 3u;  // v3 also persists optional catalog digests

template <typename T>
bool writePod(std::ostream& out, const T& v)
{
  out.write(reinterpret_cast<const char*>(&v), sizeof(T));
  return out.good();
}

template <typename T>
bool readPod(std::istream& in, T& v)
{
  in.read(reinterpret_cast<char*>(&v), sizeof(T));
  return in.good();
}

bool writeStr(std::ostream& out, const std::string& s)
{
  uint32_t len = static_cast<uint32_t>(s.size());
  if (!writePod(out, len)) return false;
  if (len > 0) out.write(s.data(), len);
  return out.good();
}

bool readStr(std::istream& in, std::string& s)
{
  uint32_t len = 0;
  if (!readPod(in, len)) return false;
  // Sanity bound: 1 MB per string is enough for any path we care about.
  if (len > 1u * 1024u * 1024u) return false;
  s.resize(len);
  if (len > 0) in.read(s.data(), len);
  return in.good();
}

// Returns -1 if stat fails.  Nanosecond precision; fs::file_time_type's
// epoch is implementation-defined, so we go through the same conversion
// used elsewhere by reading via std::filesystem and comparing as int64.
int64_t mtimeNs(const fs::path& p)
{
  std::error_code ec;
  auto t = fs::last_write_time(p, ec);
  if (ec) return -1;
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
             t.time_since_epoch())
      .count();
}

uint64_t fileSize(const fs::path& p)
{
  std::error_code ec;
  auto s = fs::file_size(p, ec);
  if (ec) return 0;
  return static_cast<uint64_t>(s);
}

// Stable 64-bit hash (FNV-1a) over a string.  Used to derive a unique
// cache filename from the mount config so different instances don't
// step on each other's cache.
uint64_t hash64(const std::string& s)
{
  uint64_t h = 1469598103934665603ULL;
  for (unsigned char c : s) {
    h ^= c;
    h *= 1099511628211ULL;
  }
  return h;
}
}  // namespace

fs::path ScanCache::cacheFilePath(const ScanCacheKey& key)
{
  // Cache key fingerprint = data_dir + overwrite_dir + ordered mod paths.
  // Hashing keeps the filename short and filesystem-safe; the full key
  // is re-validated inside tryLoad() so collisions can't produce a stale
  // hit, only a wasted load attempt.
  std::string fp;
  fp.reserve(4096);
  fp += key.data_dir.string();
  fp += '\0';
  fp += key.overwrite_dir.string();
  fp += '\0';
  for (const auto& [name, path] : key.mods) {
    fp += name;
    fp += '\0';
    fp += path;
    fp += '\0';
  }

  char buf[32];
  std::snprintf(buf, sizeof(buf), "%016llx.vfscache",
                static_cast<unsigned long long>(hash64(fp)));

  const QString dir = fluorineVfsCacheDir();
  return fs::path(dir.toStdString()) / buf;
}

ScanCache::ScanCache(fs::path cache_file)
    : m_cache_file(std::move(cache_file))
{}

std::shared_ptr<VfsTree> ScanCache::tryLoad(const ScanCacheKey& key)
{
  std::ifstream in(m_cache_file, std::ios::binary);
  if (!in) return nullptr;

  // 1. Header
  uint32_t magic = 0, version = 0;
  if (!readPod(in, magic) || magic != kMagic) return nullptr;
  if (!readPod(in, version) || version != kVersion) return nullptr;

  // 2. modlist.txt mtime + size (skipped if path empty)
  uint8_t hasModlist = 0;
  if (!readPod(in, hasModlist)) return nullptr;
  if (hasModlist) {
    int64_t cachedMtime = 0;
    uint64_t cachedSize = 0;
    if (!readPod(in, cachedMtime) || !readPod(in, cachedSize)) return nullptr;
    if (cachedMtime != mtimeNs(key.modlist_txt)) return nullptr;
    if (cachedSize != fileSize(key.modlist_txt)) return nullptr;
  }

  // 3. data_dir mtime
  int64_t dataMtime = 0;
  if (!readPod(in, dataMtime)) return nullptr;
  if (dataMtime != mtimeNs(key.data_dir)) return nullptr;

  // 4. overwrite_dir mtime
  int64_t overwriteMtime = 0;
  if (!readPod(in, overwriteMtime)) return nullptr;
  if (overwriteMtime != mtimeNs(key.overwrite_dir)) return nullptr;

  // 5. Per-mod check (count + name + path + dir mtime, in order)
  uint32_t modCount = 0;
  if (!readPod(in, modCount)) return nullptr;
  if (modCount != key.mods.size()) return nullptr;

  for (uint32_t i = 0; i < modCount; ++i) {
    std::string name, path;
    int64_t modMtime = 0;
    if (!readStr(in, name) || !readStr(in, path) || !readPod(in, modMtime)) {
      return nullptr;
    }
    if (name != key.mods[i].first) return nullptr;
    if (path != key.mods[i].second) return nullptr;
    if (modMtime != mtimeNs(path)) return nullptr;
  }

  // 6. Tree counts
  uint64_t fileCount = 0, dirCount = 0;
  if (!readPod(in, fileCount) || !readPod(in, dirCount)) return nullptr;

  // 7. Deserialize tree
  auto tree            = std::make_shared<VfsTree>();
  tree->root.is_directory = true;
  if (!deserializeNode(in, tree->root)) return nullptr;

  tree->file_count = static_cast<size_t>(fileCount);
  tree->dir_count  = static_cast<size_t>(dirCount);
  return tree;
}

bool ScanCache::save(const ScanCacheKey& key, const VfsTree& tree)
{
  std::error_code ec;
  fs::create_directories(m_cache_file.parent_path(), ec);

  // Atomic write: serialize to temp, rename over.  A torn write is
  // detectable on read (header check or short read) but renaming
  // avoids leaving a partial cache file behind on crash.
  fs::path tmp = m_cache_file;
  tmp += ".tmp";

  {
    std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
    if (!out) return false;

    if (!writePod(out, kMagic)) return false;
    if (!writePod(out, kVersion)) return false;

    uint8_t hasModlist = key.modlist_txt.empty() ? 0 : 1;
    if (!writePod(out, hasModlist)) return false;
    if (hasModlist) {
      int64_t mtime  = mtimeNs(key.modlist_txt);
      uint64_t size  = fileSize(key.modlist_txt);
      if (!writePod(out, mtime)) return false;
      if (!writePod(out, size)) return false;
    }

    int64_t dataMtime = mtimeNs(key.data_dir);
    if (!writePod(out, dataMtime)) return false;
    int64_t overwriteMtime = mtimeNs(key.overwrite_dir);
    if (!writePod(out, overwriteMtime)) return false;

    uint32_t modCount = static_cast<uint32_t>(key.mods.size());
    if (!writePod(out, modCount)) return false;
    for (const auto& [name, path] : key.mods) {
      if (!writeStr(out, name)) return false;
      if (!writeStr(out, path)) return false;
      int64_t modMtime = mtimeNs(path);
      if (!writePod(out, modMtime)) return false;
    }

    uint64_t fileCount = static_cast<uint64_t>(tree.file_count);
    uint64_t dirCount  = static_cast<uint64_t>(tree.dir_count);
    if (!writePod(out, fileCount)) return false;
    if (!writePod(out, dirCount)) return false;

    if (!serializeNode(out, tree.root)) return false;
    out.flush();
    if (!out.good()) return false;
  }

  fs::rename(tmp, m_cache_file, ec);
  if (ec) {
    fs::remove(tmp, ec);
    return false;
  }
  return true;
}

void ScanCache::invalidate()
{
  std::error_code ec;
  fs::remove(m_cache_file, ec);
}
