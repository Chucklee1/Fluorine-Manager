#include "vfsbackend.h"

#include <QDir>
#include <QFileInfo>
#include <QRegularExpression>

VfsBackend parseVfsBackend(QStringView value)
{
  return value.compare(QStringLiteral("usvfs"), Qt::CaseInsensitive) == 0
             ? VfsBackend::Usvfs
             : VfsBackend::Fuse;
}

QString vfsBackendSettingValue(VfsBackend backend)
{
  return backend == VfsBackend::Usvfs ? QStringLiteral("usvfs")
                                      : QStringLiteral("fuse");
}

bool parseUsvfsExperimentFlag(QStringView value, bool fallback)
{
  const QString normalized = value.trimmed().toString();
  if (normalized.compare(QStringLiteral("1"), Qt::CaseInsensitive) == 0 ||
      normalized.compare(QStringLiteral("true"), Qt::CaseInsensitive) == 0 ||
      normalized.compare(QStringLiteral("on"), Qt::CaseInsensitive) == 0) {
    return true;
  }
  if (normalized.compare(QStringLiteral("0"), Qt::CaseInsensitive) == 0 ||
      normalized.compare(QStringLiteral("false"), Qt::CaseInsensitive) == 0 ||
      normalized.compare(QStringLiteral("off"), Qt::CaseInsensitive) == 0) {
    return false;
  }
  return fallback;
}

bool useUsvfsForLaunch(VfsBackend backend, bool useProton,
                       bool gameUsesOrganizerVfs)
{
  return gameUsesOrganizerVfs && useProton && backend == VfsBackend::Usvfs;
}

QStringList processTrackingExecutables(const QStringList& targetExecutables,
                                       bool usingUsvfsHelper)
{
  if (usingUsvfsHelper) {
    return {QString::fromLatin1(kUsvfsLauncherExecutable)};
  }
  return targetExecutables;
}

QString toWinePath(const QString& path)
{
  if (path.isEmpty()) {
    return {};
  }

  QString normalized = QDir::fromNativeSeparators(path);
  static const QRegularExpression drivePath(QStringLiteral("^[A-Za-z]:[/\\\\]"));
  if (drivePath.match(normalized).hasMatch() || normalized.startsWith("//")) {
    return normalized.replace('/', '\\');
  }

  const QFileInfo info(normalized);
  if (info.isAbsolute()) {
    normalized = QDir::cleanPath(info.absoluteFilePath());
    return QStringLiteral("Z:") + normalized.replace('/', '\\');
  }

  return normalized.replace('/', '\\');
}
