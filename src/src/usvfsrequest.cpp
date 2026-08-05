#include "usvfsrequest.h"

#include "vfsbackend.h"

#include <QByteArray>
#include <QDir>
#include <QTemporaryFile>
#include <QUuid>

namespace
{
constexpr char kMagic[] = {'F', 'U', 'S', 'V', 'F', 'S', '1', '\0'};
constexpr quint32 kFormatVersion = 1;

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
  if (static_cast<quint64>(utf8.size()) > 0xffffffffULL) {
    error = QStringLiteral("USVFS request contains a string larger than 4 GiB");
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
}

UsvfsRequestResult writeUsvfsRequest(const UsvfsRequestOptions& options)
{
  UsvfsRequestResult result;
  if (options.binary.absoluteFilePath().isEmpty()) {
    result.error = QStringLiteral("USVFS request has no target executable");
    return result;
  }

  result.instanceName =
      QStringLiteral("fluorine-") +
      QUuid::createUuid().toString(QUuid::WithoutBraces).remove('-');

  QByteArray output;
  output.reserve(4096 + static_cast<qsizetype>(options.mappings.size()) * 256);
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
    if (!appendString(output, toWinePath(mapping.source), result.error) ||
        !appendString(output, toWinePath(mapping.destination), result.error)) {
      return result;
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
