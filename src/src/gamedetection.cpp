#include "gamedetection.h"
#include "heroicjson.h"
#include "knowngames.h"
#include "vdfparser.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QSet>
#include <uibase/log.h>
#include <optional>

// ============================================================================
// Wine registry helpers
// ============================================================================

namespace {

/// Parse a quoted registry value, handling Wine escape sequences.
QString parseQuotedRegValue(const QString& s)
{
  if (!s.startsWith('"'))
    return {};

  QString result;
  bool esc = false;
  for (int i = 1; i < s.size(); ++i) {
    QChar const c = s[i];
    if (esc) {
      if (c == 'n') result += '\n';
      else if (c == 'r') result += '\r';
      else if (c == 't') result += '\t';
      else if (c == '\\') result += '\\';
      else if (c == '"') result += '"';
      else { result += '\\'; result += c; }
      esc = false;
    } else if (c == '\\') {
      esc = true;
    } else if (c == '"') {
      break;
    } else {
      result += c;
    }
  }
  return result;
}

/// Parse a registry value line like "ValueName"="value".
std::pair<QString, QString> parseRegValueLine(const QString& line)
{
  int const eq = line.indexOf('=');
  if (eq < 0)
    return {};

  QString const namePart = line.left(eq).trimmed();
  QString const valPart  = line.mid(eq + 1);

  QString const name = (namePart == QStringLiteral("@"))
      ? QStringLiteral("@")
      : namePart.mid(1, namePart.size() - 2);  // strip quotes

  QString value;
  if (valPart.startsWith('"')) {
    value = parseQuotedRegValue(valPart);
  } else if (valPart.startsWith(QStringLiteral("dword:"))) {
    bool ok;
    uint const v = valPart.mid(6).toUInt(&ok, 16);
    value  = ok ? QString::number(v) : valPart;
  } else {
    value = valPart;
  }
  return {name, value};
}

/// Find a value inside registry content for a given key section.
QString findValueInContent(const QString& content, const QString& key,
                           const QString& valueName)
{
  const QString keyLower  = key.toLower();
  const QString valLower  = valueName.toLower();
  bool inTarget = false;

  for (const auto& line : content.split('\n')) {
    const QString trimmed = line.trimmed();
    if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
      inTarget = (trimmed.toLower() == keyLower);
      continue;
    }
    if (!inTarget) continue;
    if (trimmed.isEmpty()) continue;
    if (trimmed.startsWith('[')) break;

    auto [name, value] = parseRegValueLine(trimmed);
    if (name.toLower() == valLower)
      return value;
  }
  return {};
}

/// Read a registry value from a Wine prefix.
QString readRegistryValue(const QString& prefixPath, const QString& keyPath,
                          const QString& valueName)
{
  // Wine key format: lowercase, double-escaped backslashes.
  auto wineKey = [](const QString& kp) {
    return QStringLiteral("[%1]").arg(
        kp.toLower().replace('\\', QStringLiteral("\\\\")));
  };

  // Wow6432Node variant.
  auto wow64Key = [](const QString& kp) {
    QString stripped = kp;
    if (stripped.startsWith(QStringLiteral("Software\\"), Qt::CaseInsensitive))
      stripped = stripped.mid(9);
    return QStringLiteral("[software\\\\wow6432node\\\\%1]").arg(
        stripped.toLower().replace('\\', QStringLiteral("\\\\")));
  };

  for (const char* regFile : {"system.reg", "user.reg"}) {
    QFile f(QDir(prefixPath).filePath(QString::fromLatin1(regFile)));
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
      continue;
    const QString content = QString::fromUtf8(f.readAll());

    QString val = findValueInContent(content, wineKey(keyPath), valueName);
    if (!val.isEmpty()) return val;

    val = findValueInContent(content, wow64Key(keyPath), valueName);
    if (!val.isEmpty()) return val;
  }
  return {};
}

/// Convert a Wine Z: path to a Linux path.
QString winePathToLinux(const QString& winePath)
{
  if (winePath.startsWith(QStringLiteral("Z:"), Qt::CaseInsensitive) ||
      winePath.startsWith(QStringLiteral("z:"), Qt::CaseInsensitive))
    return QString(winePath).mid(2).replace('\\', '/');
  return {};
}

// ============================================================================
// Steam game detection
// ============================================================================

struct SteamInstallation {
  QString path;
  bool is_flatpak = false;
  bool is_snap    = false;
};

QVector<SteamInstallation> findSteamInstallations()
{
  QVector<SteamInstallation> installs;
  const QString home = QDir::homePath();

  static const char* PATHS[] = {
      ".local/share/Steam",
      ".steam/debian-installation",
      ".steam/steam",
      ".var/app/com.valvesoftware.Steam/data/Steam",
      ".var/app/com.valvesoftware.Steam/.local/share/Steam",
      "snap/steam/common/.local/share/Steam",
  };

  QSet<QString> seen;
  for (const char* rel : PATHS) {
    const QString full = QDir(home).filePath(QString::fromLatin1(rel));
    if (!QFileInfo::exists(full + "/steamapps") &&
        !QFileInfo::exists(full + "/steam.pid"))
      continue;

    const QString canonical = QFileInfo(full).canonicalFilePath();
    if (seen.contains(canonical))
      continue;
    seen.insert(canonical);

    SteamInstallation si;
    si.path       = full;
    si.is_flatpak = QString::fromLatin1(rel).contains(
        QStringLiteral(".var/app/com.valvesoftware.Steam"));
    si.is_snap    = QString::fromLatin1(rel).contains(QStringLiteral("snap/steam"));
    installs.append(si);
  }
  return installs;
}

QStringList getLibraryFolders(const QString& steamPath)
{
  QStringList folders;
  folders.append(steamPath);

  for (const char* sub : {"steamapps/libraryfolders.vdf",
                           "config/libraryfolders.vdf"}) {
    QFile f(QDir(steamPath).filePath(QString::fromLatin1(sub)));
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
      continue;
    for (const QString& p : parseLibraryFolders(QString::fromUtf8(f.readAll()))) {
      if (QFileInfo::exists(p) && !folders.contains(p))
        folders.append(p);
    }
  }
  return folders;
}

QVector<DetectedGame> detectSteamGames()
{
  QVector<DetectedGame> games;

  for (const auto& si : findSteamInstallations()) {
    const QStringList libraries = getLibraryFolders(si.path);

    // Collect all steamapps paths for cross-library compatdata search.
    QStringList allSteamapps;
    for (const QString& lib : libraries) {
      const QString sa = lib + "/steamapps";
      if (QFileInfo::exists(sa))
        allSteamapps.append(sa);
    }

    for (const QString& steamapps : allSteamapps) {
      QDir const dir(steamapps);
      const QStringList acfs =
          dir.entryList({QStringLiteral("appmanifest_*.acf")}, QDir::Files);

      for (const QString& acf : acfs) {
        QFile f(dir.filePath(acf));
        if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
          continue;

        AppManifest const m = AppManifest::fromVdf(QString::fromUtf8(f.readAll()));
        if (m.app_id.isEmpty() || !m.isInstalled())
          continue;

        const QString installPath = steamapps + "/common/" + m.install_dir;
        if (!QFileInfo::exists(installPath))
          continue;

        // Search all library folders for compatdata.
        QString prefixPath;
        for (const QString& sa : allSteamapps) {
          const QString pfx = sa + "/compatdata/" + m.app_id + "/pfx";
          if (QFileInfo::exists(pfx)) {
            prefixPath = pfx;
            break;
          }
        }

        const KnownGame* kg = findKnownGameBySteamId(m.app_id);

        DetectedGame g;
        g.name         = m.name;
        g.app_id       = m.app_id;
        g.install_path = installPath;
        g.prefix_path  = prefixPath;
        g.launcher     = si.is_flatpak ? QStringLiteral("Steam (Flatpak)")
                         : si.is_snap  ? QStringLiteral("Steam (Snap)")
                                       : QStringLiteral("Steam");
        if (kg) {
          g.my_games_folder     = kg->my_games_folder ? QString::fromLatin1(kg->my_games_folder) : QString();
          g.appdata_local_folder = kg->appdata_local_folder ? QString::fromLatin1(kg->appdata_local_folder) : QString();
          g.appdata_roaming_folder = kg->appdata_roaming_folder ? QString::fromLatin1(kg->appdata_roaming_folder) : QString();
          g.registry_path  = QString::fromLatin1(kg->registry_path);
          g.registry_value = QString::fromLatin1(kg->registry_value);
        }
        games.append(g);
      }
    }
  }

  MOBase::log::info("Steam: Found {} installed games", games.size());
  return games;
}

// ============================================================================
// Heroic game detection (GOG + Epic)
// ============================================================================

/// Get the Wine prefix for a Heroic game from its GamesConfig JSON.
QString getHeroicGamePrefix(const QString& heroicPath, const QString& appName)
{
  QFile f(heroicPath + "/GamesConfig/" + appName + ".json");
  if (!f.open(QIODevice::ReadOnly))
    return {};

  QJsonDocument const doc = QJsonDocument::fromJson(f.readAll());
  QJsonObject root  = doc.object();

  // Try direct or nested under appName.
  QString prefix;
  if (root.contains(QStringLiteral("winePrefix"))) {
    prefix = root[QStringLiteral("winePrefix")].toString();
  } else if (root.contains(appName)) {
    prefix = root[appName].toObject()[QStringLiteral("winePrefix")].toString();
  }
  return (!prefix.isEmpty() && QFileInfo::exists(prefix)) ? prefix : QString();
}

QVector<DetectedGame> detectHeroicGames()
{
  QVector<DetectedGame> games;
  const QString home = QDir::homePath();

  static const char* HEROIC_PATHS[] = {
      ".config/heroic",
      ".var/app/com.heroicgameslauncher.hgl/config/heroic",
  };

  for (const char* rel : HEROIC_PATHS) {
    const QString heroicPath = QDir(home).filePath(QString::fromLatin1(rel));
    if (!QFileInfo::exists(heroicPath))
      continue;

    // --- GOG ---
    {
      QFile f(heroicPath + "/gog_store/installed.json");
      if (f.open(QIODevice::ReadOnly)) {
        QJsonDocument const doc = QJsonDocument::fromJson(f.readAll());

        QJsonArray installed;
        if (doc.isObject() && doc.object().contains(QStringLiteral("installed")))
          installed = doc.object()[QStringLiteral("installed")].toArray();
        else if (doc.isArray())
          installed = doc.array();

        for (const QJsonValue& v : installed) {
          QJsonObject obj = v.toObject();
          if (obj[QStringLiteral("platform")].toString() != QStringLiteral("windows"))
            continue;

          const QString appName     = obj[QStringLiteral("appName")].toString();
          const QString installPath = obj[QStringLiteral("install_path")].toString();
          if (appName.isEmpty() || installPath.isEmpty() || !QFileInfo::exists(installPath))
            continue;

          const KnownGame* kg = findKnownGameByGogId(appName);

          DetectedGame g;
          g.name         = obj[QStringLiteral("title")].toString(appName);
          g.app_id       = appName;
          g.install_path = installPath;
          g.prefix_path  = getHeroicGamePrefix(heroicPath, appName);
          g.launcher     = QStringLiteral("Heroic (GOG)");
          if (kg) {
            g.my_games_folder        = kg->my_games_folder ? QString::fromLatin1(kg->my_games_folder) : QString();
            g.appdata_local_folder   = kg->appdata_local_folder ? QString::fromLatin1(kg->appdata_local_folder) : QString();
            g.appdata_roaming_folder = kg->appdata_roaming_folder ? QString::fromLatin1(kg->appdata_roaming_folder) : QString();
            g.registry_path  = QString::fromLatin1(kg->registry_path);
            g.registry_value = QString::fromLatin1(kg->registry_value);
          }
          games.append(g);
        }
      }
    }

    // --- Epic ---
    {
      // installed.json is authoritative for installation state and paths;
      // Heroic's cache enriches those entries with namespace and title data.
      auto parseFile = [&](const QString& relativePath) {
        QFile file(heroicPath + relativePath);
        if (!file.open(QIODevice::ReadOnly)) {
          return QVector<HeroicEpicInstall>{};
        }
        return parseHeroicEpicInstalls(file.readAll());
      };

      const QVector<HeroicEpicInstall> installedManifest = parseFile(
          QStringLiteral("/legendaryConfig/legendary/installed.json"));
      const QVector<HeroicEpicInstall> libraryCache =
          parseFile(QStringLiteral("/store_cache/legendary_library.json"));
      const QVector<HeroicEpicInstall> installs =
          mergeHeroicEpicInstalls(installedManifest, libraryCache);

      for (const HeroicEpicInstall& install : installs) {
        if (!install.is_installed || install.is_dlc ||
            install.platform.compare(QStringLiteral("windows"),
                                     Qt::CaseInsensitive) != 0 ||
            install.install_path.isEmpty() ||
            !QFileInfo::exists(install.install_path)) {
          continue;
        }

        const QString epicId = install.namespace_id.isEmpty()
                                   ? install.app_name
                                   : install.namespace_id;
        const KnownGame* kg = findKnownGameByEpicId(epicId);
        if (!kg && epicId != install.app_name) {
          kg = findKnownGameByEpicId(install.app_name);
        }
        if (!kg) {
          kg = findKnownGameByTitle(install.title);
        }

        DetectedGame g;
        g.name         = install.title;
        g.app_id       = install.app_name;
        g.install_path = install.install_path;
        g.prefix_path  = getHeroicGamePrefix(heroicPath, install.app_name);
        g.launcher     = QStringLiteral("Heroic (Epic)");
        if (kg) {
          g.my_games_folder = kg->my_games_folder
                                  ? QString::fromLatin1(kg->my_games_folder)
                                  : QString();
          g.appdata_local_folder =
              kg->appdata_local_folder
                  ? QString::fromLatin1(kg->appdata_local_folder)
                  : QString();
          g.appdata_roaming_folder =
              kg->appdata_roaming_folder
                  ? QString::fromLatin1(kg->appdata_roaming_folder)
                  : QString();
          g.registry_path  = QString::fromLatin1(kg->registry_path);
          g.registry_value = QString::fromLatin1(kg->registry_value);
        }
        games.append(g);
      }
    }
  }

  MOBase::log::info("Heroic: Found {} installed games", games.size());
  return games;
}

// ============================================================================
// Bottles game detection
// ============================================================================

QVector<DetectedGame> detectBottlesGames()
{
  QVector<DetectedGame> games;
  const QString home = QDir::homePath();

  static const char* BOTTLES_PATHS[] = {
      ".local/share/bottles/bottles",
      ".var/app/com.usebottles.bottles/data/bottles/bottles",
  };

  for (const char* rel : BOTTLES_PATHS) {
    const QString bottlesPath = QDir(home).filePath(QString::fromLatin1(rel));
    if (!QFileInfo::exists(bottlesPath))
      continue;

    QDir const dir(bottlesPath);
    for (const QString& bottleName :
         dir.entryList(QDir::Dirs | QDir::NoDotAndDotDot)) {
      const QString bottlePath = dir.absoluteFilePath(bottleName);
      const QString driveC     = bottlePath + "/drive_c";
      if (!QFileInfo::exists(driveC))
        continue;

      for (int i = 0; i < KNOWN_GAMES_COUNT; ++i) {
        const KnownGame& kg = KNOWN_GAMES[i];
        const QString val   = readRegistryValue(
            bottlePath, QString::fromLatin1(kg.registry_path),
            QString::fromLatin1(kg.registry_value));
        if (val.isEmpty())
          continue;

        QString installPath = winePathToLinux(val);
        if (installPath.isEmpty()) {
          // Fallback for C: paths.
          if (val.startsWith(QStringLiteral("C:"), Qt::CaseInsensitive) ||
              val.startsWith(QStringLiteral("c:"), Qt::CaseInsensitive)) {
            QString relative = val.mid(2).replace('\\', '/');
            if (relative.startsWith('/'))
              relative = relative.mid(1);
            installPath = driveC + "/" + relative;
          } else {
            continue;
          }
        }

        if (!QFileInfo::exists(installPath))
          continue;

        DetectedGame g;
        g.name         = QString::fromLatin1(kg.name);
        g.app_id       = QStringLiteral("bottles-%1").arg(kg.steam_app_id);
        g.install_path = installPath;
        g.prefix_path  = bottlePath;
        g.launcher     = QStringLiteral("Bottles");
        g.my_games_folder        = kg.my_games_folder ? QString::fromLatin1(kg.my_games_folder) : QString();
        g.appdata_local_folder   = kg.appdata_local_folder ? QString::fromLatin1(kg.appdata_local_folder) : QString();
        g.appdata_roaming_folder = kg.appdata_roaming_folder ? QString::fromLatin1(kg.appdata_roaming_folder) : QString();
        g.registry_path  = QString::fromLatin1(kg.registry_path);
        g.registry_value = QString::fromLatin1(kg.registry_value);
        games.append(g);
      }
    }
  }

  MOBase::log::info("Bottles: Found {} installed games", games.size());
  return games;
}

}  // namespace

// ============================================================================
// Public API
// ============================================================================

GameScanResult detectAllGames()
{
  // Cache the result — game plugins call this once each during identifyGamePath().
  static std::optional<GameScanResult> cache;
  if (cache.has_value())
    return *cache;

  GameScanResult result;

  auto steam = detectSteamGames();
  result.steam_count = steam.size();
  result.games.append(steam);

  auto heroic = detectHeroicGames();
  result.heroic_count = heroic.size();
  result.games.append(heroic);

  auto bottles = detectBottlesGames();
  result.bottles_count = bottles.size();
  result.games.append(bottles);

  // Deduplicate by registry_path (keep first = highest priority).
  QSet<QString> seen;
  result.games.erase(
      std::remove_if(result.games.begin(), result.games.end(),
                     [&seen](const DetectedGame& g) {
                       if (g.registry_path.isEmpty())
                         return false;
                       if (seen.contains(g.registry_path))
                         return true;
                       seen.insert(g.registry_path);
                       return false;
                     }),
      result.games.end());

  cache = result;
  return result;
}
