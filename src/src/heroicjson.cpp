#include "heroicjson.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>

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
  result.is_installed = game.contains(QStringLiteral("is_installed"))
                            ? game.value(QStringLiteral("is_installed")).toBool()
                            : installedByPresence;
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
