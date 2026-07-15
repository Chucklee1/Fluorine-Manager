#include <gtest/gtest.h>

#include "plugincompatibility.h"

namespace
{

struct FakePlugin
{
  QString name;
  FakePlugin* master{nullptr};
};

std::optional<PluginCompatibility::Block> blocked(FakePlugin* plugin)
{
  return PluginCompatibility::blockedRuleForPlugin(
      QStringLiteral("Morrowind (OpenMW)"), plugin,
      [](FakePlugin* current) { return current->name; },
      [](FakePlugin* current) { return current->master; });
}

}  // namespace

TEST(PluginCompatibility, BlocksOpenMWPlayerForNativeOpenMW)
{
  const auto block = PluginCompatibility::blockedRule(
      QStringLiteral("Morrowind (OpenMW)"), {QStringLiteral("OpenMWPlayer")});

  ASSERT_TRUE(block.has_value());
  EXPECT_EQ(block->id, QStringLiteral("openmwplayer-native-openmw"));
}

TEST(PluginCompatibility, BlocksDescendantsByMasterAncestry)
{
  EXPECT_TRUE(PluginCompatibility::blockedRule(
                  QStringLiteral("Morrowind (OpenMW)"),
                  {QStringLiteral("OpenMWPlayer Launcher"),
                   QStringLiteral("OpenMWPlayer")})
                  .has_value());
}

TEST(PluginCompatibility, TraversesMasterAncestryAndStopsAtCycles)
{
  FakePlugin root{QStringLiteral("OpenMWPlayer")};
  FakePlugin child{QStringLiteral("OpenMWPlayer Launcher"), &root};
  FakePlugin grandchild{QStringLiteral("OpenMWPlayer Child Tool"), &child};

  EXPECT_TRUE(blocked(&grandchild).has_value());

  root.master = &grandchild;
  EXPECT_TRUE(blocked(&grandchild).has_value());
}

TEST(PluginCompatibility, AllowsClassicMorrowindAndOtherPlugins)
{
  EXPECT_FALSE(PluginCompatibility::blockedRule(
                   QStringLiteral("Morrowind"), {QStringLiteral("OpenMWPlayer")})
                   .has_value());
  EXPECT_FALSE(PluginCompatibility::blockedRule(
                   QStringLiteral("Morrowind (OpenMW)"),
                   {QStringLiteral("Unrelated Plugin")})
                   .has_value());
  EXPECT_FALSE(PluginCompatibility::blockedRule(
                   QStringLiteral("morrowind (openmw)"),
                   {QStringLiteral("OpenMWPlayer")})
                   .has_value());
}

TEST(PluginCompatibility, SessionOverrideAllowsBlockedRule)
{
  EXPECT_FALSE(PluginCompatibility::blockedRule(
                   QStringLiteral("Morrowind (OpenMW)"),
                   {QStringLiteral("OpenMWPlayer")},
                   {QStringLiteral("openmwplayer-native-openmw")})
                   .has_value());
}

TEST(PluginCompatibility, ReadsSessionOverridesFromEnvironment)
{
  const auto variable = QByteArrayLiteral("FLUORINE_ALLOW_INCOMPATIBLE_PLUGINS");
  const auto original = qgetenv(variable.constData());
  qputenv(variable.constData(),
          QByteArrayLiteral("other-rule, openmwplayer-native-openmw"));

  const auto overrides = PluginCompatibility::environmentOverrides();

  if (original.isNull()) {
    qunsetenv(variable.constData());
  } else {
    qputenv(variable.constData(), original);
  }
  EXPECT_TRUE(overrides.contains(QStringLiteral("other-rule")));
  EXPECT_TRUE(overrides.contains(QStringLiteral("openmwplayer-native-openmw")));
}
