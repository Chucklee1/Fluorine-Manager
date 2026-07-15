#include "inodetable.h"

#include "vfstree.h"

#include <vector>

namespace
{
std::string canonicalizePath(const std::string& path)
{
  std::string canonical = path;
  for (char& c : canonical) {
    if (c == '\\') {
      c = '/';
    }
  }

  while (!canonical.empty() && canonical.front() == '/') {
    canonical.erase(canonical.begin());
  }
  while (!canonical.empty() && canonical.back() == '/') {
    canonical.pop_back();
  }

  return canonical;
}
}  // namespace

InodeTable::InodeTable()
{
  m_pathToInode.emplace("", 1);
  m_inodeToPath.emplace(1, "");
}

void InodeTable::reserve(std::size_t count)
{
  m_pathToInode.reserve(count);
  m_inodeToPath.reserve(count);
}

uint64_t InodeTable::get(const std::string& path) const
{
  const std::string key = normalizeForLookup(path);
  auto it               = m_pathToInode.find(key);
  if (it == m_pathToInode.end()) {
    return 0;
  }
  return it->second;
}

uint64_t InodeTable::getOrCreate(const std::string& path)
{
  const std::string key = normalizeForLookup(path);
  auto existing         = m_pathToInode.find(key);
  if (existing != m_pathToInode.end()) {
    return existing->second;
  }

  const uint64_t ino = m_nextInode++;
  m_pathToInode.emplace(key, ino);
  m_inodeToPath.emplace(ino, canonicalizePath(path));
  return ino;
}

std::string InodeTable::getPath(uint64_t ino) const
{
  auto it = m_inodeToPath.find(ino);
  if (it == m_inodeToPath.end()) {
    return "";
  }
  return it->second;
}

void InodeTable::rename(const std::string& old_path, const std::string& new_path)
{
  const std::string oldCanonical = canonicalizePath(old_path);
  const std::string newCanonical = canonicalizePath(new_path);
  const std::string oldKey       = normalizeForLookup(oldCanonical);
  const std::string newKey       = normalizeForLookup(newCanonical);

  auto it = m_pathToInode.find(oldKey);
  if (it != m_pathToInode.end()) {
    const uint64_t ino = it->second;
    m_pathToInode.erase(it);
    // POSIX rename replaces an existing destination. Future lookups must use
    // the source inode, not retain the inode of the file that was replaced.
    auto replaced = m_pathToInode.find(newKey);
    if (replaced != m_pathToInode.end() && replaced->second != ino) {
      m_inodeToPath.erase(replaced->second);
    }
    m_pathToInode.insert_or_assign(newKey, ino);
    m_inodeToPath[ino] = newCanonical;
  }

  std::vector<std::pair<std::string, uint64_t>> descendants;
  descendants.reserve(m_pathToInode.size());

  const std::string oldPrefix = oldKey.empty() ? oldKey : oldKey + "/";
  for (const auto& [key, ino] : m_pathToInode) {
    if (oldPrefix.empty() || key.rfind(oldPrefix, 0) == 0) {
      descendants.emplace_back(key, ino);
    }
  }

  for (const auto& [descKey, ino] : descendants) {
    if (descKey == oldKey) {
      continue;
    }

    const std::string suffix = descKey.substr(oldPrefix.size());
    const std::string nextKey = newKey.empty() ? suffix : newKey + "/" + suffix;
    m_pathToInode.erase(descKey);
    auto replaced = m_pathToInode.find(nextKey);
    if (replaced != m_pathToInode.end() && replaced->second != ino) {
      m_inodeToPath.erase(replaced->second);
    }
    m_pathToInode.insert_or_assign(nextKey, ino);

    auto inodeIt = m_inodeToPath.find(ino);
    if (inodeIt != m_inodeToPath.end()) {
      const std::string suffixCanonical = inodeIt->second.substr(oldCanonical.size());
      inodeIt->second = newCanonical + suffixCanonical;
    }
  }
}
