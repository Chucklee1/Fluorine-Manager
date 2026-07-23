#include "heroicjson.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QHash>
#include <QSet>

#include <utility>

namespace
{
HeroicEpicInstall parseInstall(const QJsonObject& game, const QString& fallbackAppName,
                               bool installedByPresence)
{
  const QJsonObject install = game.value(QStringLiteral("install")).toObject();

  HeroicEpicInstall result;
  result.app_name    = game.value(QStringLiteral("app_name")).toString(fallbackAppName);
  result.namespace_id = game.value(QStringLiteral("namespace")).toString();
  result.title       = game.value(QStringLiteral("title")).toString(result.app_name);
  result.install_path =
      install.value(QStringLiteral("install_path"))
          .toString(game.value(QStringLiteral("install_path")).toString());
  result.platform =
      install.value(QStringLiteral("platform"))
          .toString(game.value(QStringLiteral("platform")).toString());
  if (game.contains(QStringLiteral("is_installed"))) {
    result.is_installed = game.value(QStringLiteral("is_installed")).toBool();
  } else if (install.contains(QStringLiteral("is_installed"))) {
    result.is_installed = install.value(QStringLiteral("is_installed")).toBool();
  } else {
    // Modern Heroic caches may omit is_installed. A populated nested install
    // record is the remaining installation signal in that schema.
    result.is_installed = installedByPresence || !result.install_path.isEmpty();
  }
  result.is_dlc = install.contains(QStringLiteral("is_dlc"))
                      ? install.value(QStringLiteral("is_dlc")).toBool()
                      : game.value(QStringLiteral("is_dlc")).toBool();
  return result;
}
}  // namespace

QVector<HeroicEpicInstall> parseHeroicEpicInstalls(const QByteArray& json)
{
  const QJsonDocument document = QJsonDocument::fromJson(json);
  if (!document.isObject()) {
    return {};
  }

  const QJsonObject root = document.object();
  QVector<HeroicEpicInstall> installs;

  // Current Heroic cache schema:
  // {"library": [{"app_name": "...", "install": {...}}, ...]}
  if (root.value(QStringLiteral("library")).isArray()) {
    const QJsonArray library = root.value(QStringLiteral("library")).toArray();
    installs.reserve(library.size());
    for (const QJsonValue& value : library) {
      if (!value.isObject()) {
        continue;
      }
      HeroicEpicInstall install = parseInstall(value.toObject(), {}, false);
      if (!install.app_name.isEmpty()) {
        installs.append(std::move(install));
      }
    }
    return installs;
  }

  // Legendary installed.json schema:
  // {"AppName": {"app_name": "AppName", "install_path": "..."}, ...}
  // Presence in this file means installed; it normally has no is_installed key.
  installs.reserve(root.size());
  for (auto it = root.constBegin(); it != root.constEnd(); ++it) {
    if (!it.value().isObject()) {
      continue;
    }
    HeroicEpicInstall install = parseInstall(it.value().toObject(), it.key(), true);
    if (!install.app_name.isEmpty()) {
      installs.append(std::move(install));
    }
  }
  return installs;
}

QVector<HeroicEpicInstall> mergeHeroicEpicInstalls(
    const QVector<HeroicEpicInstall>& installedManifest,
    const QVector<HeroicEpicInstall>& libraryCache)
{
  QVector<HeroicEpicInstall> result;
  QHash<QString, qsizetype> indexes;
  QSet<QString> manifestAppNames;

  auto insertOrReplaceManifest = [&](const HeroicEpicInstall& install) {
    const auto existing = indexes.constFind(install.app_name);
    if (existing == indexes.constEnd()) {
      indexes.insert(install.app_name, result.size());
      result.append(install);
    } else {
      result[*existing] = install;
    }
    manifestAppNames.insert(install.app_name);
  };

  for (const HeroicEpicInstall& install : installedManifest) {
    insertOrReplaceManifest(install);
  }

  for (const HeroicEpicInstall& cached : libraryCache) {
    const auto existing = indexes.constFind(cached.app_name);
    if (existing == indexes.constEnd()) {
      indexes.insert(cached.app_name, result.size());
      result.append(cached);
      continue;
    }

    HeroicEpicInstall& merged = result[*existing];
    if (!cached.namespace_id.isEmpty()) {
      merged.namespace_id = cached.namespace_id;
    }
    if (!cached.title.isEmpty() && cached.title != cached.app_name) {
      merged.title = cached.title;
    }
    if (merged.install_path.isEmpty()) {
      merged.install_path = cached.install_path;
    }
    if (merged.platform.isEmpty()) {
      merged.platform = cached.platform;
    }
    merged.is_dlc = merged.is_dlc || cached.is_dlc;

    // Cache-only duplicate records may contribute installation state. When
    // installed.json supplied the record, its state remains authoritative.
    if (!manifestAppNames.contains(cached.app_name)) {
      merged.is_installed = merged.is_installed || cached.is_installed;
    }
  }

  return result;
}
