#include "plugincompatibility.h"

#include <QByteArray>
#include <Qt>

namespace PluginCompatibility
{

namespace
{

const QString openMWPlayerRuleId = QStringLiteral("openmwplayer-native-openmw");

}  // namespace

std::optional<Block> blockedRule(const QString& gameName,
                                 const QStringList& pluginAncestry,
                                 const QSet<QString>& allowedRuleIds)
{
  if (allowedRuleIds.contains(openMWPlayerRuleId)) {
    return std::nullopt;
  }
  if (gameName != QStringLiteral("Morrowind (OpenMW)")) {
    return std::nullopt;
  }
  if (!pluginAncestry.contains(QStringLiteral("OpenMWPlayer"))) {
    return std::nullopt;
  }
  return Block{
      openMWPlayerRuleId,
      QStringLiteral("OpenMWPlayer conflicts with Fluorine's native OpenMW "
                     "configuration and launch management."),
  };
}

QSet<QString> environmentOverrides()
{
  QSet<QString> result;
  const auto value = qgetenv("FLUORINE_ALLOW_INCOMPATIBLE_PLUGINS");
  for (const auto& part : value.split(',')) {
    const auto id = QString::fromUtf8(part).trimmed();
    if (!id.isEmpty()) {
      result.insert(id);
    }
  }
  return result;
}

}  // namespace PluginCompatibility
