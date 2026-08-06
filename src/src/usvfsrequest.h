#ifndef USVFSREQUEST_H
#define USVFSREQUEST_H

#include <QDir>
#include <QFileInfo>
#include <QList>
#include <QString>
#include <QStringList>
#include <uibase/executableinfo.h>
#include <uibase/filemapping.h>

struct UsvfsRequestOptions
{
  QFileInfo binary;
  QDir workingDirectory;
  QStringList arguments;
  MappingType mappings;
  // Optional catalog-resolved Data snapshot. When enabled, ordinary directory
  // mappings into dataDirectory are installed without recursive scanning and
  // ordinary file mappings there are applied after the snapshot.
  bool useResolvedSnapshot = false;
  QString dataDirectory;
  MappingType resolvedMappings;
  QList<MOBase::ExecutableForcedLoadSetting> forcedLibraries;
  QStringList executableBlacklist;
  QStringList skipFileSuffixes;
  QStringList skipDirectories;
  QString logPath;
};

struct UsvfsRequestResult
{
  QString path;
  QString instanceName;
  QString error;

  explicit operator bool() const { return !path.isEmpty() && error.isEmpty(); }
};

// Writes the versioned, length-prefixed request consumed by the bundled
// fluorine-usvfs-launcher.exe. The temporary file is intentionally not
// auto-removed: the Wine-side helper deletes it immediately after parsing.
UsvfsRequestResult writeUsvfsRequest(const UsvfsRequestOptions& options);

#endif
