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
            "platform": "Windows"
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
        "platform": "Windows"
      }
    }
  )json";

  const QVector<HeroicEpicInstall> installs = parseHeroicEpicInstalls(json);

  ASSERT_EQ(installs.size(), 1);
  EXPECT_EQ(installs[0].app_name, QStringLiteral("Ginger"));
  EXPECT_EQ(installs[0].install_path, QStringLiteral("/games/Cyberpunk2077"));
  EXPECT_EQ(installs[0].platform, QStringLiteral("Windows"));
  EXPECT_TRUE(installs[0].is_installed);
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

TEST(HeroicJson, RejectsMalformedOrUnexpectedDocuments)
{
  EXPECT_TRUE(parseHeroicEpicInstalls("{").isEmpty());
  EXPECT_TRUE(parseHeroicEpicInstalls("[]").isEmpty());
}
