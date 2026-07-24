#include "slrmanager.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QNetworkRequest>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QProcess>
#include <QTemporaryDir>
#include <QTimer>
#include <QEventLoop>
#include <uibase/log.h>

namespace {

// Pin SLR releases explicitly. Valve's latest-public-beta directory alias can
// fail at the edge cache even while the corresponding versioned directory is
// available. Update this URL deliberately when adopting a newer runtime.
const char* BASE_URL =
    "https://repo.steampowered.com/steamrt4/images/4.0.20260714.251823";
const char* ARCHIVE_NAME = "SteamLinuxRuntime_4.tar.xz";
const char* EXTRACTED_DIR = "SteamLinuxRuntime_4";

// steamrt4 (Debian bookworm-based) ships without xrandr, which Proton-GE
// and some protonfixes require at launch. We inject it from the Debian
// x11-xserver-utils package.
const char* XRANDR_DEB_URL =
    "http://ftp.debian.org/debian/pool/main/x/x11-xserver-utils/"
    "x11-xserver-utils_7.7+11_amd64.deb";

QString slrInstallDir()
{
  return QDir::homePath() + "/.local/share/fluorine/steamrt";
}

QString slrRunScriptPath()
{
  return slrInstallDir() + "/" + EXTRACTED_DIR + "/run";
}

QString localBuildIdPath()
{
  return slrInstallDir() + "/BUILD_ID.txt";
}

/// Blocking HTTP GET that returns the response body as QByteArray.
QByteArray httpGet(const QString& url, const int* cancelFlag,
                   const std::function<void(float)>& progressCb = nullptr,
                   const QString& destFile = {})
{
  QNetworkAccessManager mgr;
  QNetworkRequest request{QUrl(url)};
  request.setRawHeader("User-Agent", "Fluorine-Manager/slr");
  request.setAttribute(QNetworkRequest::RedirectPolicyAttribute,
                       QNetworkRequest::NoLessSafeRedirectPolicy);
  request.setAttribute(QNetworkRequest::Http2AllowedAttribute, false);

  QNetworkReply* reply = mgr.get(request);
  QEventLoop loop;

  QFile outFile;
  if (!destFile.isEmpty()) {
    outFile.setFileName(destFile);
    if (!outFile.open(QIODevice::WriteOnly))
      return {};
  }

  QByteArray inMemoryBuf;
  qint64 totalBytes = -1;
  qint64 received   = 0;

  QObject::connect(reply, &QNetworkReply::readyRead, [&]() {
    if (totalBytes < 0)
      totalBytes = reply->header(QNetworkRequest::ContentLengthHeader).toLongLong();
    QByteArray chunk = reply->readAll();
    received += chunk.size();
    if (outFile.isOpen())
      outFile.write(chunk);
    else
      inMemoryBuf.append(chunk);
    if (progressCb && totalBytes > 0)
      progressCb(static_cast<float>(received) / static_cast<float>(totalBytes));
  });

  QObject::connect(reply, &QNetworkReply::finished, &loop, &QEventLoop::quit);

  // Poll cancel flag via a timer.
  QTimer cancelTimer;
  if (cancelFlag) {
    QObject::connect(&cancelTimer, &QTimer::timeout, [&]() {
      if (*cancelFlag != 0) {
        reply->abort();
        loop.quit();
      }
    });
    cancelTimer.start(200);
  }

  loop.exec();

  if (outFile.isOpen())
    outFile.close();

  if (reply->error() != QNetworkReply::NoError) {
    MOBase::log::warn("SLR download request failed: {} ({})",
                      url,
                      reply->errorString());
    reply->deleteLater();
    if (!destFile.isEmpty())
      QFile::remove(destFile);
    return {};
  }

  reply->deleteLater();
  return inMemoryBuf;
}

QString readLocalBuildId()
{
  QFile f(localBuildIdPath());
  if (!f.open(QIODevice::ReadOnly)) {
    return {};
  }
  return QString::fromUtf8(f.readAll()).trimmed();
}

bool writeLocalBuildId(const QString& buildId)
{
  QFile f(localBuildIdPath());
  if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
    return false;
  }
  f.write(buildId.toUtf8());
  f.write("\n");
  return true;
}

bool makeExecutable(const QString& path)
{
  return QFile::setPermissions(path,
                               QFileDevice::ReadOwner | QFileDevice::WriteOwner |
                                   QFileDevice::ExeOwner | QFileDevice::ReadGroup |
                                   QFileDevice::ExeGroup | QFileDevice::ReadOther |
                                   QFileDevice::ExeOther);
}

bool replaceRuntimeAtomically(const QString& stagedRuntimeDir, QString& err)
{
  const QString installDir   = slrInstallDir();
  const QString extractedDir = installDir + "/" + EXTRACTED_DIR;
  const QString backupDir    = installDir + "/" + EXTRACTED_DIR + ".previous";

  if (!QFileInfo::exists(stagedRuntimeDir + "/run")) {
    err = QStringLiteral("staged runtime is missing run script");
    return false;
  }
  makeExecutable(stagedRuntimeDir + "/run");

  QDir().mkpath(installDir);
  QDir(backupDir).removeRecursively();

  bool hadPrevious = QFileInfo::exists(extractedDir);
  if (hadPrevious && !QDir().rename(extractedDir, backupDir)) {
    err = QStringLiteral("failed to move existing runtime aside");
    return false;
  }

  if (!QDir().rename(stagedRuntimeDir, extractedDir)) {
    if (hadPrevious) {
      QDir().rename(backupDir, extractedDir);
    }
    err = QStringLiteral("failed to install staged runtime");
    return false;
  }

  if (hadPrevious) {
    QDir(backupDir).removeRecursively();
  }
  return true;
}

}  // namespace

bool isSlrInstalled()
{
  const QString script = slrRunScriptPath();
  QFileInfo fi(script);
  return fi.exists() && fi.isExecutable();
}

QString xrandrInjectedPath()
{
  return slrInstallDir() + "/xrandr-bin/xrandr";
}

bool isXrandrInjected()
{
  QFileInfo fi(xrandrInjectedPath());
  return fi.exists() && fi.isExecutable();
}

// Download + extract xrandr from the Debian x11-xserver-utils package into
// the SLR install dir. Called standalone for users who installed the
// runtime before the xrandr step existed, and inline from downloadSlr() for
// fresh installs.
static bool installXrandrAssets(const int* cancelFlag,
                                const std::function<void(const QString&)>& statusCb)
{
  auto status = [&](const QString& msg) { if (statusCb) statusCb(msg); };

  const QString installDir = slrInstallDir();
  QDir().mkpath(installDir);

  const QString debPath = installDir + "/x11-xserver-utils.deb";
  status(QStringLiteral("Downloading xrandr..."));
  httpGet(QString::fromLatin1(XRANDR_DEB_URL), cancelFlag, nullptr, debPath);
  if (!QFileInfo::exists(debPath)) {
    MOBase::log::warn("Failed to download xrandr .deb — runtime will lack xrandr");
    return false;
  }

  const QString tmpExtract = installDir + "/xrandr_tmp";
  QDir(tmpExtract).removeRecursively();
  QDir().mkpath(tmpExtract);

  QProcess ar;
  ar.setWorkingDirectory(tmpExtract);
  ar.start(QStringLiteral("ar"),
           {QStringLiteral("x"), debPath, QStringLiteral("data.tar.xz")});
  ar.waitForFinished(30000);

  QProcess untar;
  untar.setWorkingDirectory(tmpExtract);
  untar.start(QStringLiteral("tar"),
              {QStringLiteral("xf"), QStringLiteral("data.tar.xz"),
               QStringLiteral("./usr/bin/xrandr")});
  untar.waitForFinished(30000);

  const QString xrandrSrc = tmpExtract + "/usr/bin/xrandr";
  bool ok = false;
  if (QFileInfo::exists(xrandrSrc)) {
    const QString xrandrDir = installDir + "/xrandr-bin";
    QDir().mkpath(xrandrDir);
    const QString dst = xrandrDir + "/xrandr";
    QFile::remove(dst);
    if (QFile::copy(xrandrSrc, dst)) {
      QFile::setPermissions(dst, QFileDevice::ReadOwner | QFileDevice::WriteOwner |
                                     QFileDevice::ExeOwner | QFileDevice::ReadGroup |
                                     QFileDevice::ExeGroup | QFileDevice::ReadOther |
                                     QFileDevice::ExeOther);
      MOBase::log::info("Installed xrandr to {}", dst.toStdString());
      ok = true;
    } else {
      MOBase::log::warn("Failed to copy xrandr into fluorine bin dir");
    }
  } else {
    MOBase::log::warn("xrandr .deb extracted but binary not found");
  }

  QDir(tmpExtract).removeRecursively();
  QFile::remove(debPath);
  return ok;
}

bool ensureXrandrInstalled(const int* cancelFlag,
                           const std::function<void(const QString&)>& statusCb)
{
  if (isXrandrInjected()) {
    return true;
  }
  return installXrandrAssets(cancelFlag, statusCb);
}

QString getSlrRunScript()
{
  return isSlrInstalled() ? slrRunScriptPath() : QString();
}

SlrUpdateInfo checkSlrUpdate(const int* cancelFlag)
{
  SlrUpdateInfo info;
  info.installed    = isSlrInstalled();
  info.localBuildId = readLocalBuildId();

  const QByteArray remoteBuildIdRaw = httpGet(
      QStringLiteral("%1/BUILD_ID.txt").arg(QLatin1String(BASE_URL)), cancelFlag);
  if (remoteBuildIdRaw.isEmpty()) {
    info.error = QStringLiteral("Failed to fetch SLR BUILD_ID");
    return info;
  }

  info.remoteBuildId    = QString::fromUtf8(remoteBuildIdRaw).trimmed();
  info.updateAvailable = info.installed && info.localBuildId != info.remoteBuildId;
  return info;
}

QString downloadSlr(const std::function<void(float)>& progressCb,
                    const std::function<void(const QString&)>& statusCb,
                    const int* cancelFlag)
{
  auto status = [&](const QString& msg) { if (statusCb) statusCb(msg); };
  auto progress = [&](float p) { if (progressCb) progressCb(p); };

  // 1. Check for updates.
  status(QStringLiteral("Checking Steam Linux Runtime version..."));

  const SlrUpdateInfo updateInfo = checkSlrUpdate(cancelFlag);
  if (!updateInfo.error.isEmpty())
    return updateInfo.error;

  const QString remoteBuildId = updateInfo.remoteBuildId;
  const QString localBuildId  = updateInfo.localBuildId;

  if (localBuildId == remoteBuildId && isSlrInstalled()) {
    MOBase::log::info("Steam Linux Runtime is already up to date");
    // Existing installs from earlier Fluorine versions may not have the
    // xrandr helper (issue #49). Back-fill it so Proton-GE prefix init
    // doesn't silently fail on distros without host xrandr exposed.
    if (!isXrandrInjected()) {
      status(QStringLiteral("Injecting xrandr into existing runtime..."));
      installXrandrAssets(cancelFlag, statusCb);
    }
    status(QStringLiteral("Steam Linux Runtime is already up to date"));
    progress(1.0f);
    return {};
  }

  MOBase::log::info("Downloading Steam Linux Runtime (BUILD_ID: {})", remoteBuildId);

  const QString installDir = slrInstallDir();
  QDir().mkpath(installDir);

  QTemporaryDir stagingRoot(installDir + "/slr-update-XXXXXX");
  if (!stagingRoot.isValid()) {
    return QStringLiteral("Failed to create SLR staging directory");
  }
  const QString archivePath = stagingRoot.filePath(ARCHIVE_NAME);

  // 2. Download.
  status(QStringLiteral("Downloading Steam Linux Runtime (steamrt4, ~200 MB)..."));
  httpGet(QStringLiteral("%1/%2").arg(QLatin1String(BASE_URL), QLatin1String(ARCHIVE_NAME)),
          cancelFlag, progress, archivePath);
  progress(1.0f);

  if (!QFileInfo::exists(archivePath))
    return QStringLiteral("Download failed or was cancelled");

  // 3. Extract.
  status(QStringLiteral("Extracting Steam Linux Runtime..."));

  QProcess tar;
  tar.setWorkingDirectory(stagingRoot.path());
  tar.start(QStringLiteral("tar"), {QStringLiteral("xJf"), archivePath});
  tar.waitForFinished(600000);
  QFile::remove(archivePath);

  if (tar.exitStatus() != QProcess::NormalExit || tar.exitCode() != 0)
    return QStringLiteral("tar extraction failed (exit code %1)").arg(tar.exitCode());

  const QString stagedRuntimeDir = stagingRoot.filePath(EXTRACTED_DIR);
  if (!QFileInfo::exists(stagedRuntimeDir + "/run"))
    return QStringLiteral("Extraction succeeded but run script not found");

  QString replaceError;
  if (!replaceRuntimeAtomically(stagedRuntimeDir, replaceError)) {
    return replaceError;
  }

  // 4. Inject xrandr into the container (steamrt4 ships without it, but
  // Proton-GE and several protonfixes invoke xrandr during launch).
  status(QStringLiteral("Injecting xrandr into runtime..."));
  installXrandrAssets(cancelFlag, statusCb);

  // 5. Save BUILD_ID.
  if (!writeLocalBuildId(remoteBuildId)) {
    MOBase::log::warn("Failed to write SLR BUILD_ID marker");
  }

  MOBase::log::info("Steam Linux Runtime installed successfully");
  status(QStringLiteral("Steam Linux Runtime ready"));
  return {};
}
