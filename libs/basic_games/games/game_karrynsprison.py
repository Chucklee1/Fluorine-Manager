from __future__ import annotations

import mobase

from ..basic_game import BasicGame


def _find_www(filetree: mobase.IFileTree) -> mobase.IFileTree | None:
    """Find the game-relative ``www`` directory in a packaged mod."""
    for entry in filetree:
        if not isinstance(entry, mobase.IFileTree):
            continue
        if entry.name().casefold() == "www":
            return entry
        if (found := _find_www(entry)) is not None:
            return found
    return None


def _find_metadata(filetree: mobase.IFileTree) -> mobase.FileTreeEntry | None:
    for entry in filetree:
        if entry.name().casefold() == "meta.ini" and entry.isFile():
            return entry
        if isinstance(entry, mobase.IFileTree):
            if (found := _find_metadata(entry)) is not None:
                return found
    return None


class KarrynsPrisonModDataChecker(mobase.ModDataChecker):
    """Accept GitGud packages and unwrap repository/source archives.

    Integrated Karryn's Prison mods preserve the game layout below a ``www``
    directory.  Release packages normally put it at archive root, while GitLab
    source archives add one or more wrapper directories.
    """

    def dataLooksValid(
        self, filetree: mobase.IFileTree
    ) -> mobase.ModDataChecker.CheckReturn:
        www = _find_www(filetree)
        if www is None:
            return mobase.ModDataChecker.INVALID
        if www.parent() is filetree:
            return mobase.ModDataChecker.VALID
        return mobase.ModDataChecker.FIXABLE

    def fix(self, filetree: mobase.IFileTree) -> mobase.IFileTree:
        www = _find_www(filetree)
        if www is None or www.parent() is filetree:
            return filetree

        metadata = _find_metadata(filetree)
        www.moveTo(filetree)
        if metadata is not None and metadata.parent() is not filetree:
            metadata.moveTo(filetree)
        return filetree


class KarrynsPrisonGame(BasicGame):
    Name = "Karryn's Prison Support Plugin"
    Author = "Fluorine contributors"
    Version = "1.0.0"

    GameName = "Karryn's Prison"
    GameShortName = "karrynsprison"
    GameValidShortNames = ["karryn", "karryns-prison"]
    GameSteamId = 1619750
    GameBinary = "nw.exe"
    # Mods contain paths relative to the game root, beginning with www/.
    GameDataPath = ""
    # RPG Maker MV stores its configuration and saves inside the game tree.
    GameDocumentsDirectory = "%GAME_PATH%/www"
    GameSavesDirectory = "%GAME_PATH%/www/save"
    GameSaveExtension = "rpgsave"
    GameSupportURL = "https://gitgud.io/karryn-prison-mods/modding-wiki/-/wikis/home"

    def init(self, organizer: mobase.IOrganizer) -> bool:
        super().init(organizer)
        self._register_feature(KarrynsPrisonModDataChecker())
        return True
