#ifndef FLUORINE_UPDATER_H
#define FLUORINE_UPDATER_H

#include <QJsonObject>
#include <QObject>
#include <QString>

class QNetworkAccessManager;
class QNetworkReply;

// Lightweight self-update checker. Queries the GitHub Releases API for
// Fluorine Manager and notifies when a newer build is available. Installation
// remains user-controlled through the update prompt or Settings.
//
// Two user-facing channels:
//   stable: fetches the latest tagged `v*` release and compares against the
//           build's FLUORINE_VERSION_STRING.
//   nightly: fetches the rolling `nightly` tag and compares its monotonic CI
//            build number against the installed build.
class FluorineUpdater : public QObject
{
  Q_OBJECT

public:
  enum class Channel
  {
    Stable,
    Nightly,
  };

  struct ReleaseInfo
  {
    Channel channel       = Channel::Stable;
    QString tagName;       // "v0.3.2" or "nightly"
    QString name;          // release title
    QString releaseNotes;  // release body
    QString htmlUrl;       // release HTML page
    QString downloadUrl;   // first .tar.gz asset URL (may be empty)
    QString buildNumber;   // nightly only: monotonically increasing CI run number
    QString timestamp;     // nightly only: "YYYYMMDDHHMM"
    QString commit;        // nightly only: full commit SHA
    QString versionString; // stable only: tag minus leading 'v'
  };

  explicit FluorineUpdater(QObject* parent = nullptr);
  ~FluorineUpdater() override;

  // Kick off an async check. Emits updateAvailable()/upToDate()/checkFailed()
  // exactly once per call.
  void checkForUpdates(Channel channel);

  // Build channel that was baked into this binary at compile time. The
  // Settings toggle defaults to this value.
  static Channel buildChannel();

  static QString channelToString(Channel c);
  static Channel channelFromString(const QString& s, Channel fallback);

signals:
  void updateAvailable(const FluorineUpdater::ReleaseInfo& info);
  void upToDate(const FluorineUpdater::ReleaseInfo& info);
  void checkFailed(const QString& reason);

private slots:
  void onReplyFinished();

private:
  static bool parseNightlyRelease(const QJsonObject& obj, ReleaseInfo& out);
  static bool parseStableRelease(const QJsonObject& obj, ReleaseInfo& out);

  QNetworkAccessManager* m_net;
  QNetworkReply* m_reply = nullptr;
  Channel m_pendingChannel = Channel::Stable;
};

#endif  // FLUORINE_UPDATER_H
