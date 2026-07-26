#ifndef FLUORINE_UPDATE_INSTALLER_H
#define FLUORINE_UPDATE_INSTALLER_H

#include "fluorineupdater.h"

#include <QObject>
#include <QString>

// Downloads a release into the existing update staging directory, validates
// that it contains a launcher, and hands it to the launcher's existing
// single-copy sync process after Fluorine exits.
class FluorineUpdateInstaller : public QObject
{
  Q_OBJECT

public:
  explicit FluorineUpdateInstaller(QObject* parent = nullptr);

  bool isBusy() const { return m_busy; }
  void install(const FluorineUpdater::ReleaseInfo& info);

signals:
  void statusChanged(const QString& status);
  void downloadProgress(qint64 received, qint64 total);
  void failed(const QString& reason);

private:
  void fail(const QString& reason);

  bool m_busy = false;
};

#endif  // FLUORINE_UPDATE_INSTALLER_H
