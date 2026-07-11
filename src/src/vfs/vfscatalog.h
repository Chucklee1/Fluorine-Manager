#ifndef VFS_VFSCATALOG_H
#define VFS_VFSCATALOG_H

#include "vfstree.h"

#include <cstdint>
#include <filesystem>
#include <functional>
#include <string>
#include <utility>
#include <vector>

struct VfsCatalogProgress
{
  uint64_t files_scanned = 0;
  uint64_t files_hashed = 0;
  uint64_t bytes_hashed = 0;
  std::string current_root;
};

// Persistent per-machine inventory of all VFS providers. The SQLite database
// is always stored in Fluorine's local cache; indexed roots may live on any
// local or network filesystem. SQLite is never consulted by FUSE handlers.
class VfsCatalog
{
public:
  using ProgressCallback = std::function<void(const VfsCatalogProgress&)>;

  explicit VfsCatalog(std::filesystem::path database_path);

  static std::filesystem::path databasePath(const std::string& data_dir);

  // Reconcile every provider using cheap stat fingerprints, BLAKE3-hash only
  // new/changed files, resolve conflicts, and return one immutable generation.
  VfsTree reconcileAndBuild(
      const std::string& data_dir,
      const std::vector<std::pair<std::string, std::string>>& mods,
      const std::string& overwrite_dir,
      bool scan_base,
      ProgressCallback progress = {});

  // Snapshot used only for in-session rebuilds after the real data directory
  // is hidden by the FUSE mount.
  std::vector<CachedBaseFile> loadBaseSnapshot(const std::string& data_dir) const;

private:
  std::filesystem::path m_database_path;
};

#endif
