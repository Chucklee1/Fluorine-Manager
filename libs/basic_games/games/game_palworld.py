from pathlib import Path

from PyQt6.QtCore import QDir

import mobase

from ..basic_features.basic_save_game_info import (
    BasicGameSaveGame,
    BasicGameSaveGameInfo,
)
from ..basic_game import BasicGame


class PalworldGame(BasicGame):
    Name = "Palworld Support Plugin"
    Author = "WickedSik"
    Version = "0.7.0"
    Description = "Palworld installer with support for multi-platform packages"

    GameName = "Palworld"
    GameShortName = "palworld"
    GameNexusName = "palworld"
    GameNexusId = 658
    GameSteamId = 1623730

    # Preserve the on-disk spelling: unlike Windows, Linux path lookups are
    # case-sensitive, and the Steam installation contains Palworld.exe.
    GameBinary = "Palworld.exe"
    GameDataPath = "Pal"
    GameSaveExtension = "sav"
    GameDocumentsDirectory = (
        "%USERPROFILE%/AppData/Local/Pal/Saved/Config/Windows"
    )
    GameSavesDirectory = "%USERPROFILE%/AppData/Local/Pal/Saved/SaveGames"

    def init(self, organizer: mobase.IOrganizer) -> bool:
        if not super().init(organizer):
            return False

        self._register_feature(
            BasicGameSaveGameInfo(lambda save: Path(save or "", "Level.sav"))
        )
        return True

    def listSaves(self, folder: QDir) -> list[mobase.ISaveGame]:
        saves_root = Path(folder.absolutePath())
        if not saves_root.is_dir():
            return []

        return [
            BasicGameSaveGame(world_directory)
            for user_directory in saves_root.iterdir()
            if user_directory.is_dir()
            for world_directory in user_directory.iterdir()
            if world_directory.is_dir()
            and (world_directory / "Level.sav").is_file()
        ]
