#include "gmock/gmock.h"
#include "gtest/gtest.h"

#include "pythonrunner.h"

#include <QCoreApplication>

#include <uibase/iplugingame.h>

#include "MockOrganizer.h"

using namespace MOBase;

TEST(IPluginGame, Simple)
{
    const auto plugins_folder = QString(std::getenv("PLUGIN_DIR"));

    auto runner = mo2::python::createPythonRunner();
    runner->initialize();

    // load objects
    const auto objects = runner->load(plugins_folder + "/dummy-game.py");
    ASSERT_EQ(objects.size(), 2);

    // Python overrides are exposed through the optional policy interface and
    // reached through the ABI-safe IPluginGame facade.
    IPluginGame* plugin = qobject_cast<IPluginGame*>(objects[0]);
    ASSERT_NE(plugin, nullptr);
    IPluginGamePolicies* policies =
        qobject_cast<IPluginGamePolicies*>(objects[0]);
    ASSERT_NE(policies, nullptr);
    EXPECT_EQ(policies->ignoredPluginFileSuffixes(),
              QStringList({QStringLiteral(".wrapper.esp")}));
    EXPECT_EQ(plugin->ignoredPluginFileSuffixes(),
              QStringList({QStringLiteral(".wrapper.esp")}));
    EXPECT_FALSE(plugin->genericPluginStateFollowsModState());
    EXPECT_TRUE(plugin->parsePluginHeader(QStringLiteral("example.esp")));
    EXPECT_FALSE(plugin->parsePluginHeader(QStringLiteral("skip.omwscripts")));
    EXPECT_FALSE(plugin->enforcePluginRelationships());

    // A Python game that does not override the policy methods gets the same
    // classic defaults as a native PluginGame/2.0 object without the capability.
    IPluginGame* defaultPlugin = qobject_cast<IPluginGame*>(objects[1]);
    ASSERT_NE(defaultPlugin, nullptr);
    EXPECT_TRUE(defaultPlugin->ignoredPluginFileSuffixes().isEmpty());
    EXPECT_TRUE(defaultPlugin->genericPluginStateFollowsModState());
    EXPECT_TRUE(defaultPlugin->parsePluginHeader(QStringLiteral("example.esp")));
    EXPECT_TRUE(defaultPlugin->enforcePluginRelationships());
}
