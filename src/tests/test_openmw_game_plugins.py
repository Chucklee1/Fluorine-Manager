from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


_CRITICAL_MESSAGES: list[str] = []
_WARNING_MESSAGES: list[str] = []


class _FakeTimer:
    callbacks: list[object] = []

    @classmethod
    def singleShot(cls, delay: int, callback) -> None:  # noqa: ANN001
        cls.callbacks.append(callback)

    @classmethod
    def run_all(cls) -> None:
        while cls.callbacks:
            callback = cls.callbacks.pop(0)
            callback()


class _Signal:
    def connect(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        pass

    def emit(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        pass


class _QObject:
    def tr(self, text: str) -> str:
        return text

    def moveToThread(self, thread) -> None:  # noqa: ANN001
        pass


def _install_import_stubs() -> None:
    pyqt = sys.modules.setdefault("PyQt6", types.ModuleType("PyQt6"))
    qtcore = sys.modules.setdefault(
        "PyQt6.QtCore", types.ModuleType("PyQt6.QtCore")
    )
    qtcore.QTimer = _FakeTimer
    qtcore.QCoreApplication = SimpleNamespace(
        translate=lambda context, text: text
    )
    qtcore.QObject = _QObject
    qtcore.Qt = SimpleNamespace(
        WindowModality=SimpleNamespace(WindowModal=1),
        ConnectionType=SimpleNamespace(QueuedConnection=1),
    )
    qtcore.QThread = type("QThread", (), {})
    qtcore.pyqtSignal = lambda *args, **kwargs: _Signal()
    qtcore.qInfo = lambda *args, **kwargs: None
    qtcore.qCritical = lambda message: _CRITICAL_MESSAGES.append(str(message))
    qtcore.qWarning = lambda message: _WARNING_MESSAGES.append(str(message))
    pyqt.QtCore = qtcore
    qtwidgets = sys.modules.setdefault(
        "PyQt6.QtWidgets", types.ModuleType("PyQt6.QtWidgets")
    )
    qtwidgets.QMessageBox = type(
        "QMessageBox",
        (),
        {
            "Icon": SimpleNamespace(Warning=1, Information=2),
            "StandardButton": SimpleNamespace(Ok=1, Yes=2, No=4),
        },
    )
    qtwidgets.QProgressDialog = type("QProgressDialog", (), {})
    pyqt.QtWidgets = qtwidgets

    mobase = sys.modules.setdefault("mobase", types.ModuleType("mobase"))
    mobase.GamePlugins = type("GamePlugins", (), {})
    mobase.IPluginTool = type("IPluginTool", (), {})
    mobase.IPlugin = type("IPlugin", (), {})
    mobase.IOrganizer = object
    mobase.IPluginList = object
    mobase.PluginState = SimpleNamespace(ACTIVE=1, INACTIVE=0, MISSING=-1)
    mobase.ModState = SimpleNamespace(ACTIVE=1)
    mobase.VersionInfo = lambda *args: args
    mobase.PluginSetting = lambda *args: args


_install_import_stubs()
ROOT = Path(__file__).parents[2]
SUPPORT_DIR = ROOT / "libs/basic_games/games/openmw_support"
PACKAGE_NAME = "_openmw_game_plugins_tests"
PACKAGE = types.ModuleType(PACKAGE_NAME)
PACKAGE.__path__ = [str(SUPPORT_DIR)]
sys.modules[PACKAGE_NAME] = PACKAGE


def _load_module(name: str, path: Path):  # noqa: ANN001, ANN201
    qualified = f"{PACKAGE_NAME}.{name}"
    spec = importlib.util.spec_from_file_location(qualified, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


openmw_cfg = _load_module("openmw_cfg", SUPPORT_DIR / "openmw_cfg.py")
game_plugins = _load_module("game_plugins", SUPPORT_DIR / "game_plugins.py")


class _FakePluginList:
    def __init__(
        self,
        names: list[str],
        *,
        active: tuple[str, ...] = (),
    ) -> None:
        self._names = list(names)
        self._order = list(names)
        active_keys = {name.casefold() for name in active}
        self._states = {
            name.casefold(): (
                sys.modules["mobase"].PluginState.ACTIVE
                if name.casefold() in active_keys
                else sys.modules["mobase"].PluginState.INACTIVE
            )
            for name in names
        }
        self.fail_set_state_for: str | None = None

    def pluginNames(self) -> list[str]:
        return list(self._names)

    def priority(self, name: str) -> int:
        key = name.casefold()
        return next(
            index
            for index, candidate in enumerate(self._order)
            if candidate.casefold() == key
        )

    def state(self, name: str):  # noqa: ANN201
        return self._states[name.casefold()]

    def setLoadOrder(self, order: list[str]) -> None:
        if {name.casefold() for name in order} != {
            name.casefold() for name in self._names
        }:
            raise ValueError("load order does not cover the fake inventory")
        by_key = {name.casefold(): name for name in self._names}
        self._order = [by_key[name.casefold()] for name in order]

    def setState(self, name: str, state: object) -> None:
        if (
            self.fail_set_state_for is not None
            and name.casefold() == self.fail_set_state_for.casefold()
        ):
            self.fail_set_state_for = None
            raise OSError("injected UI state failure")
        self._states[name.casefold()] = state

    def reorder(self, order: list[str]) -> None:
        self.setLoadOrder(order)

    def set_active(self, name: str, active: bool) -> None:
        state = (
            sys.modules["mobase"].PluginState.ACTIVE
            if active
            else sys.modules["mobase"].PluginState.INACTIVE
        )
        self.setState(name, state)

    def add(self, name: str, *, active: bool = False) -> None:
        self._names.append(name)
        self._order.append(name)
        self._states[name.casefold()] = (
            sys.modules["mobase"].PluginState.ACTIVE
            if active
            else sys.modules["mobase"].PluginState.INACTIVE
        )

    @property
    def order(self) -> list[str]:
        return list(self._order)

    @property
    def active_names(self) -> list[str]:
        active = sys.modules["mobase"].PluginState.ACTIVE
        return [name for name in self._order if self.state(name) == active]


class _Organizer:
    def __init__(
        self,
        directory: Path,
        primary: tuple[str, ...] = ("Morrowind.esm",),
        game_directory: Path | None = None,
    ):
        self._profile = SimpleNamespace(
            absolutePath=lambda: str(directory),
            localSettingsEnabled=lambda: True,
        )
        self._game = SimpleNamespace(
            primaryPlugins=lambda: list(primary),
            gameDirectory=lambda: SimpleNamespace(
                absolutePath=lambda: str(game_directory or directory / "game")
            ),
        )
        self._executables: list[object] = []

    def profile(self):  # noqa: ANN201
        return self._profile

    def managedGame(self):  # noqa: ANN201
        return self._game

    def executablesList(self):  # noqa: ANN201
        return SimpleNamespace(executables=lambda: iter(self._executables))


def _state(
    order: list[str],
    enabled: list[str],
    *,
    groundcover: list[str] | None = None,
) -> dict:
    return {
        "version": 3,
        "plugin_order": list(order),
        "enabled_plugins": list(enabled),
        "groundcover": list(groundcover or []),
        "known_archives": ["Morrowind.bsa"],
        "archives": ["Morrowind.bsa"],
        "profile_config_entries": [],
        "profile_config_entries_known": True,
        "profile_config_terminal": False,
        "content_migration_source": "test",
        "groundcover_migration_source": "test",
        "archive_migration_source": "test",
        "order_migration_source": "test",
        "plugin_state_migrated": True,
    }


def _write_state(directory: Path, state: dict) -> None:
    openmw_cfg.write_selection_state(
        directory / "fluorine-openmw-selection.json", state
    )


def _projection(path: Path) -> list[str]:
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]


class OpenMWGamePluginsTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeTimer.callbacks.clear()
        _CRITICAL_MESSAGES.clear()
        _WARNING_MESSAGES.clear()
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.organizer = _Organizer(self.directory)
        self.adapter = game_plugins.OpenMWGamePlugins(self.organizer)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_hydrates_from_migration_and_writes_exact_projections(self) -> None:
        (self.directory / "Morrowind.ini").write_text(
            "[Game Files]\nGameFile0=Enabled.esp\n",
            encoding="utf-8",
        )
        (self.directory / "plugins.txt").write_text(
            "Morrowind.esm\nEnabled.esp\nDisabled.esp\n",
            encoding="utf-8",
        )
        (self.directory / "loadorder.txt").write_text(
            "Disabled.esp\nEnabled.esp\n", encoding="utf-8"
        )
        plugins = _FakePluginList(
            ["Enabled.esp", "Morrowind.esm", "Disabled.esp"],
            active=("Disabled.esp",),
        )

        self.adapter.readPluginLists(plugins)

        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertEqual(
            state["plugin_order"],
            ["Morrowind.esm", "Disabled.esp", "Enabled.esp"],
        )
        self.assertEqual(
            state["enabled_plugins"], ["Morrowind.esm", "Enabled.esp"]
        )
        self.assertEqual(state["content_migration_source"], "Morrowind.ini")
        self.assertEqual(plugins.order, state["plugin_order"])
        self.assertEqual(plugins.active_names, state["enabled_plugins"])
        self.assertEqual(
            _projection(self.directory / "plugins.txt"),
            ["Morrowind.esm", "Enabled.esp"],
        )
        self.assertEqual(
            _projection(self.directory / "loadorder.txt"),
            state["plugin_order"],
        )

    def test_migration_reads_effective_openmw_config_chain(self) -> None:
        nested = self.directory / "nested"
        nested.mkdir()
        (nested / "openmw.cfg").write_text(
            "content=Nested.esp\n", encoding="utf-8"
        )
        (self.directory / "openmw.cfg").write_text(
            "config=nested\n", encoding="utf-8"
        )
        plugins = _FakePluginList(["Nested.esp", "Other.esp", "Morrowind.esm"])

        self.adapter.readPluginLists(plugins)

        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertEqual(state["content_migration_source"], "openmw.cfg")
        self.assertEqual(
            state["enabled_plugins"], ["Morrowind.esm", "Nested.esp"]
        )
        self.assertNotIn("Other.esp", plugins.active_names)

    def test_nonlocal_profile_migrates_from_active_root_config(self) -> None:
        root = self.directory / "root-config"
        root.mkdir()
        (root / "openmw.cfg").write_text(
            "content=Root Selected.esp\n", encoding="utf-8"
        )
        (self.directory / "openmw.cfg").write_text(
            "content=Wrong Profile.esp\n", encoding="utf-8"
        )
        self.organizer._profile = SimpleNamespace(
            absolutePath=lambda: str(self.directory),
            localSettingsEnabled=lambda: False,
        )
        context = {
            "?local?": self.directory / "bin",
            "?userconfig?": root,
            "?userdata?": self.directory / "data",
            "?global?": self.directory / "global",
        }
        plugins = _FakePluginList(
            ["Wrong Profile.esp", "Root Selected.esp", "Morrowind.esm"]
        )

        with mock.patch.object(
            self.adapter,
            "_selection_token_contexts",
            return_value=[context],
        ):
            self.adapter.readPluginLists(plugins)

        self.assertEqual(
            plugins.active_names, ["Morrowind.esm", "Root Selected.esp"]
        )

    def test_migration_resolves_tokens_with_installed_engine_context(self) -> None:
        token_root = self.directory / "token-config"
        curated = token_root / "curated"
        curated.mkdir(parents=True)
        (curated / "openmw.cfg").write_text(
            "content=Selected.esp\n", encoding="utf-8"
        )
        (self.directory / "openmw.cfg").write_text(
            "config=?userconfig?/curated\n", encoding="utf-8"
        )
        context = {
            "?local?": self.directory / "engine/bin",
            "?userconfig?": token_root,
            "?userdata?": self.directory / "data",
            "?global?": self.directory / "global/openmw",
        }
        plugins = _FakePluginList(["Selected.esp", "Other.esp", "Morrowind.esm"])

        with mock.patch.object(
            self.adapter,
            "_selection_token_contexts",
            return_value=[context],
        ):
            self.adapter.readPluginLists(plugins)

        self.assertEqual(
            plugins.active_names, ["Morrowind.esm", "Selected.esp"]
        )

    def test_ambiguous_engine_token_contexts_fail_before_migration(self) -> None:
        native = self.directory / "native"
        flatpak = self.directory / "flatpak"
        (native / "curated").mkdir(parents=True)
        (flatpak / "curated").mkdir(parents=True)
        (native / "curated/openmw.cfg").write_text(
            "content=Native.esp\n", encoding="utf-8"
        )
        (flatpak / "curated/openmw.cfg").write_text(
            "content=Flatpak.esp\n", encoding="utf-8"
        )
        (self.directory / "openmw.cfg").write_text(
            "config=?userconfig?/curated\n", encoding="utf-8"
        )
        contexts = [
            {
                "?local?": native,
                "?userconfig?": native,
                "?userdata?": native,
                "?global?": native,
            },
            {
                "?local?": flatpak,
                "?userconfig?": flatpak,
                "?userdata?": flatpak,
                "?global?": flatpak,
            },
        ]
        plugins = _FakePluginList(
            ["Native.esp", "Flatpak.esp", "Morrowind.esm"]
        )

        with mock.patch.object(
            self.adapter,
            "_selection_token_contexts",
            return_value=contexts,
        ), self.assertRaisesRegex(ValueError, "resolve differently"):
            self.adapter.readPluginLists(plugins)

        self.assertFalse(
            (self.directory / "fluorine-openmw-selection.json").exists()
        )

    def test_wrapper_only_inventory_is_known_but_not_projected(self) -> None:
        game_directory = self.directory / "game"
        data_files = game_directory / "Data Files"
        data_files.mkdir(parents=True)
        (data_files / "Alias.omwaddon.esp").write_bytes(b"wrapper")
        self.organizer = _Organizer(
            self.directory, game_directory=game_directory
        )
        self.adapter = game_plugins.OpenMWGamePlugins(self.organizer)
        plugins = _FakePluginList(["Morrowind.esm"])

        self.adapter.readPluginLists(plugins)

        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertIn("Alias.omwaddon", state["plugin_order"])
        self.assertIn("Alias.omwaddon", state["enabled_plugins"])
        self.assertNotIn(
            "Alias.omwaddon", _projection(self.directory / "plugins.txt")
        )

    def test_fresh_archive_defaults_use_physical_inventory(self) -> None:
        game_directory = self.directory / "game"
        data_files = game_directory / "Data Files"
        data_files.mkdir(parents=True)
        (data_files / "Custom.bsa").write_bytes(b"archive")
        self.organizer = _Organizer(
            self.directory, game_directory=game_directory
        )
        self.adapter = game_plugins.OpenMWGamePlugins(self.organizer)
        plugins = _FakePluginList(["Morrowind.esm"])

        self.adapter.readPluginLists(plugins)

        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertEqual(state["archive_migration_source"], "defaults")
        self.assertEqual(state["archives"], ["Custom.bsa"])

    def test_fresh_archive_authority_does_not_enable_other_physical_bsas(
        self,
    ) -> None:
        game_directory = self.directory / "game"
        data_files = game_directory / "Data Files"
        data_files.mkdir(parents=True)
        (data_files / "Enabled.bsa").write_bytes(b"enabled")
        (data_files / "Disabled.bsa").write_bytes(b"disabled")
        (self.directory / "openmw.cfg").write_text(
            "fallback-archive=Enabled.bsa\n", encoding="utf-8"
        )
        self.organizer = _Organizer(
            self.directory, game_directory=game_directory
        )
        self.adapter = game_plugins.OpenMWGamePlugins(self.organizer)

        self.adapter.readPluginLists(_FakePluginList(["Morrowind.esm"]))

        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertEqual(
            state["known_archives"], ["Disabled.bsa", "Enabled.bsa"]
        )
        self.assertEqual(state["archives"], ["Enabled.bsa"])

    def test_lower_archive_source_does_not_suppress_future_fresh_default(
        self,
    ) -> None:
        game_directory = self.directory / "game"
        data_files = game_directory / "Data Files"
        data_files.mkdir(parents=True)
        (data_files / "Enabled.bsa").write_bytes(b"enabled")
        (self.directory / "openmw.cfg").write_text(
            "fallback-archive=Enabled.bsa\n", encoding="utf-8"
        )
        (self.directory / "archives.txt").write_text(
            "Future.bsa\n", encoding="utf-8"
        )
        self.organizer = _Organizer(
            self.directory, game_directory=game_directory
        )
        self.adapter = game_plugins.OpenMWGamePlugins(self.organizer)
        plugins = _FakePluginList(["Morrowind.esm"])
        self.adapter.readPluginLists(plugins)
        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertNotIn("Future.bsa", state["known_archives"])

        (data_files / "Future.bsa").write_bytes(b"future")
        self.adapter.readPluginLists(plugins)

        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertIn("Future.bsa", state["archives"])

    def test_unresolved_native_local_token_fails_before_migration(self) -> None:
        (self.directory / "openmw.cfg").write_text(
            "config=?local?/curated\n", encoding="utf-8"
        )
        plugins = _FakePluginList(["Morrowind.esm", "Fallback.esp"])

        with mock.patch.object(
            game_plugins.shutil, "which", return_value=None
        ), self.assertRaisesRegex(ValueError, "Unresolved OpenMW path token"):
            self.adapter.readPluginLists(plugins)

        self.assertFalse(
            (self.directory / "fluorine-openmw-selection.json").exists()
        )

    def test_launch_tokens_use_exact_native_executable_path(self) -> None:
        executable = self.directory / "custom-openmw/bin/openmw"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"binary")

        tokens = self.adapter.pathTokensForLaunch(False, str(executable))

        self.assertEqual(tokens["?local?"], executable.parent.resolve())
        self.assertEqual(
            tokens["?global?"],
            self.directory / "custom-openmw/share/games/openmw",
        )

    def test_hydration_contexts_include_configured_custom_executable(self) -> None:
        executable = self.directory / "custom/bin/openmw"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"binary")
        self.organizer._executables = [
            SimpleNamespace(
                binaryInfo=lambda: SimpleNamespace(
                    absoluteFilePath=lambda: str(executable)
                )
            )
        ]

        with mock.patch.object(game_plugins.shutil, "which", return_value=None):
            contexts = self.adapter._selection_token_contexts()

        self.assertIn(
            executable.parent.resolve(),
            [context.get("?local?") for context in contexts],
        )

    def test_flatpak_deployment_context_exists_before_first_app_run(self) -> None:
        deployment = self.directory / "flatpak-deployment"
        result = SimpleNamespace(
            returncode=0,
            stdout=str(deployment).encode("utf-8"),
        )

        with mock.patch.object(Path, "home", return_value=self.directory / "home"), (
            mock.patch.object(
                game_plugins.shutil,
                "which",
                side_effect=lambda name: "/usr/bin/flatpak"
                if name == "flatpak" else None,
            )
        ), mock.patch.object(game_plugins.subprocess, "run", return_value=result):
            contexts = self.adapter._selection_token_contexts()

        self.assertIn(
            deployment / "files/share/games/openmw",
            [context.get("?global?") for context in contexts],
        )

    def test_stale_flatpak_app_home_is_not_an_installation_context(self) -> None:
        home = self.directory / "home"
        stale = home / ".var/app/org.openmw.OpenMW"
        stale.mkdir(parents=True)

        with mock.patch.object(Path, "home", return_value=home), mock.patch.object(
            game_plugins.shutil, "which", return_value=None
        ):
            contexts = self.adapter._selection_token_contexts()

        self.assertNotIn(
            stale / "config/openmw",
            [context.get("?userconfig?") for context in contexts],
        )

    def test_new_physical_archive_is_enabled_after_v3_migration(self) -> None:
        game_directory = self.directory / "game"
        data_files = game_directory / "Data Files"
        data_files.mkdir(parents=True)
        _write_state(
            self.directory,
            _state(["Morrowind.esm"], ["Morrowind.esm"]),
        )
        (data_files / "NewAssets.bsa").write_bytes(b"archive")
        self.organizer = _Organizer(
            self.directory, game_directory=game_directory
        )
        self.adapter = game_plugins.OpenMWGamePlugins(self.organizer)

        self.adapter.readPluginLists(_FakePluginList(["Morrowind.esm"]))

        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertEqual(
            state["known_archives"], ["Morrowind.bsa", "NewAssets.bsa"]
        )
        self.assertEqual(
            state["archives"], ["Morrowind.bsa", "NewAssets.bsa"]
        )

    def test_v2_groundcover_wins_during_migration_read(self) -> None:
        legacy = {
            "version": 2,
            "known_plugins": ["Morrowind.esm", "Curated Grass.esp", "Other.esp"],
            "enabled_plugins": ["Morrowind.esm", "Curated Grass.esp"],
            "groundcover": ["Curated Grass.esp"],
            "known_archives": [],
            "archives": [],
            "profile_config_entries": [],
            "profile_config_entries_known": True,
            "profile_config_terminal": False,
        }
        (self.directory / "fluorine-openmw-selection.json").write_text(
            json.dumps(legacy), encoding="utf-8"
        )
        (self.directory / "groundcover.txt").write_text(
            "Other.esp\n", encoding="utf-8"
        )
        plugins = _FakePluginList(
            ["Other.esp", "Curated Grass.esp", "Morrowind.esm"]
        )

        self.adapter.readPluginLists(plugins)

        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertEqual(state["groundcover"], ["Curated Grass.esp"])
        self.assertEqual(state["groundcover_migration_source"], "state-v2")

    def test_v2_migration_enables_newly_discovered_physical_archive(self) -> None:
        game_directory = self.directory / "game"
        data_files = game_directory / "Data Files"
        data_files.mkdir(parents=True)
        (data_files / "NewAssets.bsa").write_bytes(b"archive")
        legacy = {
            "version": 2,
            "known_plugins": ["Morrowind.esm"],
            "enabled_plugins": ["Morrowind.esm"],
            "groundcover": [],
            "known_archives": ["Old.bsa"],
            "archives": ["Old.bsa"],
            "profile_config_entries": [],
            "profile_config_entries_known": True,
            "profile_config_terminal": False,
        }
        (self.directory / "fluorine-openmw-selection.json").write_text(
            json.dumps(legacy), encoding="utf-8"
        )
        (self.directory / "archives.txt").write_text(
            "NewAssets.bsa\n", encoding="utf-8"
        )
        self.organizer = _Organizer(
            self.directory, game_directory=game_directory
        )
        self.adapter = game_plugins.OpenMWGamePlugins(self.organizer)

        self.adapter.readPluginLists(_FakePluginList(["Morrowind.esm"]))

        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertEqual(
            state["known_archives"], ["Old.bsa", "NewAssets.bsa"]
        )
        self.assertEqual(state["archives"], ["Old.bsa", "NewAssets.bsa"])

    def test_lower_legacy_archive_does_not_suppress_future_physical_default(
        self,
    ) -> None:
        game_directory = self.directory / "game"
        data_files = game_directory / "Data Files"
        data_files.mkdir(parents=True)
        legacy = {
            "version": 2,
            "known_plugins": ["Morrowind.esm"],
            "enabled_plugins": ["Morrowind.esm"],
            "groundcover": [],
            "known_archives": ["Old.bsa"],
            "archives": ["Old.bsa"],
            "profile_config_entries": [],
            "profile_config_entries_known": True,
            "profile_config_terminal": False,
        }
        (self.directory / "fluorine-openmw-selection.json").write_text(
            json.dumps(legacy), encoding="utf-8"
        )
        (self.directory / "archives.txt").write_text(
            "Future.bsa\n", encoding="utf-8"
        )
        self.organizer = _Organizer(
            self.directory, game_directory=game_directory
        )
        self.adapter = game_plugins.OpenMWGamePlugins(self.organizer)
        plugins = _FakePluginList(["Morrowind.esm"])
        self.adapter.readPluginLists(plugins)
        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertNotIn("Future.bsa", state["known_archives"])

        (data_files / "Future.bsa").write_bytes(b"archive")
        self.adapter.readPluginLists(plugins)

        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertIn("Future.bsa", state["archives"])

    def test_v2_migration_enables_newly_discovered_plugin(self) -> None:
        legacy = {
            "version": 2,
            "known_plugins": ["Morrowind.esm", "Old.esp"],
            "enabled_plugins": ["Morrowind.esm"],
            "groundcover": [],
            "known_archives": [],
            "archives": [],
            "profile_config_entries": [],
            "profile_config_entries_known": True,
            "profile_config_terminal": False,
        }
        (self.directory / "fluorine-openmw-selection.json").write_text(
            json.dumps(legacy), encoding="utf-8"
        )
        plugins = _FakePluginList(
            ["New.esp", "Old.esp", "Morrowind.esm"]
        )

        self.adapter.readPluginLists(plugins)

        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertEqual(
            state["enabled_plugins"], ["Morrowind.esm", "New.esp"]
        )
        self.assertNotIn("Old.esp", plugins.active_names)

    def test_missing_enabled_plugin_returns_in_its_committed_slot(self) -> None:
        original = _state(
            ["Morrowind.esm", "Missing.esp", "Available.esp"],
            ["Morrowind.esm", "Missing.esp"],
        )
        _write_state(self.directory, original)
        plugins = _FakePluginList(["Available.esp", "Morrowind.esm"])
        self.adapter.readPluginLists(plugins)
        self.assertEqual(plugins.order, ["Morrowind.esm", "Available.esp"])
        self.assertNotIn("Missing.esp", _projection(self.directory / "plugins.txt"))

        plugins.add("Missing.esp")
        self.adapter.readPluginLists(plugins)

        self.assertEqual(
            plugins.order,
            ["Morrowind.esm", "Missing.esp", "Available.esp"],
        )
        self.assertIn("Missing.esp", plugins.active_names)
        self.assertEqual(
            openmw_cfg.read_selection_state(
                self.directory / "fluorine-openmw-selection.json"
            )["enabled_plugins"],
            ["Morrowind.esm", "Missing.esp"],
        )

    def test_write_merges_available_slots_and_preserves_groundcover(self) -> None:
        original = _state(
            [
                "Morrowind.esm",
                "Unavailable.esp",
                "Unavailable Grass.esp",
                "A.esp",
                "Grass.esp",
                "B.esp",
            ],
            [
                "Morrowind.esm",
                "Unavailable.esp",
                "Unavailable Grass.esp",
                "A.esp",
                "Grass.esp",
            ],
            groundcover=["Unavailable Grass.esp", "Grass.esp"],
        )
        _write_state(self.directory, original)
        plugins = _FakePluginList(
            ["A.esp", "Grass.esp", "Morrowind.esm", "B.esp"]
        )
        self.adapter.readPluginLists(plugins)
        plugins.reorder(["Morrowind.esm", "B.esp", "Grass.esp", "A.esp"])
        plugins.set_active("A.esp", False)
        plugins.set_active("B.esp", True)

        self.adapter.writePluginLists(plugins)
        self.adapter.flushPendingWrites(plugins)

        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertEqual(
            state["plugin_order"],
            [
                "Morrowind.esm",
                "Unavailable.esp",
                "Unavailable Grass.esp",
                "B.esp",
                "Grass.esp",
                "A.esp",
            ],
        )
        self.assertEqual(
            state["enabled_plugins"],
            [
                "Morrowind.esm",
                "Unavailable.esp",
                "Unavailable Grass.esp",
                "B.esp",
                "Grass.esp",
            ],
        )
        self.assertEqual(
            state["groundcover"],
            ["Unavailable Grass.esp", "Grass.esp"],
        )
        self.assertEqual(
            _projection(self.directory / "plugins.txt"),
            ["Morrowind.esm", "B.esp", "Grass.esp"],
        )

    def test_primary_only_active_projection_is_valid(self) -> None:
        _write_state(
            self.directory,
            _state(
                ["Morrowind.esm", "Optional.esp"],
                ["Morrowind.esm"],
            ),
        )
        plugins = _FakePluginList(["Optional.esp", "Morrowind.esm"])

        self.adapter.readPluginLists(plugins)
        self.adapter.writePluginLists(plugins)
        self.adapter.flushPendingWrites(plugins)

        self.assertEqual(plugins.active_names, ["Morrowind.esm"])
        self.assertEqual(
            _projection(self.directory / "plugins.txt"), ["Morrowind.esm"]
        )
        self.assertEqual(
            _projection(self.directory / "loadorder.txt"),
            ["Morrowind.esm", "Optional.esp"],
        )

    def test_existing_inactive_groundcover_is_not_reactivated_on_read(self) -> None:
        _write_state(
            self.directory,
            _state(
                ["Morrowind.esm", "Grass.esp"],
                ["Morrowind.esm"],
                groundcover=["Grass.esp"],
            ),
        )
        (self.directory / "groundcover.txt").write_text(
            "Grass.esp\n", encoding="utf-8"
        )
        plugins = _FakePluginList(["Grass.esp", "Morrowind.esm"])

        self.adapter.readPluginLists(plugins)

        self.assertEqual(plugins.active_names, ["Morrowind.esm"])
        state = openmw_cfg.read_selection_state(
            self.directory / "fluorine-openmw-selection.json"
        )
        self.assertEqual(state["groundcover"], ["Grass.esp"])
        self.assertEqual(state["enabled_plugins"], ["Morrowind.esm"])

    def test_export_snapshot_reconciles_new_groundcover_classification(self) -> None:
        _write_state(
            self.directory,
            _state(
                ["Morrowind.esm", "Grass.esp"],
                ["Morrowind.esm"],
            ),
        )
        plugins = _FakePluginList(["Grass.esp", "Morrowind.esm"])
        self.adapter.readPluginLists(plugins)
        (self.directory / "groundcover.txt").write_text(
            "*Grass.esp\n", encoding="utf-8"
        )

        snapshot = self.adapter.exportSnapshot(plugins)

        self.assertEqual(snapshot["state"]["groundcover"], ["Grass.esp"])
        self.assertEqual(
            snapshot["state"]["enabled_plugins"],
            ["Morrowind.esm", "Grass.esp"],
        )
        self.assertEqual(plugins.active_names, ["Morrowind.esm"])
        self.assertEqual(
            openmw_cfg.read_selection_state(
                self.directory / "fluorine-openmw-selection.json"
            )["enabled_plugins"],
            ["Morrowind.esm"],
        )

        with openmw_cfg.rollback_file_changes(
            [
                self.directory / "fluorine-openmw-selection.json",
                self.directory / "plugins.txt",
                self.directory / "loadorder.txt",
            ]
        ):
            self.adapter.stageExportState(plugins, snapshot["state"])
        self.adapter.commitExportState(plugins, snapshot["state"])

        self.assertEqual(plugins.active_names, ["Morrowind.esm", "Grass.esp"])

    def test_staged_export_ui_rollback_failure_is_permanently_fatal(self) -> None:
        _write_state(
            self.directory,
            _state(["Morrowind.esm", "Grass.esp"], ["Morrowind.esm"]),
        )
        plugins = _FakePluginList(["Grass.esp", "Morrowind.esm"])
        self.adapter.readPluginLists(plugins)
        (self.directory / "groundcover.txt").write_text(
            "Grass.esp\n", encoding="utf-8"
        )
        snapshot = self.adapter.exportSnapshot(plugins)

        with mock.patch.object(
            self.adapter,
            "_apply_ui",
            side_effect=OSError("injected staged UI failure"),
        ), mock.patch.object(
            self.adapter,
            "_restore_ui",
            side_effect=RuntimeError("injected staged rollback failure"),
        ), self.assertRaisesRegex(RuntimeError, "staged rollback"):
            self.adapter.stageExportState(plugins, snapshot["state"])

        with self.assertRaisesRegex(RuntimeError, "unrecoverable"):
            self.adapter.flushPendingWrites(plugins)

    def test_commit_export_state_accepts_selector_only_changes(self) -> None:
        _write_state(
            self.directory,
            _state(["Morrowind.esm", "A.esp"], ["Morrowind.esm"]),
        )
        plugins = _FakePluginList(["A.esp", "Morrowind.esm"])
        self.adapter.readPluginLists(plugins)
        snapshot = self.adapter.exportSnapshot(plugins)
        state = snapshot["state"]
        state["profile_config_terminal"] = True
        openmw_cfg.write_selection_state(
            self.directory / "fluorine-openmw-selection.json", state
        )

        self.adapter.commitExportState(plugins, state)

        self.assertEqual(
            self.adapter.exportSnapshot(plugins)["state"], state
        )

    def test_ui_application_failure_restores_files_and_pre_read_ui(self) -> None:
        state = _state(
            ["Morrowind.esm", "A.esp"],
            ["Morrowind.esm"],
        )
        _write_state(self.directory, state)
        (self.directory / "plugins.txt").write_text(
            "legacy plugins\n", encoding="utf-8"
        )
        (self.directory / "loadorder.txt").write_text(
            "legacy order\n", encoding="utf-8"
        )
        before = {
            name: (self.directory / name).read_bytes()
            for name in (
                "fluorine-openmw-selection.json",
                "plugins.txt",
                "loadorder.txt",
            )
        }
        plugins = _FakePluginList(
            ["A.esp", "Morrowind.esm"], active=("A.esp",)
        )
        plugins.fail_set_state_for = "A.esp"

        with self.assertRaisesRegex(OSError, "injected UI"):
            self.adapter.readPluginLists(plugins)

        self.assertEqual(plugins.order, ["A.esp", "Morrowind.esm"])
        self.assertEqual(plugins.active_names, ["A.esp"])
        for name, contents in before.items():
            self.assertEqual((self.directory / name).read_bytes(), contents)

    def test_atomic_write_failure_restores_files_and_committed_ui(self) -> None:
        _write_state(
            self.directory,
            _state(
                ["Morrowind.esm", "A.esp", "B.esp"],
                ["Morrowind.esm", "A.esp"],
            ),
        )
        plugins = _FakePluginList(["B.esp", "Morrowind.esm", "A.esp"])
        self.adapter.readPluginLists(plugins)
        before = {
            name: (self.directory / name).read_bytes()
            for name in (
                "fluorine-openmw-selection.json",
                "plugins.txt",
                "loadorder.txt",
            )
        }
        plugins.reorder(["Morrowind.esm", "B.esp", "A.esp"])
        original_write = game_plugins._atomic_write_text
        calls = 0

        def fail_second(path: Path, text: str) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected loadorder failure")
            original_write(path, text)

        self.adapter.writePluginLists(plugins)
        with mock.patch.object(
            game_plugins, "_atomic_write_text", side_effect=fail_second
        ), self.assertRaisesRegex(OSError, "injected loadorder"):
            self.adapter.flushPendingWrites(plugins)

        self.assertEqual(plugins.order, ["Morrowind.esm", "A.esp", "B.esp"])
        for name, contents in before.items():
            self.assertEqual((self.directory / name).read_bytes(), contents)

    def test_exact_readback_failure_rolls_back(self) -> None:
        _write_state(
            self.directory,
            _state(
                ["Morrowind.esm", "A.esp", "B.esp"],
                ["Morrowind.esm", "A.esp", "B.esp"],
            ),
        )
        plugins = _FakePluginList(["Morrowind.esm", "A.esp", "B.esp"])
        self.adapter.readPluginLists(plugins)
        before = (self.directory / "loadorder.txt").read_bytes()
        plugins.reorder(["Morrowind.esm", "B.esp", "A.esp"])
        self.adapter.writePluginLists(plugins)
        original_read = game_plugins._read_projection_exact

        def corrupt_readback(path: Path) -> list[str]:
            if path.name == "loadorder.txt":
                return ["Morrowind.esm"]
            return original_read(path)

        with mock.patch.object(
            game_plugins,
            "_read_projection_exact",
            side_effect=corrupt_readback,
        ), self.assertRaisesRegex(RuntimeError, "loadorder.txt read-back"):
            self.adapter.flushPendingWrites(plugins)

        self.assertEqual(
            (self.directory / "loadorder.txt").read_bytes(), before
        )
        self.assertEqual(plugins.order, ["Morrowind.esm", "A.esp", "B.esp"])

    def test_delayed_writes_coalesce_and_failure_is_sticky(self) -> None:
        _write_state(
            self.directory,
            _state(
                ["Morrowind.esm", "A.esp", "B.esp"],
                ["Morrowind.esm", "A.esp", "B.esp"],
            ),
        )
        plugins = _FakePluginList(["Morrowind.esm", "A.esp", "B.esp"])
        self.adapter.readPluginLists(plugins)
        plugins.reorder(["Morrowind.esm", "B.esp", "A.esp"])
        self.adapter.writePluginLists(plugins)
        plugins.reorder(["Morrowind.esm", "A.esp", "B.esp"])
        self.adapter.writePluginLists(plugins)
        self.assertEqual(len(_FakeTimer.callbacks), 1)
        _FakeTimer.run_all()
        self.assertEqual(
            _projection(self.directory / "loadorder.txt"),
            ["Morrowind.esm", "A.esp", "B.esp"],
        )

        plugins.reorder(["Morrowind.esm", "B.esp", "A.esp"])
        self.adapter.writePluginLists(plugins)
        with mock.patch.object(
            game_plugins,
            "_atomic_write_text",
            side_effect=OSError("delayed injected failure"),
        ):
            _FakeTimer.run_all()

        self.assertEqual(plugins.order, ["Morrowind.esm", "A.esp", "B.esp"])
        self.assertTrue(
            any("delayed plugin persistence failed" in message for message in _CRITICAL_MESSAGES)
        )
        with self.assertRaisesRegex(RuntimeError, "Previous OpenMW"):
            self.adapter.flushPendingWrites(plugins)

        plugins.reorder(["Morrowind.esm", "B.esp", "A.esp"])
        self.adapter.writePluginLists(plugins)
        _FakeTimer.run_all()
        self.adapter.flushPendingWrites(plugins)
        self.assertEqual(
            _projection(self.directory / "loadorder.txt"),
            ["Morrowind.esm", "B.esp", "A.esp"],
        )

    def test_ui_rollback_failure_permanently_blocks_persistence(self) -> None:
        _write_state(
            self.directory,
            _state(
                ["Morrowind.esm", "A.esp", "B.esp"],
                ["Morrowind.esm", "A.esp"],
            ),
        )
        plugins = _FakePluginList(["Morrowind.esm", "A.esp", "B.esp"])
        self.adapter.readPluginLists(plugins)
        plugins.reorder(["Morrowind.esm", "B.esp", "A.esp"])
        self.adapter.writePluginLists(plugins)

        with mock.patch.object(
            game_plugins,
            "_atomic_write_text",
            side_effect=OSError("injected persistence failure"),
        ), mock.patch.object(
            self.adapter,
            "_restore_committed",
            side_effect=OSError("injected rollback failure"),
        ), self.assertRaisesRegex(OSError, "injected persistence"):
            self.adapter.flushPendingWrites(plugins)

        plugins.reorder(["Morrowind.esm", "A.esp", "B.esp"])
        self.adapter.writePluginLists(plugins)
        with self.assertRaisesRegex(RuntimeError, "unrecoverable"):
            self.adapter.flushPendingWrites(plugins)

    def test_hydration_ui_rollback_failure_permanently_blocks(self) -> None:
        _write_state(
            self.directory,
            _state(["Morrowind.esm", "A.esp"], ["Morrowind.esm"]),
        )
        plugins = _FakePluginList(["A.esp", "Morrowind.esm"], active=("A.esp",))
        self.adapter.readPluginLists(plugins)
        plugins.reorder(["A.esp", "Morrowind.esm"])
        plugins.fail_set_state_for = "A.esp"

        with mock.patch.object(
            self.adapter,
            "_restore_ui",
            side_effect=RuntimeError("injected hydration rollback failure"),
        ), self.assertRaisesRegex(RuntimeError, "hydration rollback"):
            self.adapter.readPluginLists(plugins)

        with self.assertRaisesRegex(RuntimeError, "unrecoverable"):
            self.adapter.flushPendingWrites(plugins)

    def test_incomplete_disk_rollback_permanently_blocks(self) -> None:
        _write_state(
            self.directory,
            _state(["Morrowind.esm", "A.esp"], ["Morrowind.esm"]),
        )
        plugins = _FakePluginList(["Morrowind.esm", "A.esp"])
        self.adapter.readPluginLists(plugins)
        plugins.reorder(["A.esp", "Morrowind.esm"])
        self.adapter.writePluginLists(plugins)

        with mock.patch.object(
            game_plugins,
            "rollback_file_changes",
            side_effect=openmw_cfg.TransactionRollbackError(
                "injected incomplete rollback"
            ),
        ), self.assertRaisesRegex(
            openmw_cfg.TransactionRollbackError, "incomplete rollback"
        ):
            self.adapter.flushPendingWrites(plugins)

        with self.assertRaisesRegex(RuntimeError, "unrecoverable"):
            self.adapter.flushPendingWrites(plugins)

    def test_profile_refresh_persists_pending_snapshot_without_old_ui_apply(
        self,
    ) -> None:
        old_directory = self.directory / "old"
        new_directory = self.directory / "new"
        old_directory.mkdir()
        new_directory.mkdir()
        _write_state(
            old_directory,
            _state(
                ["Morrowind.esm", "A.esp", "B.esp"],
                ["Morrowind.esm", "A.esp"],
            ),
        )
        _write_state(
            new_directory,
            _state(
                ["Morrowind.esm", "New.esp"],
                ["Morrowind.esm", "New.esp"],
            ),
        )
        self.organizer._profile = SimpleNamespace(
            absolutePath=lambda: str(old_directory)
        )
        old_plugins = _FakePluginList(
            ["Morrowind.esm", "A.esp", "B.esp"]
        )
        self.adapter.readPluginLists(old_plugins)
        old_plugins.reorder(["Morrowind.esm", "B.esp", "A.esp"])
        self.adapter.writePluginLists(old_plugins)

        self.organizer._profile = SimpleNamespace(
            absolutePath=lambda: str(new_directory)
        )
        new_plugins = _FakePluginList(["New.esp", "Morrowind.esm"])
        self.adapter.readPluginLists(new_plugins)

        self.assertEqual(
            _projection(old_directory / "loadorder.txt"),
            ["Morrowind.esm", "B.esp", "A.esp"],
        )
        self.assertEqual(new_plugins.order, ["Morrowind.esm", "New.esp"])
        self.assertEqual(
            new_plugins.active_names, ["Morrowind.esm", "New.esp"]
        )

    def test_profile_switch_incomplete_old_rollback_is_permanently_fatal(
        self,
    ) -> None:
        old_directory = self.directory / "old"
        new_directory = self.directory / "new"
        old_directory.mkdir()
        new_directory.mkdir()
        _write_state(
            old_directory,
            _state(["Morrowind.esm", "A.esp"], ["Morrowind.esm"]),
        )
        _write_state(
            new_directory,
            _state(["Morrowind.esm", "New.esp"], ["Morrowind.esm"]),
        )
        self.organizer._profile = SimpleNamespace(
            absolutePath=lambda: str(old_directory)
        )
        old_plugins = _FakePluginList(["Morrowind.esm", "A.esp"])
        self.adapter.readPluginLists(old_plugins)
        old_plugins.reorder(["A.esp", "Morrowind.esm"])
        self.adapter.writePluginLists(old_plugins)
        self.organizer._profile = SimpleNamespace(
            absolutePath=lambda: str(new_directory)
        )
        new_plugins = _FakePluginList(["Morrowind.esm", "New.esp"])

        with mock.patch.object(
            game_plugins,
            "rollback_file_changes",
            side_effect=openmw_cfg.TransactionRollbackError(
                "injected profile-switch rollback failure"
            ),
        ), self.assertRaisesRegex(
            openmw_cfg.TransactionRollbackError, "profile-switch"
        ):
            self.adapter.readPluginLists(new_plugins)

        self.adapter.writePluginLists(new_plugins)
        with self.assertRaisesRegex(RuntimeError, "unrecoverable"):
            self.adapter.flushPendingWrites(new_plugins)

    def test_loot_snapshot_revision_and_complete_order_application(self) -> None:
        order = [
            "Morrowind.esm",
            "Inactive.esp",
            "A.esp",
            "Unavailable.esp",
            "Grass.esp",
            "Scripts.omwscripts",
            "B.esp",
        ]
        _write_state(
            self.directory,
            _state(
                order,
                [
                    "Morrowind.esm",
                    "A.esp",
                    "Unavailable.esp",
                    "Grass.esp",
                    "Scripts.omwscripts",
                    "B.esp",
                ],
                groundcover=["Grass.esp"],
            ),
        )
        plugins = _FakePluginList(
            [
                "Morrowind.esm",
                "Inactive.esp",
                "A.esp",
                "Grass.esp",
                "Scripts.omwscripts",
                "B.esp",
            ]
        )
        self.adapter.readPluginLists(plugins)

        snapshot = self.adapter.lootSortSnapshot(plugins)
        self.assertEqual([row["name"] for row in snapshot["rows"]], order)
        unavailable = next(
            row for row in snapshot["rows"]
            if row["name"] == "Unavailable.esp"
        )
        grass = next(
            row for row in snapshot["rows"] if row["name"] == "Grass.esp"
        )
        self.assertFalse(unavailable["available"])
        self.assertTrue(unavailable["active"])
        self.assertTrue(grass["groundcover"])

        sorted_order = [
            "Morrowind.esm",
            "Inactive.esp",
            "B.esp",
            "Unavailable.esp",
            "Grass.esp",
            "Scripts.omwscripts",
            "A.esp",
        ]
        self.assertTrue(
            self.adapter.applyLootOrder(
                plugins, snapshot["revision"], sorted_order
            )
        )
        self.assertEqual(
            openmw_cfg.read_selection_state(
                self.directory / "fluorine-openmw-selection.json"
            )["plugin_order"],
            sorted_order,
        )
        self.assertEqual(
            plugins.order,
            [
                "Morrowind.esm",
                "Inactive.esp",
                "B.esp",
                "Grass.esp",
                "Scripts.omwscripts",
                "A.esp",
            ],
        )
        with self.assertRaisesRegex(RuntimeError, "changed while LOOT"):
            self.adapter.applyLootOrder(
                plugins, snapshot["revision"], sorted_order
            )

    def test_loot_rejects_movement_of_fixed_slots(self) -> None:
        order = ["Morrowind.esm", "Inactive.esp", "A.esp"]
        _write_state(
            self.directory,
            _state(order, ["Morrowind.esm", "A.esp"]),
        )
        plugins = _FakePluginList(order)
        self.adapter.readPluginLists(plugins)
        snapshot = self.adapter.lootSortSnapshot(plugins)

        with self.assertRaisesRegex(ValueError, "fixed OpenMW slot"):
            self.adapter.applyLootOrder(
                plugins,
                snapshot["revision"],
                ["Morrowind.esm", "A.esp", "Inactive.esp"],
            )
        self.assertEqual(plugins.order, order)

    def test_get_load_order_is_read_only(self) -> None:
        state = _state(
            ["Morrowind.esm", "Unavailable.esp"],
            ["Morrowind.esm"],
        )
        _write_state(self.directory, state)
        before = (self.directory / "fluorine-openmw-selection.json").read_bytes()

        self.assertEqual(self.adapter.getLoadOrder(), state["plugin_order"])
        self.assertEqual(
            (self.directory / "fluorine-openmw-selection.json").read_bytes(),
            before,
        )
        self.assertFalse((self.directory / "plugins.txt").exists())


if __name__ == "__main__":
    unittest.main()
