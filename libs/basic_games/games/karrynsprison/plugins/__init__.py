import mobase

from .gitgud_mods import GitGudModsTool


def createPlugins() -> list[mobase.IPluginTool]:
    return [GitGudModsTool()]
