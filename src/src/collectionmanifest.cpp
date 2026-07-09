#include "collectionmanifest.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

static CollectionFomodChoices parseFomodChoices(const QJsonObject& obj)
{
  CollectionFomodChoices choices;
  for (const QJsonValue& stepVal : obj["options"].toArray()) {
    const QJsonObject stepObj = stepVal.toObject();
    CollectionFomodStep step;
    step.name = stepObj["name"].toString();
    for (const QJsonValue& groupVal : stepObj["groups"].toArray()) {
      const QJsonObject groupObj = groupVal.toObject();
      CollectionFomodGroup group;
      group.name = groupObj["name"].toString();
      for (const QJsonValue& choiceVal : groupObj["choices"].toArray()) {
        const QJsonObject choiceObj = choiceVal.toObject();
        CollectionFomodChoice choice;
        choice.name = choiceObj["name"].toString();
        choice.idx  = choiceObj["idx"].toInt(0);
        group.choices.append(choice);
      }
      step.groups.append(group);
    }
    choices.options.append(step);
  }
  return choices;
}

static CollectionModSource parseSource(const QJsonObject& obj)
{
  CollectionModSource src;
  src.type             = obj["type"].toString();
  src.modId            = obj["modId"].toInt(0);
  src.fileId           = obj["fileId"].toInt(0);
  src.logicalFilename  = obj["logicalFilename"].toString();
  src.fileSize         = static_cast<qint64>(obj["fileSize"].toDouble(0));
  src.md5              = obj["md5"].toString();
  src.url              = obj["url"].toString();
  src.instructions     = obj["instructions"].toString();
  return src;
}

CollectionManifest CollectionManifest::fromJson(const QByteArray& data)
{
  CollectionManifest m;
  const QJsonObject root = QJsonDocument::fromJson(data).object();
  if (root.isEmpty())
    return m;

  // Support both {info:{name,author,...}, ...} and flat {collectionName,...}.
  const QJsonObject info = root["info"].toObject();
  m.name        = info["name"].toString();
  if (m.name.isEmpty()) m.name       = root["collectionName"].toString();
  m.author      = info["author"].toString();
  if (m.author.isEmpty()) m.author   = root["author"].toString();
  m.domainName  = info["domainName"].toString();
  if (m.domainName.isEmpty()) m.domainName = root["domainName"].toString();
  m.description = info["description"].toString();
  if (m.description.isEmpty()) m.description = root["description"].toString();
  m.version     = root["version"].toString();

  for (const QJsonValue& v : root["mods"].toArray()) {
    const QJsonObject obj = v.toObject();
    CollectionMod mod;
    mod.name             = obj["name"].toString();
    mod.logicalFilename  = obj["logicalFilename"].toString();
    mod.folderName       = obj["folderName"].toString();
    mod.version          = obj["version"].toString();
    mod.source           = parseSource(obj["source"].toObject());
    mod.phase            = obj["phase"].toInt(0);
    mod.optional         = obj["optional"].toBool(false);
    mod.domainName       = obj["domainName"].toString(m.domainName);

    if (obj.contains("choices"))
      mod.choices = parseFomodChoices(obj["choices"].toObject());

    for (const QJsonValue& fo : obj["fileOverrides"].toArray())
      mod.fileOverrides.append(fo.toString());

    m.mods.append(mod);
  }

  for (const QJsonValue& v : root["plugins"].toArray()) {
    const QJsonObject obj = v.toObject();
    CollectionPlugin plugin;
    plugin.name    = obj["name"].toString();
    plugin.enabled = obj["enabled"].toBool(false);
    m.plugins.append(plugin);
  }

  for (const QJsonValue& v : root["modRules"].toArray()) {
    const QJsonObject obj = v.toObject();
    CollectionModRule rule;
    rule.type              = obj["type"].toString();
    rule.sourceMd5         = obj["source"].toObject()["fileMD5"].toString();
    rule.sourceFilename    = obj["source"].toObject()["logicalFileName"].toString();
    rule.referenceMd5      = obj["reference"].toObject()["fileMD5"].toString();
    rule.referenceFilename = obj["reference"].toObject()["logicalFileName"].toString();
    m.modRules.append(rule);
  }

  return m;
}
