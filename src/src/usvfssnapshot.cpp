#include "usvfssnapshot.h"

#include <QDir>
#include <QFileInfo>

#include <algorithm>
#include <filesystem>
#include <map>
#include <set>
#include <system_error>

namespace
{
namespace fs = std::filesystem;

struct VisibleFile
{
  fs::path relative;
  fs::path source;
};

bool skippedPath(const fs::path& relative, const QStringList& suffixes,
                 const QStringList& directories)
{
  for (const fs::path& component : relative.parent_path()) {
    const QString name = QString::fromStdString(component.string());
    for (const QString& skipped : directories) {
      if (name.compare(skipped, Qt::CaseInsensitive) == 0) return true;
    }
  }

  const QString fileName = QString::fromStdString(relative.filename().string());
  for (const QString& suffix : suffixes) {
    if (fileName.endsWith(suffix, Qt::CaseInsensitive)) return true;
  }
  return false;
}

void collectVisibleFiles(const VfsNode& node, const fs::path& relative,
                         const QStringList& suffixes,
                         const QStringList& directories,
                         std::vector<VisibleFile>& files)
{
  if (!node.is_directory) {
    if (!node.file_info.is_backing && !node.file_info.real_path.empty() &&
        !skippedPath(relative, suffixes, directories)) {
      files.push_back({relative, fs::path(node.file_info.real_path)});
    }
    return;
  }

  auto children = node.listChildren();
  std::sort(children.begin(), children.end(), [](const auto& left, const auto& right) {
    return normalizeForLookup(left.first) < normalizeForLookup(right.first);
  });
  for (const auto& [displayName, child] : children) {
    collectVisibleFiles(*child, relative / fs::path(displayName), suffixes,
                        directories, files);
  }
}

std::size_t pathDepth(const fs::path& path)
{
  return static_cast<std::size_t>(std::distance(path.begin(), path.end()));
}

std::vector<std::string> pathComponents(const fs::path& path)
{
  std::vector<std::string> components;
  for (const fs::path& component : path) {
    const std::string value = component.string();
    if (!value.empty() && value != ".") components.push_back(value);
  }
  return components;
}
}

std::vector<std::pair<std::string, std::string>> usvfsCatalogModsFromMappings(
    const MappingType& mappings, const QString& dataDirectory,
    const QString& overwriteDirectory)
{
  std::vector<std::pair<std::string, std::string>> mods;
  std::set<std::string> seen;
  const QString cleanData =
      QDir::cleanPath(QDir::fromNativeSeparators(dataDirectory));
  const QString dataPrefix = cleanData + QStringLiteral("/");
  const QString cleanOverwrite =
      QDir::cleanPath(QDir::fromNativeSeparators(overwriteDirectory));
  const QString overwritePrefix = cleanOverwrite + QStringLiteral("/");

  for (const Mapping& mapping : mappings) {
    if (!mapping.isDirectory) continue;
    const QString source =
        QDir::cleanPath(QDir::fromNativeSeparators(mapping.source));
    const QString destination =
        QDir::cleanPath(QDir::fromNativeSeparators(mapping.destination));
    if (destination != cleanData && !destination.startsWith(dataPrefix)) continue;
    if (source == cleanOverwrite || source.startsWith(overwritePrefix)) continue;

    const std::string sourcePath = source.toStdString();
    if (!seen.insert(sourcePath).second) continue;
    mods.emplace_back(QFileInfo(source).fileName().toStdString(), sourcePath);
  }
  return mods;
}

UsvfsResolvedSnapshot buildUsvfsResolvedSnapshot(
    const VfsTree& tree, const QString& dataDirectory,
    const QStringList& skipFileSuffixes, const QStringList& skipDirectories)
{
  std::vector<VisibleFile> files;
  collectVisibleFiles(tree.root, {}, skipFileSuffixes, skipDirectories, files);
  std::sort(files.begin(), files.end(), [](const VisibleFile& left,
                                           const VisibleFile& right) {
    return normalizeForLookup(left.relative.string()) <
           normalizeForLookup(right.relative.string());
  });

  // Every virtual directory needs one real directory target so Windows can
  // open it before USVFS merges its virtual children. A representative winner
  // beneath the directory supplies that target. Deterministic first-winner
  // selection keeps serialized requests reproducible.
  std::map<std::string, Mapping> directories;
  const fs::path dataRoot(dataDirectory.toStdString());
  for (const VisibleFile& file : files) {
    fs::path relativeParent = file.relative.parent_path();
    fs::path sourceParent = file.source.parent_path();
    while (!relativeParent.empty() && relativeParent != fs::path(".")) {
      const std::string key = normalizeForLookup(relativeParent.string());
      directories.try_emplace(
          key, Mapping{QString::fromStdString(sourceParent.string()),
                       QString::fromStdString((dataRoot / relativeParent).string()),
                       true, false});
      relativeParent = relativeParent.parent_path();
      sourceParent = sourceParent.parent_path();
    }
  }

  std::vector<std::pair<fs::path, Mapping>> orderedDirectories;
  orderedDirectories.reserve(directories.size());
  for (auto& [key, mapping] : directories) {
    (void)key;
    const fs::path relative =
        fs::path(mapping.destination.toStdString()).lexically_relative(dataRoot);
    orderedDirectories.emplace_back(relative, std::move(mapping));
  }
  std::sort(orderedDirectories.begin(), orderedDirectories.end(),
            [](const auto& left, const auto& right) {
              const std::size_t leftDepth = pathDepth(left.first);
              const std::size_t rightDepth = pathDepth(right.first);
              if (leftDepth != rightDepth) return leftDepth < rightDepth;
              return normalizeForLookup(left.first.string()) <
                     normalizeForLookup(right.first.string());
            });

  UsvfsResolvedSnapshot result;
  result.directoryCount = orderedDirectories.size();
  result.fileCount = files.size();
  result.mappings.reserve(result.directoryCount + result.fileCount);
  for (auto& [relative, mapping] : orderedDirectories) {
    (void)relative;
    result.mappings.push_back(std::move(mapping));
  }
  for (const VisibleFile& file : files) {
    result.mappings.push_back(
        {QString::fromStdString(file.source.string()),
         QString::fromStdString((dataRoot / file.relative).string()), false, false});
  }
  return result;
}

UsvfsResolvedSnapshot buildUsvfsResolvedSnapshotFromMappings(
    const MappingType& mappings, const QString& dataDirectory,
    const QStringList& skipFileSuffixes, const QStringList& skipDirectories)
{
  const QString cleanData =
      QDir::cleanPath(QDir::fromNativeSeparators(dataDirectory));
  const QString dataPrefix = cleanData + QStringLiteral("/");
  VfsTree tree;
  tree.root.is_directory = true;
  tree.dir_count = 1;

  for (const Mapping& mapping : mappings) {
    if (!mapping.isDirectory) continue;

    const QString source =
        QDir::cleanPath(QDir::fromNativeSeparators(mapping.source));
    const QString destination =
        QDir::cleanPath(QDir::fromNativeSeparators(mapping.destination));
    if (destination != cleanData && !destination.startsWith(dataPrefix)) {
      continue;
    }

    const fs::path sourceRoot(source.toStdString());
    std::error_code error;
    if (!fs::is_directory(sourceRoot, error)) continue;

    fs::path destinationPrefix;
    if (destination != cleanData) {
      destinationPrefix = fs::path(
          destination.mid(dataPrefix.size()).toStdString());
    }
    const std::vector<std::string> prefix =
        pathComponents(destinationPrefix);

    for (fs::recursive_directory_iterator iterator(
             sourceRoot, fs::directory_options::skip_permission_denied, error),
         end;
         !error && iterator != end; iterator.increment(error)) {
      const fs::directory_entry& entry = *iterator;
      const fs::path relative = entry.path().lexically_relative(sourceRoot);
      if (relative.empty() || relative == fs::path("meta.ini")) continue;

      // The catalog uses lstat and deliberately excludes symlinks. Match that
      // behavior while letting directory_entry reuse the d_type supplied by
      // readdir instead of issuing a stat syscall for every ordinary file.
      if (entry.is_symlink(error)) {
        error.clear();
        if (entry.is_directory(error)) iterator.disable_recursion_pending();
        error.clear();
        continue;
      }
      if (entry.is_directory(error)) {
        error.clear();
        continue;
      }
      if (error) {
        error.clear();
        continue;
      }
      if (!entry.is_regular_file(error)) {
        error.clear();
        continue;
      }

      std::vector<std::string> components = prefix;
      const auto relativeComponents = pathComponents(relative);
      components.insert(components.end(), relativeComponents.begin(),
                        relativeComponents.end());
      tree.root.insertFile(components, entry.path().string(), 0, {},
                           sourceRoot.filename().string(), false, 0);
      ++tree.file_count;
    }
  }

  return buildUsvfsResolvedSnapshot(
      tree, dataDirectory, skipFileSuffixes, skipDirectories);
}
