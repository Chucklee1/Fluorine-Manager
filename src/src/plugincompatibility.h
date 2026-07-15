#ifndef PLUGINCOMPATIBILITY_H
#define PLUGINCOMPATIBILITY_H

#include <QSet>
#include <QString>
#include <QStringList>

#include <optional>
#include <set>

namespace PluginCompatibility
{

struct Block
{
  QString id;
  QString reason;
};

std::optional<Block> blockedRule(const QString& gameName,
                                 const QStringList& pluginAncestry,
                                 const QSet<QString>& allowedRuleIds = {});

QSet<QString> environmentOverrides();

template <typename Plugin, typename NameGetter, typename MasterGetter>
std::optional<Block> blockedRuleForPlugin(const QString& gameName, Plugin* plugin,
                                          NameGetter nameGetter,
                                          MasterGetter masterGetter,
                                          const QSet<QString>& allowedRuleIds = {})
{
  QStringList ancestry;
  std::set<Plugin*> visited;
  while (plugin != nullptr && visited.insert(plugin).second) {
    ancestry.append(nameGetter(plugin));
    plugin = masterGetter(plugin);
  }
  return blockedRule(gameName, ancestry, allowedRuleIds);
}

}  // namespace PluginCompatibility

#endif  // PLUGINCOMPATIBILITY_H
