#ifndef VFS_RUNTIMEINDEX_H
#define VFS_RUNTIMEINDEX_H

#include "inodetable.h"
#include "vfstree.h"

#include <chrono>
#include <cstdint>
#include <memory>
#include <optional>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>

#include <sys/stat.h>
#include <sys/types.h>

struct VfsIndexedNode
{
  uint64_t ino = 0;
  std::string virtual_path;
  std::string real_path;
  std::string origin;
  bool is_directory = false;
  bool is_backing = false;
  uint64_t size = 0;
  std::chrono::system_clock::time_point mtime;
  mode_t cached_mode = 0;
  struct stat attr {};
};

enum class VfsLookupSource
{
  Base,
  Overlay,
  Negative,
  Tombstone,
  Missing,
};

struct VfsIndexedLookup
{
  VfsLookupSource source = VfsLookupSource::Missing;
  std::string canonical_name;
  std::optional<VfsIndexedNode> node;
};

// Immutable positive lookup generation with a small mutable runtime overlay.
// Base entries are never evicted. Creates, replacements and tombstones live in
// the overlay; genuine absent probes live in the separate negative cache.
class VfsRuntimeIndex
{
public:
  static std::shared_ptr<VfsRuntimeIndex> build(
      const VfsTree& tree, InodeTable& inodes, uid_t uid, gid_t gid);

  VfsIndexedLookup lookup(uint64_t parent, const std::string& name) const;
  std::optional<VfsIndexedNode> node(uint64_t ino) const;

  void publish(uint64_t parent, const std::string& name,
               const VfsIndexedNode& node);
  void tombstone(uint64_t parent, const std::string& name, uint64_t ino = 0);
  void recordNegative(uint64_t parent, const std::string& name,
                      std::chrono::seconds ttl);
  void eraseNegative(uint64_t parent, const std::string& name);

  std::size_t baseLookupCount() const;
  std::size_t baseNodeCount() const;
  std::size_t overlayCount() const;
  std::size_t negativeCount() const;

  static VfsIndexedNode makeFileNode(
      uint64_t ino, std::string virtualPath, std::string realPath,
      std::string origin, bool isBacking, uint64_t size,
      std::chrono::system_clock::time_point mtime, mode_t cachedMode,
      uid_t uid, gid_t gid);
  static VfsIndexedNode makeDirectoryNode(
      uint64_t ino, std::string virtualPath, uid_t uid, gid_t gid);

private:
  struct LookupKey
  {
    uint64_t parent = 0;
    std::string name;

    bool operator==(const LookupKey&) const = default;
  };

  struct LookupKeyHash
  {
    std::size_t operator()(const LookupKey& key) const;
  };

  struct Child
  {
    uint64_t ino = 0;
    std::string canonical_name;
  };

  struct OverlayChild
  {
    bool tombstone = false;
    Child child;
  };

  using BaseLookupMap = std::unordered_map<LookupKey, Child, LookupKeyHash>;
  using OverlayLookupMap =
      std::unordered_map<LookupKey, OverlayChild, LookupKeyHash>;

  BaseLookupMap m_baseLookups;
  std::unordered_map<uint64_t, VfsIndexedNode> m_baseNodes;

  mutable std::shared_mutex m_overlayMutex;
  OverlayLookupMap m_overlayLookups;
  std::unordered_map<uint64_t, VfsIndexedNode> m_overlayNodes;
  std::unordered_set<uint64_t> m_hiddenInodes;
  std::unordered_map<LookupKey, std::chrono::steady_clock::time_point,
                     LookupKeyHash>
      m_negativeLookups;
};

#endif
