#include "nexuscollections.h"
#include "apiuseraccount.h"
#include "fluorinepaths.h"
#include "nexusinterface.h"
#include "nxmaccessmanager.h"
#include "settings.h"

#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QProcess>
#include <QStandardPaths>
#include <QUrl>
#include <log.h>

static const char* GRAPHQL_URL = "https://api.nexusmods.com/v2/graphql";
static const char* REST_V1_URL = "https://api.nexusmods.com/v1";

// ─── Game name ↔ Nexus domain ─────────────────────────────────────────────

static const std::pair<const char*, const char*> DOMAIN_MAP[] = {
    {"Enderal",                  "enderal"},
    {"Enderal Special Edition",  "enderalspecialedition"},
    {"Fallout 3",                "fallout3"},
    {"Fallout 4",                "fallout4"},
    {"Fallout 4 VR",             "fallout4"},
    {"Fallout New Vegas",        "newvegas"},
    {"Morrowind",                "morrowind"},
    {"Oblivion",                 "oblivion"},
    {"Skyrim",                   "skyrim"},
    {"Skyrim Special Edition",   "skyrimspecialedition"},
    {"Skyrim VR",                "skyrimspecialedition"},
    {"Starfield",                "starfield"},
    {"The Witcher 3",            "witcher3"},
    {"Cyberpunk 2077",           "cyberpunk2077"},
    {"Baldur's Gate 3",          "baldursgate3"},
};

// Steam App ID → Nexus domain.  Covers full Steam titles that don't match the
// short names in DOMAIN_MAP (e.g. "The Elder Scrolls V: Skyrim Special Edition").
static const std::pair<const char*, const char*> STEAM_ID_MAP[] = {
    {"489830",  "skyrimspecialedition"},
    {"72850",   "skyrim"},
    {"22320",   "morrowind"},
    {"22330",   "oblivion"},
    {"900883",  "oblivion"},         // Oblivion Remastered
    {"22300",   "fallout3"},
    {"22380",   "newvegas"},
    {"377160",  "fallout4"},
    {"1716740", "starfield"},
    {"1086940", "baldursgate3"},
    {"1091500", "cyberpunk2077"},
    {"499430",  "witcher3"},
    {"976620",  "enderalspecialedition"},
    {"1252570", "enderal"},
};

QString NexusCollections::domainForSteamAppId(const QString& appId)
{
  for (auto& [id, domain] : STEAM_ID_MAP) {
    if (appId == QLatin1String(id))
      return QLatin1String(domain);
  }
  return {};
}

QString NexusCollections::domainForGameName(const QString& gameName)
{
  for (auto& [name, domain] : DOMAIN_MAP) {
    if (gameName.compare(QLatin1String(name), Qt::CaseInsensitive) == 0)
      return QLatin1String(domain);
  }
  return {};
}

QString NexusCollections::gameNameForDomain(const QString& domain)
{
  for (auto& [name, d] : DOMAIN_MAP) {
    if (domain.compare(QLatin1String(d), Qt::CaseInsensitive) == 0)
      return QLatin1String(name);
  }
  return domain;
}

// ─── Ctor ─────────────────────────────────────────────────────────────────

NexusCollections::NexusCollections(QObject* parent)
    : QObject(parent)
{
}

// ─── 7z helpers ───────────────────────────────────────────────────────────

QString NexusCollections::find7z()
{
  const QString bundled = fluorineDataDir() + "/bin/7zz";
  if (QFile::exists(bundled))
    return bundled;

  for (const QString& name : {QStringLiteral("7z"), QStringLiteral("7za"),
                               QStringLiteral("7zz")}) {
    const QString found = QStandardPaths::findExecutable(name);
    if (!found.isEmpty())
      return found;
  }
  return {};
}

bool NexusCollections::extract7z(const QString& archivePath, const QString& destDir)
{
  const QString bin = find7z();
  if (bin.isEmpty()) {
    MOBase::log::error("[collections] 7z binary not found");
    return false;
  }

  QDir().mkpath(destDir);
  QProcess proc;
  proc.start(bin, {"x", "-y", "-o" + destDir, archivePath});
  proc.waitForFinished(5 * 60 * 1000);
  return proc.exitCode() == 0;
}

// ─── Auth check ───────────────────────────────────────────────────────────

void NexusCollections::checkAuth()
{
  NXMAccessManager* am = NexusInterface::instance().getAccessManager();

  // Try OAuth bearer token first via the userinfo endpoint.
  auto* oauthReply = am ? am->makeOAuthGetRequest(
      QUrl("https://users.nexusmods.com/oauth/userinfo")) : nullptr;
  if (oauthReply) {
    connect(oauthReply, &QNetworkReply::finished, this, [this, oauthReply]() {
      oauthReply->deleteLater();
      if (oauthReply->error() != QNetworkReply::NoError) {
        emit validateError(oauthReply->errorString());
        return;
      }
      const QJsonObject obj = QJsonDocument::fromJson(oauthReply->readAll()).object();
      const QString name    = obj.value("name").toString();
      const QJsonArray groups = obj.value("groups").toArray();
      bool premium = false;
      for (const QJsonValue& g : groups) {
        const QString role = g.toString();
        if (role == "premium" || role == "lifetimepremium") {
          premium = true;
          break;
        }
      }
      // Also cross-check the cached account type (populated after full validation).
      if (!premium && NexusInterface::instance().getAPIUserAccount().type()
                          == APIUserAccountTypes::Premium) {
        premium = true;
      }
      emit validateReady(name, premium);
    });
    return;
  }

  // Fallback: legacy API key from settings.
  NexusOAuthTokens tokens;
  GlobalSettings::nexusOAuthTokens(tokens);
  if (tokens.apiKey.isEmpty()) {
    emit validateError(
        "No Nexus credentials found. Please connect your Nexus account in "
        "Settings \342\206\222 Nexus.");
    return;
  }

  QNetworkRequest req(QUrl(QLatin1String(REST_V1_URL) + "/users/validate.json"));
  req.setRawHeader("APIKEY", tokens.apiKey.toUtf8());
  req.setRawHeader("Application-Name", "MO2");
  req.setRawHeader("Application-Version", "0.3.0");
  req.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");

  auto* legacyReply = m_nam.get(req);
  connect(legacyReply, &QNetworkReply::finished, this, [this, legacyReply]() {
    legacyReply->deleteLater();
    if (legacyReply->error() != QNetworkReply::NoError) {
      emit validateError(legacyReply->errorString());
      return;
    }
    const QJsonObject obj = QJsonDocument::fromJson(legacyReply->readAll()).object();
    const QString name    = obj.value("name").toString();
    const bool premium    = obj.value("is_premium").toBool()
                         || obj.value("is_premium+").toBool();
    emit validateReady(name, premium);
  });
}

// ─── Gallery ──────────────────────────────────────────────────────────────

void NexusCollections::fetchGallery(const QString& gameDomain,
                                    SortBy sort,
                                    int offset,
                                    int count)
{
  const char* sortField = (sort == SortBy::Downloads) ? "downloads"
                        : (sort == SortBy::Recent)    ? "createdAt"
                                                      : "endorsements";

  QJsonObject variables;
  variables["count"]  = count;
  variables["offset"] = offset;

  QJsonArray statusFilters;
  {
    QJsonObject fListed; fListed["op"] = "EQUALS"; fListed["value"] = "listed";
    QJsonObject fPub;    fPub["op"]    = "EQUALS"; fPub["value"]    = "published";
    statusFilters.append(fListed);
    statusFilters.append(fPub);
  }
  QJsonObject filter;
  filter["op"]               = "AND";
  filter["collectionStatus"] = statusFilters;
  if (!gameDomain.isEmpty()) {
    QJsonObject gd; gd["op"] = "EQUALS"; gd["value"] = gameDomain;
    filter["gameDomain"] = QJsonArray{gd};
  }
  variables["filter"] = filter;

  QJsonObject sortObj;
  {
    QJsonObject dir; dir["direction"] = "DESC";
    sortObj[sortField] = dir;
  }
  variables["sort"] = sortObj;

  const QLatin1String query(R"(
    query CollectionsV2($count:Int,$offset:Int,$filter:CollectionsSearchFilter,$sort:[CollectionsSearchSort!]) {
      collectionsV2(count:$count,offset:$offset,filter:$filter,sort:$sort) {
        totalCount
        nodes {
          slug name summary endorsements totalDownloads adultContent
          tileImage { url }
          headerImage { url }
          user { name }
          game { domainName name }
          latestPublishedRevision { revisionNumber totalSize modCount }
        }
      }
    }
  )");

  QJsonObject body;
  body["query"]     = query;
  body["variables"] = variables;

  const QByteArray payload = QJsonDocument(body).toJson(QJsonDocument::Compact);

  NXMAccessManager* am = NexusInterface::instance().getAccessManager();
  auto* reply = am ? am->makeOAuthPostRequest(QUrl(QLatin1String(GRAPHQL_URL)), payload)
                   : nullptr;
  if (!reply) {
    emit galleryError(
        "Not authenticated. Please connect your Nexus account in Settings \342\206\222 Nexus.");
    return;
  }

  connect(reply, &QNetworkReply::finished, this, [this, reply, offset]() {
    reply->deleteLater();
    if (reply->error() != QNetworkReply::NoError) {
      emit galleryError(reply->errorString());
      return;
    }

    const QJsonObject root = QJsonDocument::fromJson(reply->readAll()).object();
    if (root.contains("errors")) {
      emit galleryError(
          QJsonDocument(root["errors"].toArray()).toJson(QJsonDocument::Compact));
      return;
    }

    const QJsonObject collectionsObj =
        root["data"].toObject()["collectionsV2"].toObject();
    const int totalCount = collectionsObj["totalCount"].toInt();
    const QJsonArray nodes = collectionsObj["nodes"].toArray();

    QVector<CollectionCard> cards;
    for (const QJsonValue& v : nodes) {
      const QJsonObject n = v.toObject();
      CollectionCard c;
      c.slug           = n["slug"].toString();
      c.name           = n["name"].toString();
      c.summary        = n["summary"].toString();
      c.endorsements   = static_cast<quint64>(n["endorsements"].toDouble());
      c.totalDownloads = static_cast<quint64>(n["totalDownloads"].toDouble());
      c.isAdult        = n["adultContent"].toBool();
      c.author         = n["user"].toObject()["name"].toString();

      const QJsonObject game = n["game"].toObject();
      c.gameDomain = game["domainName"].toString();
      c.gameName   = game["name"].toString();

      // tileImage.url is the full CDN URL; headerImage is a fallback.
      const QJsonObject tile = n["tileImage"].toObject();
      c.tileImageUrl = tile["url"].toString();
      if (c.tileImageUrl.isEmpty())
        c.tileImageUrl = n["headerImage"].toObject()["url"].toString();

      const QJsonObject rev = n["latestPublishedRevision"].toObject();
      c.latestRevision = static_cast<quint64>(rev["revisionNumber"].toDouble());
      c.totalSizeBytes = rev["totalSize"].toString("0").toULongLong();
      c.modCount       = static_cast<quint64>(rev["modCount"].toDouble());

      cards.append(c);
    }
    emit galleryReady(cards, offset, totalCount);
  });
}

// ─── Manifest — step 1: resolve download link via GraphQL ─────────────────

void NexusCollections::fetchManifest(const QString& slug,
                                     const QString& gameDomain,
                                     const QString& workDir,
                                     int revision)
{
  fetchManifestDownloadLink(slug, gameDomain, workDir, revision);
}

void NexusCollections::fetchManifestDownloadLink(const QString& slug,
                                                  const QString& /*gameDomain*/,
                                                  const QString& workDir,
                                                  int revision)
{
  const QLatin1String queryLatest(R"(
    query GetCollection($slug:String!) {
      collectionRevision(slug:$slug) {
        revisionNumber downloadLink collection { name }
      }
    }
  )");
  const QLatin1String queryPinned(R"(
    query GetRevision($slug:String!,$rev:Int!) {
      collectionRevision(slug:$slug,revisionNumber:$rev) {
        revisionNumber downloadLink collection { name }
      }
    }
  )");

  QJsonObject vars;
  vars["slug"] = slug;
  if (revision > 0)
    vars["rev"] = revision;

  QJsonObject body;
  body["query"]     = (revision > 0) ? queryPinned : queryLatest;
  body["variables"] = vars;

  const QByteArray payload = QJsonDocument(body).toJson(QJsonDocument::Compact);

  NXMAccessManager* am = NexusInterface::instance().getAccessManager();
  auto* reply = am ? am->makeOAuthPostRequest(QUrl(QLatin1String(GRAPHQL_URL)), payload)
                   : nullptr;
  if (!reply) {
    emit manifestError(
        "Not authenticated. Please connect your Nexus account in Settings \342\206\222 Nexus.");
    return;
  }

  connect(reply, &QNetworkReply::finished, this, [this, reply, slug, workDir]() {
    reply->deleteLater();
    if (reply->error() != QNetworkReply::NoError) {
      emit manifestError(reply->errorString());
      return;
    }

    const QJsonObject root = QJsonDocument::fromJson(reply->readAll()).object();
    if (root.contains("errors")) {
      emit manifestError(
          QJsonDocument(root["errors"].toArray()).toJson(QJsonDocument::Compact));
      return;
    }

    const QJsonObject rev =
        root["data"].toObject()["collectionRevision"].toObject();
    if (rev.isEmpty()) {
      emit manifestError(
          "No collection revision returned — may require premium or adult "
          "content setting on Nexus.");
      return;
    }

    QString dlLink = rev["downloadLink"].toString();
    if (dlLink.isEmpty()) {
      emit manifestError(
          "No download link in response — collection may require a Nexus "
          "Premium account.");
      return;
    }
    if (dlLink.startsWith('/'))
      dlLink.prepend(QStringLiteral("https://api.nexusmods.com"));

    fetchManifestCdnLink(dlLink, slug, workDir);
  });
}

// ─── Manifest — step 2: resolve CDN URL from Nexus download API ───────────

void NexusCollections::fetchManifestCdnLink(const QString& downloadApiUrl,
                                              const QString& slug,
                                              const QString& workDir)
{
  NXMAccessManager* am = NexusInterface::instance().getAccessManager();
  auto* reply = am ? am->makeOAuthGetRequest(QUrl(downloadApiUrl)) : nullptr;
  if (!reply) {
    emit manifestError("Failed to resolve manifest CDN link — not authenticated.");
    return;
  }

  connect(reply, &QNetworkReply::finished, this, [this, reply, slug, workDir]() {
    reply->deleteLater();
    if (reply->error() != QNetworkReply::NoError) {
      emit manifestError(reply->errorString());
      return;
    }

    const QJsonArray links =
        QJsonDocument::fromJson(reply->readAll())
            .object()["download_links"].toArray();
    if (links.isEmpty()) {
      emit manifestError("No CDN download links returned.");
      return;
    }
    const QString cdnUrl = links.first().toObject()["URI"].toString();
    if (cdnUrl.isEmpty()) {
      emit manifestError("Empty CDN URL.");
      return;
    }
    downloadAndExtractManifest(cdnUrl, slug, workDir);
  });
}

// ─── Manifest — step 3: download .7z and extract ──────────────────────────

void NexusCollections::downloadAndExtractManifest(const QString& downloadUrl,
                                                   const QString& slug,
                                                   const QString& workDir)
{
  const QUrl dlQUrl(downloadUrl);
  QNetworkRequest req(dlQUrl);
  req.setAttribute(QNetworkRequest::RedirectPolicyAttribute,
                   QNetworkRequest::NoLessSafeRedirectPolicy);
  auto* reply = m_nam.get(req);

  connect(reply, &QNetworkReply::downloadProgress, this,
      [this](qint64 recv, qint64 total) {
        emit manifestProgress(recv, total);
      });

  connect(reply, &QNetworkReply::finished, this,
      [this, reply, slug, workDir]() {
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError) {
          emit manifestError(reply->errorString());
          return;
        }

        const QString archivePath = workDir + "/" + slug + "_collection.7z";
        QFile f(archivePath);
        if (!f.open(QIODevice::WriteOnly)) {
          emit manifestError("Cannot write archive to " + archivePath);
          return;
        }
        f.write(reply->readAll());
        f.close();

        const QString extractDir = workDir + "/" + slug;
        if (!extract7z(archivePath, extractDir)) {
          emit manifestError("7z extraction failed for " + archivePath);
          QFile::remove(archivePath);
          return;
        }
        QFile::remove(archivePath);

        const QString jsonPath = extractDir + "/collection.json";
        if (!QFile::exists(jsonPath)) {
          emit manifestError(
              "collection.json not found after extraction from archive.");
          return;
        }
        emit manifestReady(jsonPath, extractDir);
      });
}
