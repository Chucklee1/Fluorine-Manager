#include "trackedwrites.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <sstream>

namespace fs = std::filesystem;

namespace
{

std::string toLower(const std::string& s)
{
  std::string out = s;
  std::transform(out.begin(), out.end(), out.begin(),
                 [](unsigned char c) { return std::tolower(c); });
  return out;
}

// Minimal JSON helpers — avoids adding a dependency for a simple
// { "key": "value" } map + string array.

std::string jsonEscape(const std::string& s)
{
  std::string out;
  out.reserve(s.size() + 4);
  for (char c : s) {
    if (c == '"')
      out += "\\\"";
    else if (c == '\\')
      out += "\\\\";
    else
      out += c;
  }
  return out;
}

// Parse a JSON string value starting after the opening '"'.
std::string parseJsonString(const std::string& data, size_t& pos)
{
  std::string out;
  while (pos < data.size()) {
    char c = data[pos++];
    if (c == '"')
      return out;
    if (c == '\\' && pos < data.size()) {
      char next = data[pos++];
      if (next == '"')
        out += '"';
      else if (next == '\\')
        out += '\\';
      else if (next == 'n')
        out += '\n';
      else {
        out += '\\';
        out += next;
      }
    } else {
      out += c;
    }
  }
  return out;
}

void skipWhitespace(const std::string& data, size_t& pos)
{
  while (pos < data.size() && std::isspace(static_cast<unsigned char>(data[pos])))
    ++pos;
}

}  // namespace

void TrackedWrites::load(const std::string& path)
{
  std::ifstream f(path);
  if (!f.is_open())
    return;

  std::ostringstream ss;
  ss << f.rdbuf();
  const std::string data = ss.str();
  f.close();

  // Base directory for resolving relative mod paths.
  const std::string baseDir = fs::path(path).parent_path().string();

  std::lock_guard lock(m_mutex);
  m_tracked.clear();
  m_overwriteSnapshot.clear();

  size_t pos = 0;
  skipWhitespace(data, pos);
  if (pos >= data.size() || data[pos] != '{')
    return;
  ++pos;

  // Parse top-level keys
  while (pos < data.size()) {
    skipWhitespace(data, pos);
    if (pos >= data.size() || data[pos] == '}')
      break;
    if (data[pos] != '"')
      break;
    ++pos;
    std::string key = parseJsonString(data, pos);

    skipWhitespace(data, pos);
    if (pos >= data.size() || data[pos] != ':')
      break;
    ++pos;
    skipWhitespace(data, pos);

    if (key == "tracked") {
      // Parse object { "relpath": "modpath", ... }
      if (pos < data.size() && data[pos] == '{') {
        ++pos;
        while (pos < data.size()) {
          skipWhitespace(data, pos);
          if (pos >= data.size() || data[pos] == '}') {
            ++pos;
            break;
          }
          if (data[pos] != '"')
            break;
          ++pos;
          std::string relPath = parseJsonString(data, pos);

          skipWhitespace(data, pos);
          if (pos >= data.size() || data[pos] != ':')
            break;
          ++pos;
          skipWhitespace(data, pos);

          if (pos >= data.size() || data[pos] != '"')
            break;
          ++pos;
          std::string modPath = parseJsonString(data, pos);

          // Resolve mod path: if it's relative, resolve against base dir.
          // If it's absolute (legacy format), use as-is for backwards compat.
          std::error_code ec;
          std::string resolved;
          if (!modPath.empty() && modPath[0] != '/') {
            resolved = fs::weakly_canonical(fs::path(baseDir) / modPath, ec).string();
          } else {
            resolved = modPath;
          }

          m_tracked[toLower(relPath)] = resolved;

          skipWhitespace(data, pos);
          if (pos < data.size() && data[pos] == ',')
            ++pos;
        }
      }
    } else if (key == "overwrite_snapshot") {
      // Parse array [ "relpath", ... ]
      if (pos < data.size() && data[pos] == '[') {
        ++pos;
        while (pos < data.size()) {
          skipWhitespace(data, pos);
          if (pos >= data.size() || data[pos] == ']') {
            ++pos;
            break;
          }
          if (data[pos] != '"')
            break;
          ++pos;
          m_overwriteSnapshot.push_back(parseJsonString(data, pos));

          skipWhitespace(data, pos);
          if (pos < data.size() && data[pos] == ',')
            ++pos;
        }
      }
    }

    skipWhitespace(data, pos);
    if (pos < data.size() && data[pos] == ',')
      ++pos;
  }

  std::fprintf(stderr, "[VFS] loaded %zu tracked write mappings\n", m_tracked.size());

  // Prune entries whose mod folder no longer exists (e.g. user deleted the mod).
  pruneStaleUnlocked();
}

void TrackedWrites::save(const std::string& path) const
{
  std::lock_guard lock(m_mutex);

  // Ensure parent directory exists
  std::error_code ec;
  fs::create_directories(fs::path(path).parent_path(), ec);

  std::ofstream f(path);
  if (!f.is_open()) {
    std::fprintf(stderr, "[VFS] failed to save tracked writes to %s\n", path.c_str());
    return;
  }

  // Base directory for making mod paths relative (portable).
  const fs::path baseDir = fs::path(path).parent_path();

  f << "{\n  \"tracked\": {";
  bool first = true;
  for (const auto& [relPath, modPath] : m_tracked) {
    if (!first)
      f << ",";
    // Convert absolute mod path to relative for portability.
    std::string storedPath = modPath;
    if (!modPath.empty() && modPath[0] == '/') {
      auto rel = fs::relative(fs::path(modPath), baseDir, ec);
      if (!ec && !rel.empty())
        storedPath = rel.string();
    }
    f << "\n    \"" << jsonEscape(relPath) << "\": \"" << jsonEscape(storedPath) << "\"";
    first = false;
  }
  f << "\n  },\n  \"overwrite_snapshot\": [";

  first = true;
  for (const auto& relPath : m_overwriteSnapshot) {
    if (!first)
      f << ",";
    f << "\n    \"" << jsonEscape(relPath) << "\"";
    first = false;
  }
  f << "\n  ]\n}\n";

  std::fprintf(stderr, "[VFS] saved %zu tracked write mappings\n", m_tracked.size());
}

void TrackedWrites::pruneStale()
{
  std::lock_guard lock(m_mutex);
  pruneStaleUnlocked();
}

void TrackedWrites::pruneStaleUnlocked()
{
  std::error_code ec;
  int pruned = 0;
  for (auto it = m_tracked.begin(); it != m_tracked.end(); ) {
    if (!fs::is_directory(it->second, ec)) {
      std::fprintf(stderr, "[VFS] pruning stale tracking: %s -> %s (mod folder gone)\n",
                   it->first.c_str(), it->second.c_str());
      it = m_tracked.erase(it);
      ++pruned;
    } else {
      ++it;
    }
  }
  if (pruned > 0)
    std::fprintf(stderr, "[VFS] pruned %d stale tracked write entries\n", pruned);
}

void TrackedWrites::track(const std::string& relative_path,
                          const std::string& mod_folder_path)
{
  std::lock_guard lock(m_mutex);
  m_tracked[toLower(relative_path)] = mod_folder_path;
}

void TrackedWrites::untrack(const std::string& relative_path)
{
  std::lock_guard lock(m_mutex);
  m_tracked.erase(toLower(relative_path));
}

std::string TrackedWrites::modFolderFor(const std::string& relative_path) const
{
  std::lock_guard lock(m_mutex);
  auto it = m_tracked.find(toLower(relative_path));
  if (it != m_tracked.end())
    return it->second;
  return {};
}

void TrackedWrites::snapshotOverwrite(const std::string& overwrite_dir)
{
  std::lock_guard lock(m_mutex);
  m_overwriteSnapshot.clear();

  std::error_code ec;
  if (!fs::exists(overwrite_dir, ec))
    return;

  for (auto it = fs::recursive_directory_iterator(
           overwrite_dir, fs::directory_options::skip_permission_denied, ec);
       it != fs::recursive_directory_iterator(); ++it) {
    if (it->is_regular_file(ec)) {
      auto rel = fs::relative(it->path(), overwrite_dir, ec);
      if (!ec)
        m_overwriteSnapshot.push_back(rel.string());
    }
  }
}

void TrackedWrites::detectManualMoves(
    const std::string& overwrite_dir,
    const std::vector<std::pair<std::string, std::string>>& mods)
{
  std::lock_guard lock(m_mutex);

  if (m_overwriteSnapshot.empty())
    return;

  // Find files that were in overwrite last session but are gone now
  std::vector<std::string> missing;
  for (const auto& relPath : m_overwriteSnapshot) {
    std::error_code ec;
    if (!fs::exists(fs::path(overwrite_dir) / relPath, ec)) {
      missing.push_back(relPath);
    }
  }

  if (missing.empty())
    return;

  // For each missing file, check if it now exists in any mod folder.
  // Use the LAST match (highest priority — mods are ordered low→high).
  int detected = 0;
  for (const auto& relPath : missing) {
    const std::string key = toLower(relPath);
    // Skip if already tracked
    if (m_tracked.contains(key))
      continue;

    std::string matchedMod;
    std::string matchedPath;
    for (const auto& [modName, modPath] : mods) {
      std::error_code ec;
      if (fs::exists(fs::path(modPath) / relPath, ec)) {
        matchedMod  = modName;
        matchedPath = modPath;
        // Don't break — keep going to find the highest-priority match.
      }
    }

    if (!matchedPath.empty()) {
      m_tracked[key] = matchedPath;
      ++detected;
      std::fprintf(stderr, "[VFS] detected manual move: %s -> %s\n",
                   relPath.c_str(), matchedMod.c_str());
    }
  }

  if (detected > 0)
    std::fprintf(stderr, "[VFS] detected %d manually moved files from overwrite\n",
                 detected);

  m_overwriteSnapshot.clear();
}

void TrackedWrites::initialScan(
    const std::string& overwrite_dir,
    const std::vector<std::pair<std::string, std::string>>& mods)
{
  // On first run (or any mount), scan overwrite for files that also exist
  // in a mod.  This means the user already moved files to a mod but a stale
  // copy remains in overwrite.  Track the mod version so future writes go
  // there instead of creating another duplicate.
  //
  // Also scan all mods for duplicate files — if the same relative path
  // exists in multiple mods, the highest-priority one (last in the mods
  // vector) wins in the VFS.  If a lower-priority mod also has it, that
  // lower mod likely holds user-moved overwrite output.  But this is too
  // heuristic-heavy, so we only do the overwrite-vs-mod check.

  std::lock_guard lock(m_mutex);

  std::error_code ec;
  if (!fs::exists(overwrite_dir, ec))
    return;

  int detected = 0;
  for (auto it = fs::recursive_directory_iterator(
           overwrite_dir, fs::directory_options::skip_permission_denied, ec);
       it != fs::recursive_directory_iterator(); ++it) {
    if (!it->is_regular_file(ec))
      continue;

    auto rel = fs::relative(it->path(), overwrite_dir, ec);
    if (ec)
      continue;

    const std::string relStr = rel.string();
    const std::string key    = toLower(relStr);

    if (m_tracked.contains(key))
      continue;

    // Check if any mod also has this file — use the LAST match (highest
    // priority in the load order, since mods are ordered low→high).
    std::string matchedMod;
    std::string matchedPath;
    for (const auto& [modName, modPath] : mods) {
      if (fs::exists(fs::path(modPath) / relStr, ec)) {
        matchedMod  = modName;
        matchedPath = modPath;
      }
    }

    if (!matchedPath.empty()) {
      m_tracked[key] = matchedPath;
      ++detected;
      std::fprintf(stderr, "[VFS] initial scan: %s exists in overwrite AND %s — tracking mod\n",
                   relStr.c_str(), matchedMod.c_str());
    }
  }

  if (detected > 0)
    std::fprintf(stderr, "[VFS] initial scan tracked %d files\n", detected);
  else
    std::fprintf(stderr, "[VFS] initial scan: overwrite has %s\n",
                 fs::is_empty(overwrite_dir, ec) ? "no files" : "files but no mod matches");
}

std::unordered_map<std::string, std::string> TrackedWrites::allMappings() const
{
  std::lock_guard lock(m_mutex);
  return m_tracked;
}
