#ifndef VFS_STAGINGPROMOTION_H
#define VFS_STAGINGPROMOTION_H

#include "vfscatalog.h"

#include <filesystem>
#include <string>
#include <vector>

enum class StagingPromotionStatus
{
  NothingToDo,
  Promoted,
  Recovered,
  Blocked
};

struct StagingPromotedFile
{
  std::string relative_path;
  VfsDigest digest{};
  uint64_t size = 0;
  unsigned int mode = 0;
};

struct StagingPromotionResult
{
  StagingPromotionStatus status = StagingPromotionStatus::NothingToDo;
  std::vector<StagingPromotedFile> files;
  std::filesystem::path recovery_path;
  std::string message;

  bool blocked() const { return status == StagingPromotionStatus::Blocked; }
};

// Crash-safe promotion of FUSE copy-on-write files.  The journal is created
// before the destination is touched and is retained until every destination
// has been re-hashed successfully.
class StagingPromotion
{
public:
  static constexpr const char* JournalName = ".fluorine-promotion-v1.json";

  static StagingPromotionResult recover(
      const std::filesystem::path& staging,
      const std::filesystem::path& configured_destination);

  static StagingPromotionResult promote(
      const std::filesystem::path& staging,
      const std::filesystem::path& destination);
};

#endif
