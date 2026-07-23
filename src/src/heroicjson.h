#ifndef HEROICJSON_H
#define HEROICJSON_H

#include <QByteArray>
#include <QString>
#include <QVector>

struct HeroicEpicInstall
{
  QString app_name;
  QString namespace_id;
  QString title;
  QString install_path;
  QString platform;
  bool is_installed = false;
  bool is_dlc       = false;
};

/// Parse either Heroic's modern legendary_library.json cache or Legendary's
/// installed.json into a common representation.
QVector<HeroicEpicInstall> parseHeroicEpicInstalls(const QByteArray& json);

/// Merge Legendary's authoritative installed manifest with Heroic's richer
/// library cache. Manifest installation paths and state win; cache metadata
/// fills namespace, title, and any missing fields.
QVector<HeroicEpicInstall> mergeHeroicEpicInstalls(
    const QVector<HeroicEpicInstall>& installedManifest,
    const QVector<HeroicEpicInstall>& libraryCache);

#endif  // HEROICJSON_H
