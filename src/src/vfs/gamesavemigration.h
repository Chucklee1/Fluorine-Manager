#ifndef VFS_GAMESAVEMIGRATION_H
#define VFS_GAMESAVEMIGRATION_H

#include <algorithm>
#include <filesystem>
#include <string>
#include <vector>

namespace MOBase::Vfs
{

struct GameSaveMigrationStats
{
  std::size_t inspected = 0;
  std::size_t moved     = 0;
  std::size_t skipped   = 0;
  std::size_t failed    = 0;
  std::string relativePath;
};

inline bool strictRelativePath(const std::filesystem::path& root,
                               const std::filesystem::path& child,
                               std::filesystem::path& relative)
{
  const auto cleanRoot  = std::filesystem::absolute(root).lexically_normal();
  const auto cleanChild = std::filesystem::absolute(child).lexically_normal();
  relative              = cleanChild.lexically_relative(cleanRoot);
  if (relative.empty() || relative == "." || relative.is_absolute()) {
    return false;
  }
  const auto first = relative.begin();
  return first != relative.end() && *first != "..";
}

// Game-local save directories (RPG Maker's www/save, for example) sit below
// the FUSE data root, so ordinary copy-on-write sends their changes to
// Overwrite. Once FUSE is unmounted, move just that subtree back into the real
// game save directory. Each destination is replaced atomically from a sibling
// temporary file; the Overwrite copy is removed only after that succeeds.
inline GameSaveMigrationStats migrateGameLocalSaves(
    const std::filesystem::path& gameDataDir,
    const std::filesystem::path& gameSavesDir,
    const std::filesystem::path& overwriteDir)
{
  namespace fs = std::filesystem;

  GameSaveMigrationStats stats;
  fs::path relative;
  if (!strictRelativePath(gameDataDir, gameSavesDir, relative)) {
    return stats;
  }
  stats.relativePath = relative.generic_string();

  const fs::path sourceRoot = (overwriteDir / relative).lexically_normal();
  const fs::path targetRoot = fs::absolute(gameSavesDir).lexically_normal();
  std::error_code ec;
  if (!fs::is_directory(sourceRoot, ec) || ec) {
    return stats;
  }

  std::vector<fs::path> directories{sourceRoot};
  const fs::path cleanOverwrite = fs::absolute(overwriteDir).lexically_normal();
  for (fs::path parent = sourceRoot.parent_path(); parent != cleanOverwrite &&
                                                    parent.has_relative_path();
       parent = parent.parent_path()) {
    directories.push_back(parent);
  }
  fs::recursive_directory_iterator it(
      sourceRoot, fs::directory_options::skip_permission_denied, ec);
  const fs::recursive_directory_iterator end;
  while (it != end) {
    if (ec) {
      ++stats.failed;
      ec.clear();
      it.increment(ec);
      continue;
    }

    const fs::directory_entry entry = *it;
    if (entry.is_symlink(ec)) {
      ++stats.skipped;
      if (entry.is_directory(ec)) {
        it.disable_recursion_pending();
      }
      ec.clear();
      it.increment(ec);
      continue;
    }
    if (entry.is_directory(ec)) {
      directories.push_back(entry.path());
      ec.clear();
      it.increment(ec);
      continue;
    }
    if (!entry.is_regular_file(ec) || ec) {
      ++stats.skipped;
      ec.clear();
      it.increment(ec);
      continue;
    }

    ++stats.inspected;
    const fs::path fileRelative = entry.path().lexically_relative(sourceRoot);
    const fs::path destination  = targetRoot / fileRelative;
    const fs::path temporary = destination.string() + ".fluorine-save-migrate.tmp";
    const auto modified = entry.last_write_time(ec);
    ec.clear();

    fs::create_directories(destination.parent_path(), ec);
    if (ec) {
      ++stats.failed;
      ec.clear();
      it.increment(ec);
      continue;
    }
    fs::remove(temporary, ec);
    ec.clear();
    fs::copy_file(entry.path(), temporary, fs::copy_options::overwrite_existing, ec);
    if (ec) {
      ++stats.failed;
      ec.clear();
      it.increment(ec);
      continue;
    }
    fs::rename(temporary, destination, ec);
    if (ec) {
      ++stats.failed;
      fs::remove(temporary, ec);
      ec.clear();
      it.increment(ec);
      continue;
    }
    if (modified != fs::file_time_type::min()) {
      fs::last_write_time(destination, modified, ec);
      ec.clear();
    }
    if (!fs::remove(entry.path(), ec) || ec) {
      ++stats.failed;
      ec.clear();
    } else {
      ++stats.moved;
    }
    it.increment(ec);
  }

  std::sort(directories.begin(), directories.end(),
            [](const fs::path& left, const fs::path& right) {
              return left.native().size() > right.native().size();
            });
  for (const auto& directory : directories) {
    fs::remove(directory, ec);  // Removes empty directories only.
    ec.clear();
  }
  return stats;
}

}  // namespace MOBase::Vfs

#endif  // VFS_GAMESAVEMIGRATION_H
