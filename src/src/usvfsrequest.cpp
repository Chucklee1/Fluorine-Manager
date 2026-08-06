#include "usvfsrequest.h"

#include "vfsbackend.h"

#include <QByteArray>
#include <QDir>
#include <QTemporaryFile>
#include <QUuid>

#include <algorithm>

namespace
{
constexpr char kMagic[] = {'F', 'U', 'S', 'V', 'F', 'S', '1', '\0'};
constexpr quint32 kFormatVersion = 2;
constexpr quint64 kMaxEntries = 2'000'000;
constexpr qsizetype kMaxStringBytes = 16 * 1024 * 1024;
constexpr qsizetype kMaxRequestBytes = 512 * 1024 * 1024;

enum class MappingInstallMode : quint8
{
  Normal = 0,
  Shallow = 1,
  AfterSnapshot = 2,
};

void appendU8(QByteArray& output, quint8 value)
{
  output.append(static_cast<char>(value));
}

void appendU32(QByteArray& output, quint32 value)
{
  output.append(static_cast<char>(value & 0xff));
  output.append(static_cast<char>((value >> 8) & 0xff));
  output.append(static_cast<char>((value >> 16) & 0xff));
  output.append(static_cast<char>((value >> 24) & 0xff));
}

bool appendString(QByteArray& output, const QString& value, QString& error)
{
  const QByteArray utf8 = value.toUtf8();
  if (utf8.size() > kMaxStringBytes) {
    error = QStringLiteral("USVFS request contains a string larger than 16 MiB");
    return false;
  }
  appendU32(output, static_cast<quint32>(utf8.size()));
  output.append(utf8);
  return true;
}

bool appendStringList(QByteArray& output, const QStringList& values, QString& error)
{
  appendU32(output, static_cast<quint32>(values.size()));
  for (const QString& value : values) {
    if (!appendString(output, value, error)) return false;
  }
  return true;
}

bool targetsDirectory(const Mapping& mapping, const QString& directory)
{
  if (directory.isEmpty()) return false;
  const QString cleanDirectory =
      QDir::cleanPath(QDir::fromNativeSeparators(directory));
  const QString destination =
      QDir::cleanPath(QDir::fromNativeSeparators(mapping.destination));
  return destination == cleanDirectory ||
         destination.startsWith(cleanDirectory + QStringLiteral("/"));
}
}

UsvfsRequestResult writeUsvfsRequest(const UsvfsRequestOptions& options)
{
  UsvfsRequestResult result;
  if (options.binary.absoluteFilePath().isEmpty()) {
    result.error = QStringLiteral("USVFS request has no target executable");
    return result;
  }
  if (options.mappings.size() > kMaxEntries ||
      options.resolvedMappings.size() > kMaxEntries ||
      options.arguments.size() > kMaxEntries ||
      options.forcedLibraries.size() > kMaxEntries ||
      options.executableBlacklist.size() > kMaxEntries ||
      options.skipFileSuffixes.size() > kMaxEntries ||
      options.skipDirectories.size() > kMaxEntries) {
    result.error = QStringLiteral("USVFS request contains too many entries");
    return result;
  }

  result.instanceName =
      QStringLiteral("fluorine-") +
      QUuid::createUuid().toString(QUuid::WithoutBraces).remove('-');

  QByteArray output;
  const qsizetype estimatedBytes =
      4096 + static_cast<qsizetype>(options.mappings.size() +
                                    options.resolvedMappings.size()) *
                 256;
  output.reserve(std::min(estimatedBytes, kMaxRequestBytes));
  output.append(kMagic, sizeof(kMagic));
  appendU32(output, kFormatVersion);

  if (!appendString(output, result.instanceName, result.error) ||
      !appendString(output, toWinePath(options.binary.absoluteFilePath()),
                    result.error) ||
      !appendString(output,
                    toWinePath(options.workingDirectory.absolutePath()),
                    result.error) ||
      !appendString(output, toWinePath(options.logPath), result.error) ||
      !appendStringList(output, options.arguments, result.error)) {
    return result;
  }

  appendU32(output, static_cast<quint32>(options.mappings.size()));
  for (const Mapping& mapping : options.mappings) {
    appendU8(output, mapping.isDirectory ? 1 : 0);
    appendU8(output, mapping.createTarget ? 1 : 0);
    MappingInstallMode mode = MappingInstallMode::Normal;
    if (options.useResolvedSnapshot &&
        targetsDirectory(mapping, options.dataDirectory)) {
      mode = mapping.isDirectory ? MappingInstallMode::Shallow
                                 : MappingInstallMode::AfterSnapshot;
    }
    appendU8(output, static_cast<quint8>(mode));
    if (!appendString(output, toWinePath(mapping.source), result.error) ||
        !appendString(output, toWinePath(mapping.destination), result.error)) {
      return result;
    }
  }

  appendU32(output, options.useResolvedSnapshot
                        ? static_cast<quint32>(options.resolvedMappings.size())
                        : 0);
  if (options.useResolvedSnapshot) {
    for (const Mapping& mapping : options.resolvedMappings) {
      appendU8(output, mapping.isDirectory ? 1 : 0);
      if (!appendString(output, toWinePath(mapping.source), result.error) ||
          !appendString(output, toWinePath(mapping.destination), result.error)) {
        return result;
      }
    }
  }

  quint32 enabledForcedLibraries = 0;
  for (const auto& setting : options.forcedLibraries) {
    if (setting.enabled()) ++enabledForcedLibraries;
  }
  appendU32(output, enabledForcedLibraries);
  for (const auto& setting : options.forcedLibraries) {
    if (!setting.enabled()) continue;
    if (!appendString(output, setting.process(), result.error) ||
        !appendString(output, toWinePath(setting.library()), result.error)) {
      return result;
    }
  }

  if (!appendStringList(output, options.executableBlacklist, result.error) ||
      !appendStringList(output, options.skipFileSuffixes, result.error) ||
      !appendStringList(output, options.skipDirectories, result.error)) {
    return result;
  }
  if (output.size() > kMaxRequestBytes) {
    result.error = QStringLiteral("USVFS request is larger than 512 MiB");
    return result;
  }

  QTemporaryFile request(
      QDir::tempPath() + QStringLiteral("/fluorine-usvfs-XXXXXX.bin"));
  request.setAutoRemove(false);
  if (!request.open()) {
    result.error = QStringLiteral("Unable to create temporary USVFS request: %1")
                       .arg(request.errorString());
    return result;
  }
  if (request.write(output) != output.size() || !request.flush()) {
    result.error = QStringLiteral("Unable to write temporary USVFS request: %1")
                       .arg(request.errorString());
    request.remove();
    return result;
  }
  result.path = request.fileName();
  request.close();
  return result;
}
