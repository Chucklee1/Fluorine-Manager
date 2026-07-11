#include "vfs/vfscatalog.h"

#include <gtest/gtest.h>
#include <sqlite3.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>
#include <thread>

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
  VfsTree initial = catalog.reconcileAndBuild(
      data.string(), {{"Test Mod", mod.string()}}, overwrite.string(), true,
      [&](const VfsCatalogProgress& progress) { first = progress; });
  EXPECT_EQ(first.files_scanned, 3u);
  EXPECT_EQ(first.files_hashed, 3u);
  EXPECT_EQ(winnerOrigin(initial, "same.txt"), "Overwrite");

  VfsCatalogProgress second;
  VfsTree warm = catalog.reconcileAndBuild(
      data.string(), {{"Test Mod", mod.string()}}, overwrite.string(), true,
      [&](const VfsCatalogProgress& progress) { second = progress; });
  EXPECT_EQ(second.files_scanned, 3u);
  EXPECT_EQ(second.files_hashed, 0u);
  EXPECT_EQ(winnerOrigin(warm, "same.txt"), "Overwrite");

  fs::remove(overwrite / "same.txt");
  VfsTree fallback = catalog.reconcileAndBuild(
      data.string(), {{"Test Mod", mod.string()}}, overwrite.string(), true);
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
