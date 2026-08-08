import mobase

from .identity import PLUGIN_NAME


class SameNamedPlugin(mobase.IPlugin):
    def init(self, organizer: mobase.IOrganizer) -> bool:
        return True

    def author(self) -> str:
        return "Test"

    def name(self) -> str:
        return PLUGIN_NAME

    def description(self) -> str:
        return "Package-switch regression fixture"

    def version(self) -> mobase.VersionInfo:
        return mobase.VersionInfo("1.0.0")


def createPlugin() -> mobase.IPlugin:
    return SameNamedPlugin()
