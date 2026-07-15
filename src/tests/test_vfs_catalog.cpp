#include "vfs/vfscatalog.h"
#include "vfs/permissionrepair.h"

#include <gtest/gtest.h>
#include <sqlite3.h>

#include <chrono>
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <string>
#include <thread>
#include <sys/stat.h>

namespace fs = std::filesystem;

namespace
{
class TempRoot
{
public:
  TempRoot()
  {
    char path[] = "/tmp/fluorine-catalog-XXXXXX";
    if (const char* result = mkdtemp(path); result != nullptr) m_path = result;
  }
  ~TempRoot()
  {
    std::error_code ec;
    fs::remove_all(m_path, ec);
  }
  const fs::path& path() const { return m_path; }

private:
  fs::path m_path;
};

void writeFile(const fs::path& path, const std::string& contents)
{
  fs::create_directories(path.parent_path());
  std::ofstream stream(path, std::ios::binary | std::ios::trunc);
  ASSERT_TRUE(stream.is_open());
  stream << contents;
}

std::string winnerOrigin(const VfsTree& tree, const std::string& name)
{
  const VfsNode* node = tree.root.resolve({name});
  return node != nullptr && !node->is_directory ? node->file_info.origin : "";
}
}  // namespace

TEST(VfsCatalog, ReusesHashesAndPreservesOverwritePriority)
{
  TempRoot temp;
  ASSERT_FALSE(temp.path().empty());
  const fs::path data = temp.path() / "Data";
  const fs::path mod = temp.path() / "Mod";
  const fs::path overwrite = temp.path() / "overwrite";
  const fs::path db = temp.path() / "catalog.sqlite";

  writeFile(data / "same.txt", "base");
  writeFile(mod / "same.txt", "mod");
  writeFile(overwrite / "same.txt", "overwrite");

  VfsCatalog catalog(db);
  VfsCatalogProgress first;
  VfsCatalogResult initialResult = catalog.reconcileAndBuild(
      data.string(), {{"Test Mod", mod.string()}}, overwrite.string(), true,
      [&](const VfsCatalogProgress& progress) { first = progress; });
  VfsTree initial = std::move(initialResult.tree);
  EXPECT_EQ(first.files_scanned, 3u);
  EXPECT_EQ(first.files_hashed, 3u);
  EXPECT_EQ(winnerOrigin(initial, "same.txt"), "Overwrite");

  VfsCatalogProgress second;
  VfsCatalogResult warmResult = catalog.reconcileAndBuild(
      data.string(), {{"Test Mod", mod.string()}}, overwrite.string(), true,
      [&](const VfsCatalogProgress& progress) { second = progress; });
  VfsTree warm = std::move(warmResult.tree);
  EXPECT_EQ(second.files_scanned, 3u);
  EXPECT_EQ(second.files_hashed, 0u);
  EXPECT_EQ(second.provider_roots_changed, 0u);
  EXPECT_EQ(initialResult.profile_root, warmResult.profile_root);
  ASSERT_EQ(initialResult.provider_roots.size(), warmResult.provider_roots.size());
  for (size_t i = 0; i < initialResult.provider_roots.size(); ++i) {
    EXPECT_EQ(initialResult.provider_roots[i].digest,
              warmResult.provider_roots[i].digest);
  }
  EXPECT_EQ(winnerOrigin(warm, "same.txt"), "Overwrite");

  fs::remove(overwrite / "same.txt");
  VfsTree fallback = std::move(catalog.reconcileAndBuild(
      data.string(), {{"Test Mod", mod.string()}}, overwrite.string(), true).tree);
  EXPECT_EQ(winnerOrigin(fallback, "same.txt"), "Test Mod");
}

TEST(VfsCatalog, MetadataDriftRehashesOnlyChangedFile)
{
  TempRoot temp;
  const fs::path data = temp.path() / "Data";
  const fs::path overwrite = temp.path() / "overwrite";
  writeFile(data / "a.bin", "unchanged content");
  writeFile(data / "b.bin", "other content");
  fs::create_directories(overwrite);

  VfsCatalog catalog(temp.path() / "catalog.sqlite");
  catalog.reconcileAndBuild(data.string(), {}, overwrite.string(), true);

  std::error_code ec;
  const auto oldTime = fs::last_write_time(data / "a.bin", ec);
  ASSERT_FALSE(ec);
  fs::last_write_time(data / "a.bin", oldTime + std::chrono::seconds(1), ec);
  ASSERT_FALSE(ec);

  VfsCatalogProgress progress;
  catalog.reconcileAndBuild(
      data.string(), {}, overwrite.string(), true,
      [&](const VfsCatalogProgress& value) { progress = value; });
  EXPECT_EQ(progress.files_scanned, 2u);
  EXPECT_EQ(progress.files_hashed, 1u);
}

TEST(VfsCatalog, UsesWalJournalMode)
{
  TempRoot temp;
  const fs::path data = temp.path() / "Data";
  const fs::path overwrite = temp.path() / "overwrite";
  writeFile(data / "file.txt", "content");
  fs::create_directories(overwrite);
  const fs::path dbPath = temp.path() / "catalog.sqlite";
  VfsCatalog(dbPath).reconcileAndBuild(data.string(), {}, overwrite.string(), true);

  sqlite3* db = nullptr;
  ASSERT_EQ(sqlite3_open_v2(dbPath.c_str(), &db, SQLITE_OPEN_READONLY, nullptr),
            SQLITE_OK);
  sqlite3_stmt* stmt = nullptr;
  ASSERT_EQ(sqlite3_prepare_v2(db, "PRAGMA journal_mode;", -1, &stmt, nullptr),
            SQLITE_OK);
  ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
  EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)), "wal");
  sqlite3_finalize(stmt);
  sqlite3_close(db);
}

TEST(VfsCatalog, UpgradesVersionOneCatalogWithoutRehashing)
{
  TempRoot temp;
  const fs::path data = temp.path() / "Data";
  const fs::path overwrite = temp.path() / "overwrite";
  const fs::path dbPath = temp.path() / "catalog.sqlite";
  writeFile(data / "file.txt", "content");
  fs::create_directories(overwrite);

  VfsCatalog(dbPath).reconcileAndBuild(data.string(), {}, overwrite.string(), true);
  sqlite3* db = nullptr;
  ASSERT_EQ(sqlite3_open(dbPath.c_str(), &db), SQLITE_OK);
  ASSERT_EQ(sqlite3_exec(
                db,
                "UPDATE catalog_meta SET value=1 WHERE key='schema_version';"
                "DROP TABLE catalog_roots;",
                nullptr, nullptr, nullptr),
            SQLITE_OK);
  sqlite3_close(db);

  VfsCatalogProgress progress;
  const auto upgraded = VfsCatalog(dbPath).reconcileAndBuild(
      data.string(), {}, overwrite.string(), true,
      [&](const VfsCatalogProgress& value) { progress = value; });
  EXPECT_EQ(progress.files_hashed, 0u);
  EXPECT_EQ(upgraded.provider_roots.size(), 2u);

  ASSERT_EQ(sqlite3_open_v2(dbPath.c_str(), &db, SQLITE_OPEN_READONLY, nullptr),
            SQLITE_OK);
  sqlite3_stmt* stmt = nullptr;
  ASSERT_EQ(sqlite3_prepare_v2(
                db, "SELECT value FROM catalog_meta WHERE key='schema_version';",
                -1, &stmt, nullptr),
            SQLITE_OK);
  ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
  EXPECT_EQ(sqlite3_column_int(stmt, 0), 2);
  sqlite3_finalize(stmt);
  sqlite3_close(db);
}

TEST(VfsCatalog, MerkleRootsTrackContentAndPriorityIndependently)
{
  TempRoot temp;
  const fs::path data = temp.path() / "Data";
  const fs::path firstMod = temp.path() / "First";
  const fs::path secondMod = temp.path() / "Second";
  const fs::path overwrite = temp.path() / "overwrite";
  writeFile(data / "base.bin", "base");
  writeFile(firstMod / "one.bin", "one");
  writeFile(secondMod / "two.bin", "two");
  fs::create_directories(overwrite);

  VfsCatalog catalog(temp.path() / "catalog.sqlite");
  auto original = catalog.reconcileAndBuild(
      data.string(), {{"First", firstMod.string()}, {"Second", secondMod.string()}},
      overwrite.string(), true);
  VfsCatalogProgress reorderedProgress;
  auto reordered = catalog.reconcileAndBuild(
      data.string(), {{"Second", secondMod.string()}, {"First", firstMod.string()}},
      overwrite.string(), true,
      [&](const VfsCatalogProgress& value) { reorderedProgress = value; });

  EXPECT_EQ(reorderedProgress.files_hashed, 0u);
  EXPECT_EQ(reorderedProgress.provider_roots_changed, 0u);
  EXPECT_NE(original.profile_root, reordered.profile_root);
  ASSERT_EQ(original.provider_roots.size(), reordered.provider_roots.size());
  for (const auto& before : original.provider_roots) {
    const auto after = std::find_if(
        reordered.provider_roots.begin(), reordered.provider_roots.end(),
        [&](const VfsProviderRoot& root) { return root.root_key == before.root_key; });
    ASSERT_NE(after, reordered.provider_roots.end());
    EXPECT_EQ(before.digest, after->digest);
  }

  writeFile(firstMod / "one.bin", "changed contents");
  VfsCatalogProgress changedProgress;
  auto changed = catalog.reconcileAndBuild(
      data.string(), {{"First", firstMod.string()}, {"Second", secondMod.string()}},
      overwrite.string(), true,
      [&](const VfsCatalogProgress& value) { changedProgress = value; });
  EXPECT_EQ(changedProgress.files_hashed, 1u);
  EXPECT_EQ(changedProgress.provider_roots_changed, 1u);
  EXPECT_NE(original.profile_root, changed.profile_root);
}

TEST(PermissionRepair, IsIdempotentAndDoesNotFollowSymlinks)
{
  TempRoot temp;
  const fs::path game = temp.path() / "game";
  const fs::path directory = game / "subdir";
  const fs::path file = directory / "archive.bin";
  const fs::path outside = temp.path() / "outside.bin";
  writeFile(file, "game data");
  writeFile(outside, "outside");
  ASSERT_EQ(::chmod(game.c_str(), 0500), 0);
  ASSERT_EQ(::chmod(directory.c_str(), 0500), 0);
  ASSERT_EQ(::chmod(file.c_str(), 0400), 0);
  ASSERT_EQ(::chmod(outside.c_str(), 0400), 0);
  std::error_code ec;
  fs::create_symlink(outside, game / "outside-link", ec);
  ASSERT_FALSE(ec);

  const PermissionRepairStats first = repairGameDirectoryPermissions(game);
  EXPECT_EQ(first.repaired, 3u);
  EXPECT_EQ(first.failed, 0u);

  struct stat before {};
  ASSERT_EQ(::lstat(file.c_str(), &before), 0);
  const PermissionRepairStats second = repairGameDirectoryPermissions(game);
  struct stat after {};
  ASSERT_EQ(::lstat(file.c_str(), &after), 0);
  EXPECT_EQ(second.repaired, 0u);
  EXPECT_EQ(second.failed, 0u);
  EXPECT_EQ(before.st_ctim.tv_sec, after.st_ctim.tv_sec);
  EXPECT_EQ(before.st_ctim.tv_nsec, after.st_ctim.tv_nsec);
  EXPECT_EQ(after.st_mode & 0777, 0600);

  struct stat outsideStatus {};
  ASSERT_EQ(::lstat(outside.c_str(), &outsideStatus), 0);
  EXPECT_EQ(outsideStatus.st_mode & 0777, 0400);
}
