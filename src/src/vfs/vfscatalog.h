#ifndef VFS_VFSCATALOG_H
#define VFS_VFSCATALOG_H

#include "vfstree.h"

#include <array>
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
  uint64_t provider_roots_changed = 0;
  uint64_t current_file_size = 0;
  uint64_t elapsed_ms = 0;
  double hash_mib_per_second = 0.0;
  std::string current_root;
  std::string current_file;
};

using VfsDigest = std::array<unsigned char, 32>;

struct VfsProviderRoot
{
  std::string root_key;
  std::string origin;
  bool is_backing = false;
  uint64_t file_count = 0;
  VfsDigest digest{};
};

struct VfsCatalogResult
{
  VfsTree tree;
  std::vector<VfsProviderRoot> provider_roots;
  VfsDigest profile_root{};
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
  VfsCatalogResult reconcileAndBuild(
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
