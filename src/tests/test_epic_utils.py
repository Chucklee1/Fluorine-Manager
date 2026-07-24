from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

MODULE_PATH = Path(__file__).parents[2] / "libs" / "basic_games" / "epic_utils.py"
SPEC = importlib.util.spec_from_file_location("epic_utils", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {MODULE_PATH}")
epic_utils = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(epic_utils)


def write_game(
    config_path: Path,
    app_name: str,
    install_path: Path,
    namespace: str | None = None,
    is_dlc: bool = False,
    is_game: bool = True,
    has_presence_id: bool = False,
) -> None:
    legendary_path = config_path / "legendary"
    metadata_path = legendary_path / "metadata"
    metadata_path.mkdir(parents=True, exist_ok=True)

    installed_path = legendary_path / "installed.json"
    installed: dict[str, object] = (
        json.loads(installed_path.read_text(encoding="utf-8"))
        if installed_path.is_file()
        else {}
    )
    installed[app_name] = {
        "app_name": app_name,
        "install_path": str(install_path),
        "is_dlc": is_dlc,
    }
    installed_path.write_text(json.dumps(installed), encoding="utf-8")

    if namespace is not None:
        (metadata_path / f"{app_name}.json").write_text(
            json.dumps(
                {
                    "asset_infos": {"Windows": {"namespace": namespace}},
                    "metadata": {
                        "namespace": namespace,
                        "categories": [
                            {"path": "games" if is_game else "digitalextras"}
                        ],
                        "customAttributes": (
                            {"PresenceId": {"value": namespace}}
                            if has_presence_id
                            else {}
                        ),
                    },
                }
            ),
            encoding="utf-8",
        )


class FindLegendaryGamesTest(unittest.TestCase):
    def test_indexes_epic_namespace_from_heroic_metadata(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory)
            install_path = Path("/games/Cyberpunk2077")
            write_game(
                config_path,
                "Ginger",
                install_path,
                namespace="77f2b98e2cef40c8a7437518bf420e47",
            )

            games = dict(epic_utils.find_legendary_games(str(config_path)))

            self.assertEqual(games["Ginger"], install_path)
            self.assertEqual(games["77f2b98e2cef40c8a7437518bf420e47"], install_path)

    def test_keeps_app_name_mapping_when_metadata_is_invalid(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory)
            install_path = Path("/games/example")
            write_game(config_path, "Example", install_path)
            metadata_path = config_path / "legendary" / "metadata" / "Example.json"
            metadata_path.write_text("{", encoding="utf-8")

            games = dict(epic_utils.find_legendary_games(str(config_path)))

            self.assertEqual(games, {"Example": install_path})

    def test_does_not_index_dlc_namespace(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory)
            install_path = Path("/games/example-dlc")
            write_game(
                config_path,
                "ExampleDLC",
                install_path,
                namespace="example-namespace",
                is_dlc=True,
            )

            games = dict(epic_utils.find_legendary_games(str(config_path)))

            self.assertEqual(games, {"ExampleDLC": install_path})

    def test_namespace_does_not_override_primary_app_name(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory)
            primary_path = Path("/games/primary")
            write_game(config_path, "Primary", primary_path)
            write_game(
                config_path,
                "Other",
                Path("/games/other"),
                namespace="Primary",
            )

            games = dict(epic_utils.find_legendary_games(str(config_path)))

            self.assertEqual(games["Primary"], primary_path)

    def test_prefers_presence_id_with_shared_namespace(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory)
            game_path = Path("/games/main")
            write_game(
                config_path,
                "MainGame",
                game_path,
                namespace="shared-namespace",
                has_presence_id=True,
            )
            write_game(
                config_path,
                "BonusContent",
                Path("/games/bonus"),
                namespace="shared-namespace",
            )

            games = dict(epic_utils.find_legendary_games(str(config_path)))

            self.assertEqual(games["shared-namespace"], game_path)

    def test_skips_namespace_with_multiple_install_paths(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory)
            write_game(
                config_path,
                "First",
                Path("/games/first"),
                namespace="shared-namespace",
            )
            write_game(
                config_path,
                "Second",
                Path("/games/second"),
                namespace="shared-namespace",
            )

            games = dict(epic_utils.find_legendary_games(str(config_path)))

            self.assertNotIn("shared-namespace", games)


if __name__ == "__main__":
    unittest.main()
