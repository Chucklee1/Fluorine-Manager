from __future__ import annotations

import ast
import unittest
from pathlib import Path


GAMES_DIRECTORY = Path(__file__).parents[2] / "libs" / "basic_games" / "games"


def class_constants(module_path: Path, class_name: str) -> dict[str, object]:
    module = ast.parse(module_path.read_text(encoding="utf-8"), module_path.name)

    game_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    constants: dict[str, object] = {}
    for statement in game_class.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            constants[target.id] = ast.literal_eval(statement.value)
        except ValueError:
            continue
    return constants


class PalworldGameMetadataTests(unittest.TestCase):
    def test_client_binary_preserves_linux_filename_case(self) -> None:
        constants = class_constants(
            GAMES_DIRECTORY / "game_palworld.py", "PalworldGame"
        )

        self.assertEqual(constants["GameBinary"], "Palworld.exe")

    def test_client_prefix_paths_are_host_resolvable(self) -> None:
        constants = class_constants(
            GAMES_DIRECTORY / "game_palworld.py", "PalworldGame"
        )

        self.assertEqual(
            constants["GameSavesDirectory"],
            "%USERPROFILE%/AppData/Local/Pal/Saved/SaveGames",
        )

    def test_server_binary_preserves_linux_filename_case(self) -> None:
        constants = class_constants(
            GAMES_DIRECTORY / "game_palworld_server.py", "PalworldServerGame"
        )

        self.assertEqual(constants["GameBinary"], "PalServer.exe")


if __name__ == "__main__":
    unittest.main()
