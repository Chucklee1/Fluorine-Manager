"""Auto-discovered IPluginTool entry point for the OpenMW support package.

basic_games' createPlugins() walks ``games/**/plugins/__init__.py`` and calls
the module-level ``createPlugins()`` found here, so the "Sort with LOOT" tool is
registered alongside the OpenMW game plugin without any extra wiring.
"""

import mobase

from .sort_with_loot import OpenMWSortWithLoot


def createPlugins() -> list[mobase.IPlugin]:
    return [OpenMWSortWithLoot()]
