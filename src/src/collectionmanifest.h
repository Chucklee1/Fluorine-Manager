#pragma once

#include <optional>
#include <QString>
#include <QStringList>
#include <QVector>

// ─── FOMOD pre-recorded choices ─────────────────────────────────────────────

struct CollectionFomodChoice {
  QString name;
  int idx = 0;
};

struct CollectionFomodGroup {
  QString name;
  QVector<CollectionFomodChoice> choices;
};

struct CollectionFomodStep {
  QString name;
  QVector<CollectionFomodGroup> groups;
};

struct CollectionFomodChoices {
  QVector<CollectionFomodStep> options;
  bool hasChoices() const { return !options.isEmpty(); }
};

// ─── Mod source ─────────────────────────────────────────────────────────────

struct CollectionModSource {
  QString type;             // "nexus", "direct", "browse"
  int modId  = 0;
  int fileId = 0;
  QString logicalFilename;
  qint64 fileSize = 0;
  QString md5;
  QString url;          // for "direct" sources
  QString instructions; // for "browse" (manual) sources
};

// ─── Single mod entry ────────────────────────────────────────────────────────

struct CollectionMod {
  QString name;
  QString logicalFilename;
  QString folderName;
  QString version;
  CollectionModSource source;
  std::optional<CollectionFomodChoices> choices;
  int phase = 0;
  bool optional = false;
  QString domainName;
  QStringList fileOverrides;
};

// ─── Plugin (ESP/ESM/ESL) entry ──────────────────────────────────────────────

struct CollectionPlugin {
  QString name;
  bool enabled = false;
};

// ─── Mod ordering rule ───────────────────────────────────────────────────────

struct CollectionModRule {
  QString type;              // "before" | "after"
  QString sourceMd5;
  QString sourceFilename;
  QString referenceMd5;
  QString referenceFilename;
};

// ─── Top-level manifest ──────────────────────────────────────────────────────

struct CollectionManifest {
  QString name;
  QString author;
  QString domainName;
  QString description;
  QString version;
  QString slug;       // from the URL, not the JSON itself

  QVector<CollectionMod>     mods;
  QVector<CollectionPlugin>  plugins;
  QVector<CollectionModRule> modRules;

  // Returns true when the manifest was populated (has at least a name).
  bool isValid() const { return !name.isEmpty(); }

  // Parse from raw collection.json bytes.  Returns an invalid manifest on error.
  static CollectionManifest fromJson(const QByteArray& data);
};
