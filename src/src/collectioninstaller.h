#pragma once

#include "collectionmanifest.h"
#include "nexuscollections.h"

#include <QDir>
#include <QNetworkAccessManager>
#include <QObject>
#include <QString>
#include <QVector>

// ─── Install configuration ────────────────────────────────────────────────

struct CollectionInstallConfig {
  // Where collection.json + patches live (extracted from the manifest .7z).
  QString extractedCollectionDir;

  // Where downloaded mod archives are cached / placed.
  QString downloadsDir;

  // Root of the MO2 instance to create.
  // If empty, a subdirectory of downloadsDir is used.
  QString instanceDir;

  // Instance name that appears in the MO2 instance list.
  QString instanceName;

  // Path to the game installation (used for initial instance config).
  QString gamePath;

  // Nexus game domain (e.g. "skyrimspecialedition"). Filled from the manifest
  // when left empty.
  QString gameDomain;

  // True → write a portable ModOrganizer.ini inside instanceDir.
  // False → register as a global instance under the global instances root.
  bool portable = true;
};

// ─── Per-mod install status ───────────────────────────────────────────────

struct ModInstallResult {
  QString name;
  enum Status { Pending, Downloading, Extracting, Done, Skipped, Failed } status = Pending;
  QString error;
};

// ─── CollectionInstaller ─────────────────────────────────────────────────

// Orchestrates the full collection install pipeline:
//   1. Download each mod archive (premium: direct REST; free: NXM TBD)
//   2. Extract to modsDir/<folderName>/
//   3. Apply pre-recorded FOMOD choices
//   4. Route root files to Root/ subdirectory
//   5. Write modlist.txt + plugins.txt
//   6. Write ModOrganizer.ini (portable or register global)
//
// All operations run asynchronously.  Progress is reported via signals.
// Call start() once; it drives itself to completion.
//
class CollectionInstaller : public QObject
{
  Q_OBJECT

public:
  explicit CollectionInstaller(QObject* parent = nullptr);

  // Begin the install.  Must only be called once per instance.
  void start(const CollectionManifest& manifest,
             const CollectionInstallConfig& config);

  // Request cancellation.  The installer will stop after the current
  // in-flight download/extract completes.
  void cancel();

signals:
  // Overall progress [0, total].
  void progress(int done, int total);

  // Human-readable log line (same as what would appear in a progress dialog).
  void log(QString message);

  // Per-mod status update.
  void modStatus(int index, ModInstallResult::Status status, QString error);

  // Emitted on successful completion.
  void finished(QString instanceDir);

  // Emitted on fatal error (after which no further signals will fire).
  void failed(QString reason);

private:
  QNetworkAccessManager m_nam;
  CollectionManifest    m_manifest;
  CollectionInstallConfig m_config;
  QVector<ModInstallResult> m_results;
  bool m_cancelled = false;
  int m_currentIdx = 0;

  // Directory helpers derived from config.
  QString modsDir()     const;
  QString profileDir()  const;
  QString downloadsDir() const;

  // Drive install for the next mod in m_results.
  void installNext();

  // Download step.
  void downloadMod(int idx);
  void downloadFromCdnUrl(int idx, const QString& cdnUrl);
  void onDownloadFinished(int idx, const QString& archivePath);

  // Extract step: start async 7z process; onExtractionDone is the continuation.
  void extractMod(int idx, const QString& archivePath);
  void finishExtract(int idx, const QString& archivePath, const QString& tempDir);

  // Apply pre-recorded FOMOD choices from the manifest.
  // Returns the directory containing the selected files (a subdirectory of
  // tempDir, or tempDir itself when no FOMOD is present).
  QString applyFomod(int idx, const QString& tempDir);

  // Move root files (matching per-game rules) from modDir into modDir/Root/.
  void routeRootFiles(const QString& modDir, const QString& gameDomain);

  // Write modlist.txt, plugins.txt, and ModOrganizer.ini.
  void finalise();

  // Find the 7z binary (bundled 7zz > system 7z/7za/7zz).
  static QString find7z();

  // Parse a FOMOD ModuleConfig.xml and copy the selected files.
  // Returns true if FOMOD was found and applied; false if the mod has no FOMOD.
  bool executeFomod(const QString& extractedRoot,
                    const QString& destDir,
                    const CollectionFomodChoices& choices);

  // Recursively copy src → dst, overwriting existing files.
  static bool copyDir(const QString& src, const QString& dst);

  // True when the Nexus domain + filename combination belongs at game root
  // rather than inside Data/.  Mirrors CLF3's root_files.rs rules.
  static bool isRootFile(const QString& filename, const QString& gameDomain);
  static bool isRootFolder(const QString& folderName, const QString& gameDomain);
};
