#ifndef VFS_VFSINDEX_H
#define VFS_VFSINDEX_H

#include "vfscatalog.h"

#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

inline constexpr int kVfsIndexFormatVersion = 1;
inline constexpr int kVfsIndexSchemaVersion = 1;
inline constexpr int kVfsIndexApplicationId = 0x56465349;  // "VFSI"
inline constexpr const char* kVfsIndexFormatName = "vfs-index";
inline constexpr const char* kVfsIndexNormalization =
    "utf8-nfc-casefold-v1";
inline constexpr const char* kVfsIndexLocatorName = "vfs-index.json";
inline constexpr const char* kVfsIndexVirtualLocator =
    "SKSE/Plugins/VFSIndexer/vfs-index.json";
inline constexpr const char* kLegacyVfsIndexLocatorName =
    "fluorine-vfs-index.json";
inline constexpr const char* kLegacyVfsIndexVirtualLocator =
    "SKSE/Plugins/Fluorine/fluorine-vfs-index.json";

enum class VfsIndexConsumerPathStyle
{
  NativeWindows,
  Wine
};

struct VfsIndexPublicationContext
{
  std::filesystem::path output_base;
  std::string producer = "Fluorine";
  std::string instance_name;
  std::string profile_name;
  VfsIndexConsumerPathStyle consumer_path_style =
      VfsIndexConsumerPathStyle::Wine;
};

struct VfsIndexPublicationResult
{
  bool success = false;
  std::string error;
  std::string generation;
  VfsDigest resolved_snapshot_digest{};
  std::filesystem::path database_path;
  std::filesystem::path locator_path;
  std::filesystem::path root_locator_path;
  bool root_locator_deployed = false;
  std::size_t file_count = 0;
};

struct VfsIndexLocator
{
  std::string format;
  int format_version = 0;
  int schema_version = 0;
  std::string state;
  std::string generation;
  std::string producer;
  std::string instance_name;
  std::string profile_name;
  std::optional<VfsDigest> profile_digest;
  VfsDigest resolved_snapshot_digest{};
  std::string path_normalization;
  std::string host_path_style;
  std::string host_database_path;
  std::string consumer_database_path;
  int64_t published_utc_ms = 0;
};

struct VfsIndexResolvedFile
{
  std::string normalized_path;
  std::string display_path;
  std::string host_path;
  std::string consumer_path;
  std::string origin;
  uint64_t size = 0;
  uint32_t mode = 0;
  int64_t mtime_ns = 0;
  bool is_backing = false;
  std::optional<VfsDigest> blake3;
};

struct VfsIndexValidated
{
  VfsIndexLocator locator;
  std::vector<VfsIndexResolvedFile> files;
  std::shared_ptr<const VfsArchiveMemberIndex> archive_members;
};

struct VfsIndexValidationResult
{
  std::optional<VfsIndexValidated> index;
  std::string error;

  explicit operator bool() const { return index.has_value(); }
};

class VfsIndexValidator
{
public:
  using DatabasePathResolver =
      std::function<std::optional<std::filesystem::path>(const std::string&)>;

  // Consumer skeleton: parse the mapped locator, resolve its Windows-visible
  // database path, then reject the whole generation on any mismatch.
  static VfsIndexValidationResult validate(
      const std::filesystem::path& locator_path,
      DatabasePathResolver resolver = {});

  // Producer-side validation uses the host path directly but performs the
  // same database checks as the consumer.
  static VfsIndexValidationResult validateDatabase(
      const std::filesystem::path& database_path,
      const VfsIndexLocator& locator);

  static std::optional<VfsIndexLocator> parseLocator(
      const std::filesystem::path& locator_path, std::string& error);
  static bool isAbsoluteConsumerPath(const std::string& path);
  static bool isAbsoluteHostPath(const std::string& path,
                                 const std::string& style);
  static std::optional<std::filesystem::path> resolveWinePathOnHost(
      const std::string& path);
};

class VfsIndexPublisher
{
public:
  VfsIndexPublicationResult publish(
      VfsTree& tree,
      const std::vector<VfsProviderRoot>& provider_roots,
      const VfsDigest& profile_digest,
      const std::filesystem::path& data_directory,
      const VfsIndexPublicationContext& context,
      std::shared_ptr<const VfsArchiveMemberIndex> archive_members =
          {}) noexcept;

  static std::string toConsumerPath(
      const std::filesystem::path& path,
      VfsIndexConsumerPathStyle style);

  // These paths are reserved by the publication contract. Removing them
  // before either success or failure prevents a stale/mod-provided locator
  // from becoming visible for the launch.
  static void removePublicationArtifacts(VfsTree& tree);
};

#endif
