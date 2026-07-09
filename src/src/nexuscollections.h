#pragma once

#include <QNetworkAccessManager>
#include <QObject>
#include <QString>
#include <QVector>

#include "collectionmanifest.h"

// ─── Gallery card ────────────────────────────────────────────────────────────

struct CollectionCard {
  QString slug;
  QString name;
  QString summary;
  QString author;
  QString gameDomain;
  QString gameName;
  QString tileImageUrl;
  bool    isAdult         = false;
  quint64 endorsements    = 0;
  quint64 totalDownloads  = 0;
  quint64 latestRevision  = 0;
  quint64 totalSizeBytes  = 0;
  quint64 modCount        = 0;

  QString nexusUrl() const
  {
    return QString("https://next.nexusmods.com/%1/collections/%2").arg(gameDomain, slug);
  }
};

// ─── NexusCollections ────────────────────────────────────────────────────────

// Lightweight async wrapper around the Nexus v2 GraphQL endpoint.
// Auth is handled transparently via NexusInterface::instance().getAccessManager()
// so no API key needs to be passed; the user's OAuth session or legacy API key
// is picked up automatically from the existing MO2 settings.
//
// All network operations post results back via Qt signals; the caller
// must NOT block on them.
//
class NexusCollections : public QObject
{
  Q_OBJECT

public:
  enum class SortBy { Endorsements, Downloads, Recent };

  explicit NexusCollections(QObject* parent = nullptr);

  // ── Auth check ───────────────────────────────────────────────────────────

  // Checks whether the user is authenticated (OAuth or legacy API key) and
  // whether the account has Nexus Premium.
  // Emits validateReady() on success, validateError() on failure.
  void checkAuth();

  // ── Gallery ──────────────────────────────────────────────────────────────

  // Fetch a page of collection cards from the gallery.
  // `gameDomain` is the Nexus URL slug (e.g. "skyrimspecialedition"); pass
  // an empty string to query all games.
  // Emits galleryReady() on success, galleryError() on failure.
  void fetchGallery(const QString& gameDomain,
                    SortBy sort   = SortBy::Endorsements,
                    int offset    = 0,
                    int count     = 30);

  // ── Manifest ─────────────────────────────────────────────────────────────

  // Download and extract the collection .7z archive for the given slug,
  // storing the extracted files under `workDir/<slug>/`.
  // Emits manifestReady() with the path to collection.json on success,
  // manifestError() on failure.
  void fetchManifest(const QString& slug,
                     const QString& gameDomain,
                     const QString& workDir,
                     int revision = 0); // 0 → latest

  // ── Nexus domain ↔ game name mapping ────────────────────────────────────

  // Map a KNOWN_GAMES name to its Nexus domain slug, or "" if unknown.
  static QString domainForGameName(const QString& gameName);

  // Map a Steam App ID string to a Nexus domain slug, or "" if unknown.
  static QString domainForSteamAppId(const QString& appId);

  // Map a Nexus domain slug to a display name, or the slug itself if unknown.
  static QString gameNameForDomain(const QString& domain);

signals:
  void galleryReady(QVector<CollectionCard> cards, int offset, int totalCount);
  void galleryError(QString message);

  void manifestReady(QString collectionJsonPath, QString extractedDir);
  void manifestError(QString message);

  void validateReady(QString userName, bool isPremium);
  void validateError(QString message);

  // Download progress for the manifest archive (bytes received, total).
  void manifestProgress(qint64 received, qint64 total);

private:
  // Used for CDN downloads and legacy API key calls (no OAuth auth needed).
  QNetworkAccessManager m_nam;

  // Step 1: resolve download link via GraphQL.
  void fetchManifestDownloadLink(const QString& slug,
                                 const QString& gameDomain,
                                 const QString& workDir,
                                 int revision);

  // Step 2: resolve CDN URL from the Nexus download API response.
  void fetchManifestCdnLink(const QString& downloadApiUrl,
                             const QString& slug,
                             const QString& workDir);

  // Step 3: download .7z and extract.
  void downloadAndExtractManifest(const QString& downloadUrl,
                                  const QString& slug,
                                  const QString& workDir);

  // Find the 7z binary: bundled 7zz > system 7z / 7za / 7zz.
  static QString find7z();

  // Extract a .7z archive to destDir; returns true on success.
  static bool extract7z(const QString& archivePath, const QString& destDir);
};
