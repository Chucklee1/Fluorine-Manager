#ifndef USVFSSNAPSHOT_H
#define USVFSSNAPSHOT_H

#include "vfs/vfstree.h"

#include <QString>
#include <QStringList>
#include <cstddef>
#include <string>
#include <utility>
#include <vector>
#include <uibase/filemapping.h>

struct UsvfsResolvedSnapshot
{
  MappingType mappings;
  std::size_t directoryCount = 0;
  std::size_t fileCount = 0;
};

// Extract the ordered provider roots that the persistent catalog uses from
// MO2's richer mapping list. Only directory mappings into Data participate;
// Overwrite is passed separately to VfsCatalog.
std::vector<std::pair<std::string, std::string>> usvfsCatalogModsFromMappings(
    const MappingType& mappings, const QString& dataDirectory,
    const QString& overwriteDirectory);

// Convert the catalog's conflict-resolved tree into a compact USVFS mapping
// snapshot. Physical base-game winners are deliberately omitted: they remain
// visible at their real destination without redirection.
UsvfsResolvedSnapshot buildUsvfsResolvedSnapshot(
    const VfsTree& tree, const QString& dataDirectory,
    const QStringList& skipFileSuffixes = {},
    const QStringList& skipDirectories = {});

#endif
