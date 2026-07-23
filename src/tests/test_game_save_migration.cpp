#include "vfs/gamesavemigration.h"

#include <gtest/gtest.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>

namespace
{
namespace fs = std::filesystem;

class TemporaryDirectory
{
public:
  TemporaryDirectory()
      : m_path(fs::temp_directory_path() /
               ("fluorine-save-migration-" +
                std::to_string(
                    std::chrono::steady_clock::now().time_since_epoch().count())))
  {
    fs::create_directories(m_path);
  }

  ~TemporaryDirectory()
  {
    std::error_code ignored;
    fs::remove_all(m_path, ignored);
  }

  const fs::path& path() const { return m_path; }

private:
  fs::path m_path;
};

void writeFile(const fs::path& path, const std::string& contents)
{
  fs::create_directories(path.parent_path());
  std::ofstream output(path, std::ios::binary | std::ios::trunc);
  ASSERT_TRUE(output.is_open());
  output << contents;
  ASSERT_TRUE(output.good());
}

std::string readFile(const fs::path& path)
{
  std::ifstream input(path, std::ios::binary);
  return {std::istreambuf_iterator<char>(input),
          std::istreambuf_iterator<char>()};
}
}  // namespace

TEST(GameSaveMigration, MovesNestedOverwriteSavesIntoGameDirectory)
{
  TemporaryDirectory temporary;
  const fs::path gameData = temporary.path() / "game";
  const fs::path gameSaves = gameData / "www" / "save";
  const fs::path overwrite = temporary.path() / "overwrite";
  const fs::path overwriteSaves = overwrite / "www" / "save";

  writeFile(gameSaves / "file1.rpgsave", "old");
  writeFile(overwriteSaves / "file1.rpgsave", "new");
  writeFile(overwriteSaves / "nested" / "file2.rpgsave", "nested");

  const auto stats =
      MOBase::Vfs::migrateGameLocalSaves(gameData, gameSaves, overwrite);

  EXPECT_EQ(stats.relativePath, "www/save");
  EXPECT_EQ(stats.inspected, 2);
  EXPECT_EQ(stats.moved, 2);
  EXPECT_EQ(stats.failed, 0);
  EXPECT_EQ(readFile(gameSaves / "file1.rpgsave"), "new");
  EXPECT_EQ(readFile(gameSaves / "nested" / "file2.rpgsave"), "nested");
  EXPECT_FALSE(fs::exists(overwriteSaves));
}

TEST(GameSaveMigration, IgnoresSaveDirectoryOutsideGameData)
{
  TemporaryDirectory temporary;
  const fs::path gameData = temporary.path() / "game";
  const fs::path gameSaves = temporary.path() / "documents" / "saves";
  const fs::path overwrite = temporary.path() / "overwrite";
  writeFile(overwrite / "save" / "file.rpgsave", "untouched");

  const auto stats =
      MOBase::Vfs::migrateGameLocalSaves(gameData, gameSaves, overwrite);

  EXPECT_TRUE(stats.relativePath.empty());
  EXPECT_EQ(stats.inspected, 0);
  EXPECT_EQ(stats.moved, 0);
  EXPECT_TRUE(fs::exists(overwrite / "save" / "file.rpgsave"));
  EXPECT_FALSE(fs::exists(gameSaves / "file.rpgsave"));
}

TEST(GameSaveMigration, SkipsSymlinksInOverwrite)
{
  TemporaryDirectory temporary;
  const fs::path gameData = temporary.path() / "game";
  const fs::path gameSaves = gameData / "www" / "save";
  const fs::path overwrite = temporary.path() / "overwrite";
  const fs::path outside = temporary.path() / "outside.rpgsave";
  writeFile(outside, "outside");
  fs::create_directories(overwrite / "www" / "save");
  fs::create_symlink(outside,
                     overwrite / "www" / "save" / "linked.rpgsave");

  const auto stats =
      MOBase::Vfs::migrateGameLocalSaves(gameData, gameSaves, overwrite);

  EXPECT_EQ(stats.inspected, 0);
  EXPECT_EQ(stats.moved, 0);
  EXPECT_EQ(stats.skipped, 1);
  EXPECT_EQ(readFile(outside), "outside");
  EXPECT_FALSE(fs::exists(gameSaves / "linked.rpgsave"));
}
