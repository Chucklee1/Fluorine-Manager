#include "heroicjson.h"

#include <gtest/gtest.h>

TEST(HeroicJson, ParsesModernLibraryCache)
{
  const QByteArray json = R"json(
    {
      "library": [
        {
          "app_name": "Ginger",
          "namespace": "77f2b98e2cef40c8a7437518bf420e47",
          "title": "Cyberpunk 2077",
          "is_installed": true,
          "install": {
            "install_path": "/games/Cyberpunk2077",
            "platform": "Windows",
            "is_dlc": false
          }
        },
        {
          "app_name": "NotInstalled",
          "title": "Not Installed",
          "is_installed": false,
          "install": {
            "install_path": "/games/not-installed",
            "platform": "Windows"
          }
        }
      ]
    }
  )json";

  const QVector<HeroicEpicInstall> installs = parseHeroicEpicInstalls(json);

  ASSERT_EQ(installs.size(), 2);
  EXPECT_EQ(installs[0].app_name, QStringLiteral("Ginger"));
  EXPECT_EQ(installs[0].namespace_id,
            QStringLiteral("77f2b98e2cef40c8a7437518bf420e47"));
  EXPECT_EQ(installs[0].title, QStringLiteral("Cyberpunk 2077"));
  EXPECT_EQ(installs[0].install_path, QStringLiteral("/games/Cyberpunk2077"));
  EXPECT_EQ(installs[0].platform, QStringLiteral("Windows"));
  EXPECT_TRUE(installs[0].is_installed);
  EXPECT_FALSE(installs[0].is_dlc);
  EXPECT_FALSE(installs[1].is_installed);
}

TEST(HeroicJson, ParsesDlcFlagFromModernNestedInstall)
{
  const QByteArray json = R"json(
    {
      "library": [
        {
          "app_name": "CyberpunkDlc",
          "title": "Cyberpunk 2077: Phantom Liberty",
          "is_installed": true,
          "install": {
            "install_path": "/games/Cyberpunk2077",
            "platform": "Windows",
            "is_dlc": true
          }
        }
      ]
    }
  )json";

  const QVector<HeroicEpicInstall> installs = parseHeroicEpicInstalls(json);

  ASSERT_EQ(installs.size(), 1);
  EXPECT_TRUE(installs[0].is_dlc);
}

TEST(HeroicJson, InfersModernInstalledStateFromNestedInstallPath)
{
  const QByteArray json = R"json(
    {
      "library": [
        {
          "app_name": "Ginger",
          "install": {
            "install_path": "/games/Cyberpunk2077",
            "platform": "Windows"
          }
        },
        {
          "app_name": "LibraryOnly"
        }
      ]
    }
  )json";

  const QVector<HeroicEpicInstall> installs = parseHeroicEpicInstalls(json);

  ASSERT_EQ(installs.size(), 2);
  EXPECT_TRUE(installs[0].is_installed);
  EXPECT_FALSE(installs[1].is_installed);
}

TEST(HeroicJson, TreatsLegendaryInstalledEntriesAsInstalled)
{
  const QByteArray json = R"json(
    {
      "Ginger": {
        "app_name": "Ginger",
        "title": "Cyberpunk 2077",
        "install_path": "/games/Cyberpunk2077",
        "platform": "Windows",
        "is_dlc": true
      }
    }
  )json";

  const QVector<HeroicEpicInstall> installs = parseHeroicEpicInstalls(json);

  ASSERT_EQ(installs.size(), 1);
  EXPECT_EQ(installs[0].app_name, QStringLiteral("Ginger"));
  EXPECT_EQ(installs[0].install_path, QStringLiteral("/games/Cyberpunk2077"));
  EXPECT_EQ(installs[0].platform, QStringLiteral("Windows"));
  EXPECT_TRUE(installs[0].is_installed);
  EXPECT_TRUE(installs[0].is_dlc);
}

TEST(HeroicJson, UsesObjectKeyWhenLegendaryOmitsAppName)
{
  const QByteArray json = R"json(
    {
      "FallbackName": {
        "title": "Example",
        "install_path": "/games/example",
        "platform": "Windows"
      }
    }
  )json";

  const QVector<HeroicEpicInstall> installs = parseHeroicEpicInstalls(json);

  ASSERT_EQ(installs.size(), 1);
  EXPECT_EQ(installs[0].app_name, QStringLiteral("FallbackName"));
  EXPECT_TRUE(installs[0].is_installed);
}

TEST(HeroicJson, MergesCacheMetadataWithoutReplacingManifestPath)
{
  HeroicEpicInstall manifest;
  manifest.app_name     = QStringLiteral("Ginger");
  manifest.title        = QStringLiteral("Ginger");
  manifest.install_path = QStringLiteral("/games/current");
  manifest.platform     = QStringLiteral("Windows");
  manifest.is_installed = true;

  HeroicEpicInstall cached;
  cached.app_name     = QStringLiteral("Ginger");
  cached.namespace_id = QStringLiteral("77f2b98e2cef40c8a7437518bf420e47");
  cached.title        = QStringLiteral("Cyberpunk 2077");
  cached.install_path = QStringLiteral("/games/stale");
  cached.platform     = QStringLiteral("Windows");
  cached.is_installed = true;

  const QVector<HeroicEpicInstall> installs =
      mergeHeroicEpicInstalls({manifest}, {cached});

  ASSERT_EQ(installs.size(), 1);
  EXPECT_EQ(installs[0].install_path, QStringLiteral("/games/current"));
  EXPECT_EQ(installs[0].title, QStringLiteral("Cyberpunk 2077"));
  EXPECT_EQ(installs[0].namespace_id,
            QStringLiteral("77f2b98e2cef40c8a7437518bf420e47"));
}

TEST(HeroicJson, RejectsMalformedOrUnexpectedDocuments)
{
  EXPECT_TRUE(parseHeroicEpicInstalls("{").isEmpty());
  EXPECT_TRUE(parseHeroicEpicInstalls("[]").isEmpty());
}
