# -*- encoding: utf-8 -*-
from __future__ import annotations

import itertools
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import cast

try:
    import winreg
except ImportError:
    winreg = None

ErrorList = list[tuple[str, Exception]]


def find_epic_games(
    errors: ErrorList | None = None,
) -> Iterable[tuple[str, Path]]:
    if winreg is None:
        return

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\Wow6432Node\Epic Games\EpicGamesLauncher",
        ) as key:
            epic_data_path, _ = winreg.QueryValueEx(key, "AppDataPath")
    except FileNotFoundError:
        epic_data_path = r"%ProgramData%\Epic\EpicGamesLauncher\Data"

    manifests_path = Path(os.path.expandvars(epic_data_path)).joinpath("Manifests")
    if manifests_path.exists():
        for manifest_file_path in manifests_path.glob("*.item"):
            try:
                with open(manifest_file_path, encoding="utf-8") as manifest_file:
                    manifest_file_data = json.load(manifest_file)
                yield (
                    manifest_file_data["AppName"],
                    Path(manifest_file_data["InstallLocation"]),
                )
            except (json.JSONDecodeError, KeyError) as e:
                error_message = (
                    f'Unable to parse Epic Games manifest file: "{manifest_file_path}"\n'
                    " Try to run the launcher recreate it."
                )
                print(
                    error_message,
                    e,
                    file=sys.stderr,
                )
                if errors is not None:
                    errors.append((error_message, e))


def find_legendary_games(
    config_path: str | None = None, errors: ErrorList | None = None
) -> Iterable[tuple[str, Path]]:
    # Based on legendary source:
    # https://github.com/derrod/legendary/blob/master/legendary/lfs/lgndry.py
    if config_path := config_path or os.environ.get("XDG_CONFIG_HOME"):
        legendary_config_path = Path(config_path, "legendary")
    else:
        legendary_config_path = Path("~/.config/legendary").expanduser()

    installed_path = legendary_config_path / "installed.json"
    if installed_path.exists():
        try:
            with open(installed_path, encoding="utf-8") as installed_file:
                installed_games = json.load(installed_file)
            primary_app_names: set[str] = set()
            namespace_paths: dict[str, set[Path]] = {}
            game_namespace_paths: dict[str, set[Path]] = {}
            presence_namespace_paths: dict[str, set[Path]] = {}
            for game in installed_games.values():
                app_name = game["app_name"]
                install_path = Path(game["install_path"])
                yield app_name, install_path

                # Plugins normally use Epic's namespace as GameEpicId, while
                # Legendary records installed games by their launch app name.
                # They are often identical, but games such as Cyberpunk 2077
                # use different values (77f2... and "Ginger", respectively).
                if not isinstance(app_name, str):
                    continue
                primary_app_names.add(app_name)
                if game.get("is_dlc"):
                    continue
                if Path(app_name).name != app_name:
                    continue

                metadata_path = legendary_config_path / "metadata" / f"{app_name}.json"
                if not metadata_path.is_file():
                    continue

                try:
                    with open(metadata_path, encoding="utf-8") as metadata_file:
                        game_metadata = json.load(metadata_file)

                    namespaces: set[str] = set()
                    is_game = False
                    presence_id: str | None = None
                    asset_infos: object = game_metadata.get("asset_infos")
                    if isinstance(asset_infos, dict):
                        for asset_info in cast(
                            dict[object, object], asset_infos
                        ).values():
                            if isinstance(asset_info, dict):
                                namespace = cast(dict[object, object], asset_info).get(
                                    "namespace"
                                )
                                if isinstance(namespace, str) and namespace:
                                    namespaces.add(namespace)

                    metadata: object = game_metadata.get("metadata")
                    if isinstance(metadata, dict):
                        metadata_dict = cast(dict[object, object], metadata)
                        namespace = metadata_dict.get("namespace")
                        if isinstance(namespace, str) and namespace:
                            namespaces.add(namespace)
                        categories = metadata_dict.get("categories")
                        if isinstance(categories, list):
                            is_game = any(
                                isinstance(category, dict)
                                and cast(dict[object, object], category).get("path")
                                == "games"
                                for category in cast(list[object], categories)
                            )
                        custom_attributes = metadata_dict.get("customAttributes")
                        if isinstance(custom_attributes, dict):
                            presence = cast(
                                dict[object, object], custom_attributes
                            ).get("PresenceId")
                            if isinstance(presence, dict):
                                value = cast(dict[object, object], presence).get(
                                    "value"
                                )
                                if isinstance(value, str) and value:
                                    presence_id = value

                    for namespace in namespaces:
                        namespace_paths.setdefault(namespace, set()).add(install_path)
                        if is_game:
                            game_namespace_paths.setdefault(namespace, set()).add(
                                install_path
                            )
                        if presence_id == namespace:
                            presence_namespace_paths.setdefault(namespace, set()).add(
                                install_path
                            )
                except (json.JSONDecodeError, AttributeError, OSError):
                    # The app-name mapping is still valid when optional cached
                    # metadata is missing or stale.
                    pass

            for namespace, install_paths in namespace_paths.items():
                # Never let a derived alias replace Legendary's authoritative
                # app-name mapping. PresenceId identifies the canonical entry
                # when extras share its namespace; the game category and unique
                # path remain fallbacks for metadata without that attribute.
                candidate_paths = presence_namespace_paths.get(
                    namespace,
                    game_namespace_paths.get(namespace, install_paths),
                )
                if namespace in primary_app_names or len(candidate_paths) != 1:
                    continue
                yield namespace, next(iter(candidate_paths))
        except (json.JSONDecodeError, AttributeError, KeyError) as e:
            error_message = (
                f'Unable to parse installed games from Legendary/Heroic launcher: "{installed_path}"\n'
                " Try to run the launcher to recrated the file."
            )
            print(
                error_message,
                e,
                file=sys.stderr,
            )
            if errors is not None:
                errors.append((error_message, e))


def find_heroic_games(errors: ErrorList | None = None):
    # Linux: Heroic stores config in ~/.config/heroic/ (or Flatpak equivalent).
    for candidate in (
        Path.home() / ".config" / "heroic" / "legendaryConfig",
        Path.home()
        / ".var"
        / "app"
        / "com.heroicgameslauncher.hgl"
        / "config"
        / "heroic"
        / "legendaryConfig",
    ):
        if candidate.is_dir():
            return find_legendary_games(str(candidate), errors)

    # Windows fallback.
    return find_legendary_games(
        os.path.expandvars(r"%AppData%\heroic\legendaryConfig"), errors
    )


def find_games(errors: ErrorList | None = None) -> dict[str, Path]:
    return dict(
        itertools.chain(
            find_epic_games(errors=errors),
            find_legendary_games(errors=errors),
            find_heroic_games(errors=errors),
        )
    )


if __name__ == "__main__":
    games = find_games()
    for k, v in games.items():
        print("Found game with id {} at {}.".format(k, v))
