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
};

/// Parse either Heroic's modern legendary_library.json cache or Legendary's
/// installed.json into a common representation.
QVector<HeroicEpicInstall> parseHeroicEpicInstalls(const QByteArray& json);

#endif  // HEROICJSON_H
