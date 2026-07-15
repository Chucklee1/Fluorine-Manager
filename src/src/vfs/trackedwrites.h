#ifndef VFS_TRACKEDWRITES_H
#define VFS_TRACKEDWRITES_H

#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

// Tracks files that the user has moved from Overwrite into a mod folder.
// When the VFS sees a write to a tracked file, the write goes in-place to
// the mod folder instead of creating a new copy in Overwrite (COW).
//
// Tracking is updated when:
//   - Files are moved from Overwrite via the MO2 UI (sync, create mod,
//     move to existing mod, drag-and-drop).
//   - Manual moves are detected at VFS mount time by comparing the current
//     Overwrite contents against a saved snapshot from the previous session.
//
// The tracking data is persisted as a JSON file in the instance directory.

class TrackedWrites
{
public:
  TrackedWrites() = default;

  // Load tracking data from a JSON file.
  // Mod paths are stored relative to the JSON file's parent directory for
  // portability.  They are resolved to absolute paths on load.
  void load(const std::string& path);

  // Save tracking data to a JSON file.
  // Absolute mod paths are converted to relative (relative to the JSON file's
  // parent directory) before writing.
  void save(const std::string& path) const;

  // Remove entries whose mod folder no longer exists on disk.
  // Called automatically after load(), but can also be called explicitly.
  void pruneStale();

  // Record that a file at relative_path now lives in mod_folder_path.
  // mod_folder_path is the absolute path to the mod's root directory.
  void track(const std::string& relative_path, const std::string& mod_folder_path);

  // Remove tracking for a file (e.g. if the user deletes it or moves it back).
  void untrack(const std::string& relative_path);

  // Check if a file is tracked.  If so, returns the absolute path to the
  // mod folder it should be written to.  Returns empty string if not tracked.
  std::string modFolderFor(const std::string& relative_path) const;

  // Snapshot the contents of the overwrite directory (relative paths).
  // Call this at unmount time so we can detect manual moves on next mount.
  void snapshotOverwrite(const std::string& overwrite_dir);

  // Detect files that disappeared from overwrite since the last snapshot
  // and now exist in a mod folder.  Adds them to tracking automatically.
  // mods is the same (mod_name, mod_path) vector used for VFS building.
  void detectManualMoves(
      const std::string& overwrite_dir,
      const std::vector<std::pair<std::string, std::string>>& mods);

  // Initial scan: for each file in overwrite, check if the same relative
  // path exists in any mod.  If so, track it — the user already moved it.
  // Called on first run (no previous snapshot/tracking data exists).
  void initialScan(
      const std::string& overwrite_dir,
      const std::vector<std::pair<std::string, std::string>>& mods);

  // Get all tracked mappings (for debugging / inspection).
  std::unordered_map<std::string, std::string> allMappings() const;

private:
  // Prune without locking (caller must hold m_mutex).
  void pruneStaleUnlocked();

  // relative_path (lowercase) -> absolute mod folder path
  mutable std::mutex m_mutex;
  std::unordered_map<std::string, std::string> m_tracked;

  // Snapshot of overwrite directory contents from previous session
  std::vector<std::string> m_overwriteSnapshot;
};

#endif
