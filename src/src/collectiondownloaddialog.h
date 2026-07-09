#pragma once

#include "collectioninstaller.h"
#include "collectionmanifest.h"
#include "nexuscollections.h"

#include <QDialog>
#include <QHash>
#include <QListWidgetItem>
#include <QNetworkAccessManager>
#include <QPixmap>
#include <QVector>

class QPushButton;

namespace Ui { class CollectionDownloadDialog; }

class PluginContainer;

// ─── CollectionDownloadDialog ─────────────────────────────────────────────
//
// Four-page wizard for discovering and installing a Nexus Collection:
//
//   0 - Browse: gallery view with game/sort filters, detail pane
//   1 - Configure: instance name, downloads path, portable toggle
//   2 - Progress: streaming install log + progress bar
//   3 - Done: summary, optional switch-to-instance
//
class CollectionDownloadDialog : public QDialog
{
  Q_OBJECT

public:
  // pc may be nullptr when invoked from the instance manager (before an
  // active instance is set up).
  explicit CollectionDownloadDialog(PluginContainer* pc,
                                    QWidget* parent = nullptr);
  ~CollectionDownloadDialog() override;

  // Pre-select the game domain filter (e.g. "skyrimspecialedition").
  void setGameDomain(const QString& domain);

  // Set a detected game path so the config page is pre-filled.
  void setDetectedGamePath(const QString& path);

  // Returns the instance directory created at the end, or "" if none.
  QString createdInstanceDir() const;

  // Whether the user confirmed they want to switch to the new instance.
  bool shouldSwitchToInstance() const;

protected:
  void showEvent(QShowEvent* e) override;

private slots:
  void onNext();
  void onBack();
  void onCancel();

  // Gallery page.
  void loadGallery();
  void onLoadMore();
  void onGalleryReady(QVector<CollectionCard> cards, int offset, int totalCount);
  void onGalleryError(QString message);
  void onCollectionSelected(QListWidgetItem* item);
  void onShowAllGamesToggled(bool checked);
  void onSortChanged(int index);
  void onSearchChanged(const QString& text);
  void onBrowseGamePath();

  // Config page.
  void onBrowseDownloads();
  void onInstanceNameChanged(const QString& text);
  void onDownloadsPathChanged(const QString& text);
  void onAdultContentToggled(bool checked);

  // Installer signals.
  void onProgress(int done, int total);
  void onLog(QString message);
  void onInstallFinished(QString instanceDir);
  void onInstallFailed(QString reason);

  // Manifest fetch.
  void onManifestReady(QString jsonPath, QString extractedDir);
  void onManifestError(QString message);
  void onManifestProgress(qint64 recv, qint64 total);

private:
  enum Page { PageBrowse = 0, PageConfig = 1, PageProgress = 2, PageDone = 3 };

  std::unique_ptr<Ui::CollectionDownloadDialog> ui;
  PluginContainer*    m_pc{nullptr};
  NexusCollections    m_nexus;
  CollectionInstaller m_installer;

  QVector<CollectionCard> m_cards;
  CollectionCard          m_selected;
  CollectionManifest      m_manifest;

  QString m_extractedDir;
  QString m_createdInstanceDir;
  bool    m_authenticated{false};
  bool    m_isPremium{false};
  bool    m_switchOnClose{false};

  // Thumbnail cache: slug → scaled pixmap.
  QNetworkAccessManager   m_thumbnailNam;
  QHash<QString, QPixmap> m_thumbnailCache;

  // Pagination.
  int          m_galleryTotalCount = 0;
  QPushButton* m_loadMoreButton    = nullptr;

  // Detected games: map from Nexus domain → install path.
  QHash<QString, QString> m_detectedGamePaths;
  // Domains of detected games (for initial filter).
  QStringList m_detectedDomains;

  void setPage(Page p);
  void updateNav();

  void populateGameFilter();
  void filterCards();
  void applyCardToList(const CollectionCard& card, QListWidgetItem* item) const;
  void loadThumbnails();

  bool canGoNext() const;
  bool canGoBack() const;

  void startInstall();

  void detectGamesAndFillPaths();

  // Returns the game install path for the currently selected collection domain,
  // or "" if not detected / not set.
  QString resolvedGamePath() const;
};
