from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


class _Signal:
    def connect(self, *args, **kwargs) -> None:
        pass

    def emit(self, *args, **kwargs) -> None:
        pass


class _QObject:
    def tr(self, text: str) -> str:
        return text

    def moveToThread(self, thread) -> None:
        pass


class _PluginBase:
    def __init__(self) -> None:
        pass


def _install_import_stubs() -> None:
    pyqt = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    qtcore.QCoreApplication = SimpleNamespace(translate=lambda context, text: text)
    qtcore.QObject = _QObject
    qtcore.Qt = SimpleNamespace(
        WindowModality=SimpleNamespace(WindowModal=1),
        ConnectionType=SimpleNamespace(QueuedConnection=1),
    )
    qtcore.QThread = type("QThread", (), {})
    qtcore.pyqtSignal = lambda *args, **kwargs: _Signal()
    qtcore.qInfo = lambda *args, **kwargs: None
    qtcore.qWarning = lambda *args, **kwargs: None

    class _StandardButton:
        Ok = 1
        Yes = 2
        No = 4

    qtwidgets.QMessageBox = type(
        "QMessageBox",
        (),
        {
            "Icon": SimpleNamespace(Warning=1, Information=2),
            "StandardButton": _StandardButton,
        },
    )
    qtwidgets.QProgressDialog = type("QProgressDialog", (), {})
    pyqt.QtCore = qtcore
    pyqt.QtWidgets = qtwidgets

    mobase = types.ModuleType("mobase")
    mobase.IPluginTool = type("IPluginTool", (_PluginBase,), {})
    mobase.IPlugin = type("IPlugin", (_PluginBase,), {})
    mobase.IOrganizer = object
    mobase.IPluginList = object
    mobase.GamePlugins = type("GamePlugins", (), {})
    mobase.VersionInfo = lambda *args: args
    mobase.PluginSetting = lambda *args: args
    mobase.ModState = SimpleNamespace(ACTIVE=1)
    mobase.PluginState = SimpleNamespace(ACTIVE=2)

    sys.modules.setdefault("PyQt6", pyqt)
    sys.modules.setdefault("PyQt6.QtCore", qtcore)
    sys.modules.setdefault("PyQt6.QtWidgets", qtwidgets)
    sys.modules.setdefault("mobase", mobase)


_install_import_stubs()
SUPPORT_PATH = (
    Path(__file__).parents[2] / "libs/basic_games/games/openmw_support"
)
PACKAGE_NAME = "_openmw_loot_tests"
PACKAGE = types.ModuleType(PACKAGE_NAME)
PACKAGE.__path__ = [str(SUPPORT_PATH)]
sys.modules[PACKAGE_NAME] = PACKAGE
PLUGINS_PACKAGE = types.ModuleType(f"{PACKAGE_NAME}.plugins")
PLUGINS_PACKAGE.__path__ = [str(SUPPORT_PATH / "plugins")]
sys.modules[f"{PACKAGE_NAME}.plugins"] = PLUGINS_PACKAGE
MODULE_PATH = SUPPORT_PATH / "plugins/sort_with_loot.py"
SPEC = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.plugins.sort_with_loot", MODULE_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {MODULE_PATH}")
loot_sort = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = loot_sort
SPEC.loader.exec_module(loot_sort)


def _resource_root(parent: Path, name: str) -> Path:
    root = parent / name
    (root / "resources/vfs").mkdir(parents=True)
    return root


class _Response:
    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        pass

    def read(self) -> bytes:
        return self._data


class OpenMWLootMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.primary = "Morrowind.esm"
        self.slots = (
            loot_sort.PluginSlot(self.primary, True, primary=True),
            loot_sort.PluginSlot("Inactive.esp", False),
            loot_sort.PluginSlot("First.ESP", True),
            loot_sort.PluginSlot("Third.esp", True),
            loot_sort.PluginSlot("Unavailable.esp", True, available=False),
            loot_sort.PluginSlot("Grass.esp", True, groundcover=True),
            loot_sort.PluginSlot("Interface.omwscripts", True),
            loot_sort.PluginSlot("Second.esp", True),
            loot_sort.PluginSlot("Alias.omwaddon.esp", True),
        )

    def test_merges_only_movable_active_slots_and_preserves_casing(self) -> None:
        merge = loot_sort.merge_active_slots(
            self.slots,
            ["morrowind.ESM", "third.ESP", "first.esp", "second.esp"],
            [self.primary],
        )

        self.assertEqual(
            merge.order,
            (
                self.primary,
                "Inactive.esp",
                "Third.esp",
                "First.ESP",
                "Unavailable.esp",
                "Grass.esp",
                "Interface.omwscripts",
                "Second.esp",
                "Alias.omwaddon.esp",
            ),
        )
        self.assertEqual(
            merge.request,
            (self.primary, "First.ESP", "Third.esp", "Second.esp"),
        )
        self.assertEqual(merge.moved, 2)

    def test_rejects_primary_movement(self) -> None:
        with self.assertRaisesRegex(ValueError, "fixed primary"):
            loot_sort.merge_active_slots(
                self.slots,
                ["Second.esp", self.primary, "First.ESP", "Third.esp"],
                [self.primary],
            )

    def test_rejects_incorrect_primary_classification(self) -> None:
        slots = (loot_sort.PluginSlot(self.primary, True),)
        with self.assertRaisesRegex(ValueError, "Primary classification"):
            loot_sort.merge_active_slots(slots, [self.primary], [self.primary])

    def test_rejects_noncanonical_primary_order(self) -> None:
        slots = (
            loot_sort.PluginSlot("Tribunal.esm", True, primary=True),
            loot_sort.PluginSlot(self.primary, True, primary=True),
            loot_sort.PluginSlot("Plugin.esp", True),
        )
        with self.assertRaisesRegex(ValueError, "canonical primary order"):
            loot_sort.merge_active_slots(
                slots,
                ["Tribunal.esm", self.primary, "Plugin.esp"],
                [self.primary, "Tribunal.esm"],
            )

    def test_rejects_non_bijective_loot_results(self) -> None:
        invalid_results = (
            [self.primary, "First.ESP"],
            [self.primary, "First.ESP", "Added.esp"],
            [self.primary, "First.ESP", "first.esp"],
        )
        for result in invalid_results:
            with self.subTest(result=result), self.assertRaises(ValueError):
                loot_sort.merge_active_slots(self.slots, result, [self.primary])

    def test_rejects_casing_ambiguous_request(self) -> None:
        slots = self.slots + (loot_sort.PluginSlot("first.esp", True),)
        with self.assertRaisesRegex(ValueError, "casing-ambiguous"):
            loot_sort.loot_sort_request(slots)

    def test_rejects_missing_unavailable_and_inactive_masters(self) -> None:
        dependent = loot_sort.PluginSlot(
            "Dependent.esp", True, required_masters=("Required.esm",)
        )
        cases = (
            (dependent,),
            (loot_sort.PluginSlot("Required.esm", True, available=False), dependent),
            (loot_sort.PluginSlot("Required.esm", False), dependent),
        )
        for slots in cases:
            with self.subTest(slots=slots), self.assertRaises(ValueError):
                loot_sort.validate_required_masters(slots)

    def test_rejects_result_that_violates_master_order(self) -> None:
        slots = (
            loot_sort.PluginSlot("Required.esm", True),
            loot_sort.PluginSlot(
                "Dependent.esp", True, required_masters=("Required.esm",)
            ),
        )
        with self.assertRaisesRegex(ValueError, "before required master"):
            loot_sort.merge_active_slots(
                slots, ["Dependent.esp", "Required.esm"], []
            )

    def test_rejects_plugins_crossing_fixed_omwscripts_barrier(self) -> None:
        slots = (
            loot_sort.PluginSlot("Before.esp", True),
            loot_sort.PluginSlot("Framework.omwscripts", True),
            loot_sort.PluginSlot("After.esp", True),
        )

        with self.assertRaisesRegex(ValueError, "fixed script slot"):
            loot_sort.merge_active_slots(
                slots, ["After.esp", "Before.esp"], []
            )


class OpenMWLootResourceTests(unittest.TestCase):
    def test_selects_native_or_flatpak_only_and_rejects_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            native = _resource_root(parent, "native")
            flatpak = _resource_root(parent, "flatpak")

            self.assertEqual(
                loot_sort.select_resource_root("", [native], []).installation,
                "native",
            )
            self.assertEqual(
                loot_sort.select_resource_root("", [], [flatpak]).installation,
                "flatpak",
            )
            with self.assertRaisesRegex(ValueError, "Both native and Flatpak"):
                loot_sort.select_resource_root("", [native], [flatpak])
            self.assertEqual(
                loot_sort.select_resource_root(
                    "", [native], [native / "."]
                ).root,
                native.resolve(),
            )

    def test_override_is_validated_and_accepts_resources_or_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = _resource_root(parent, "install")
            alias = parent / "alias"
            alias.symlink_to(root, target_is_directory=True)

            resources = loot_sort.select_resource_root(
                str(root / "resources"), [], []
            )
            linked = loot_sort.select_resource_root(str(alias), [], [])
            self.assertEqual(resources.root, root.resolve())
            self.assertEqual(linked.root, root.resolve())

            with self.assertRaisesRegex(ValueError, "configured"):
                loot_sort.select_resource_root(
                    str(parent / "missing"), [root], []
                )

    def test_resource_config_uses_openmw_escaping_and_last_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cfg = Path(temporary) / "openmw.cfg"
            cfg.write_text(
                'resources="/old/path"\n'
                'resources="/new/with&&amp&"quote" trailing text is ignored\n',
                encoding="utf-8",
            )

            self.assertEqual(
                loot_sort.OpenMWSortWithLoot._resource_from_cfg(cfg),
                Path('/new/with&amp"quote'),
            )

    def test_resource_config_rejects_wrong_case_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cfg = Path(temporary) / "openmw.cfg"
            cfg.write_text(
                "resources=?GLOBAL?/resources\n", encoding="utf-8"
            )

            self.assertIsNone(
                loot_sort.OpenMWSortWithLoot._resource_from_cfg(
                    cfg, {"?global?": Path(temporary)}
                )
            )

    def test_relative_resource_path_is_relative_to_containing_cfg(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cfg_dir = directory / "config/profile"
            cfg_dir.mkdir(parents=True)
            cfg = cfg_dir / "openmw.cfg"
            cfg.write_text("resources=../../install/resources\n", encoding="utf-8")

            self.assertEqual(
                loot_sort.OpenMWSortWithLoot._resource_from_cfg(cfg),
                (directory / "install/resources").resolve(),
            )

    def test_higher_config_overrides_root_resource_scalar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            root = directory / "openmw.cfg"
            higher = directory / "higher"
            higher.mkdir()
            root.write_text(
                "resources=old/resources\nconfig=higher\n", encoding="utf-8"
            )
            (higher / "openmw.cfg").write_text(
                "resources=../new/resources\n", encoding="utf-8"
            )

            self.assertEqual(
                loot_sort.OpenMWSortWithLoot._resource_from_cfg(root),
                (directory / "new/resources").resolve(),
            )

    def test_resource_config_chain_uses_breadth_first_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            root = directory / "openmw.cfg"
            first = directory / "first"
            second = directory / "second"
            nested = directory / "nested"
            first.mkdir()
            second.mkdir()
            nested.mkdir()
            root.write_text("config=first\nconfig=second\n", encoding="utf-8")
            (first / "openmw.cfg").write_text(
                "config=../nested\n", encoding="utf-8"
            )
            (second / "openmw.cfg").write_text(
                "resources=second/resources\n", encoding="utf-8"
            )
            (nested / "openmw.cfg").write_text(
                "resources=nested/resources\n", encoding="utf-8"
            )

            self.assertEqual(
                loot_sort.OpenMWSortWithLoot._resource_from_cfg(root),
                (nested / "nested/resources").resolve(),
            )

    def test_resource_chain_maps_openmw_tokens_in_native_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            local = directory / "native/bin"
            prefix = directory / "native"
            user_config = directory / "config"
            user_data = directory / "data"
            local.mkdir(parents=True)
            (user_config / "openmw/profile").mkdir(parents=True)
            with mock.patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": str(user_config),
                    "XDG_DATA_HOME": str(user_data),
                },
            ):
                roots = loot_sort._native_token_roots(local, prefix)

            cfg = local / "openmw.cfg"
            cfg.write_text("config=?userconfig?/profile\n", encoding="utf-8")
            (user_config / "openmw/profile/openmw.cfg").write_text(
                "resources=?global?/resources\n", encoding="utf-8"
            )

            self.assertEqual(roots["?local?"], local)
            self.assertEqual(roots["?userdata?"], user_data / "openmw")
            self.assertEqual(
                loot_sort.OpenMWSortWithLoot._resource_from_cfg(cfg, roots),
                (prefix / "share/games/openmw/resources").resolve(),
            )

    def test_flatpak_tokens_use_host_visible_app_and_deployment_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            deployment = directory / "deployment"
            app_home = directory / "flatpak-home"
            with mock.patch.object(Path, "home", return_value=app_home):
                roots = loot_sort._flatpak_token_roots(deployment)

            self.assertEqual(roots["?local?"], deployment / "files/bin")
            self.assertEqual(
                roots["?userconfig?"],
                app_home / ".var/app/org.openmw.OpenMW/config/openmw",
            )
            self.assertEqual(
                roots["?userdata?"],
                app_home / ".var/app/org.openmw.OpenMW/data/openmw",
            )
            self.assertEqual(
                roots["?global?"], deployment / "files/share/games/openmw"
            )

            with mock.patch.object(Path, "home", return_value=app_home):
                unresolved = loot_sort._flatpak_token_roots(None)
            self.assertNotIn("?local?", unresolved)
            self.assertNotIn("?global?", unresolved)

    def test_overridden_resource_does_not_create_false_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            old = _resource_root(directory, "old")
            selected = _resource_root(directory, "selected")
            executable = directory / "native/bin/openmw"
            executable.parent.mkdir(parents=True)
            executable.touch()
            cfg = directory / "native/etc/openmw/openmw.cfg"
            cfg.parent.mkdir(parents=True)
            higher = cfg.parent / "higher"
            higher.mkdir()
            cfg.write_text(
                f"resources={old / 'resources'}\nconfig=higher\n",
                encoding="utf-8",
            )
            (higher / "openmw.cfg").write_text(
                f"resources={selected / 'resources'}\n", encoding="utf-8"
            )

            def which(name: str) -> str | None:
                return str(executable) if name == "openmw" else None

            with mock.patch.object(loot_sort.shutil, "which", side_effect=which), (
                mock.patch.object(Path, "home", return_value=directory / "home")
            ):
                native, flatpak = (
                    loot_sort.OpenMWSortWithLoot()._resource_candidates()
                )
            result = loot_sort.select_resource_root("", native, flatpak)

            self.assertIn(selected / "resources", native)
            self.assertNotIn(old / "resources", native)
            self.assertEqual(result.root, selected.resolve())

    def test_resource_discovery_includes_configured_custom_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            executable = directory / "custom/bin/openmw"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"binary")
            resource = _resource_root(directory / "custom", "share/games/openmw")
            configured = SimpleNamespace(
                binaryInfo=lambda: SimpleNamespace(
                    absoluteFilePath=lambda: str(executable)
                )
            )
            organizer = SimpleNamespace(
                executablesList=lambda: SimpleNamespace(
                    executables=lambda: iter([configured])
                )
            )
            tool = loot_sort.OpenMWSortWithLoot()
            tool._organizer = organizer

            with mock.patch.object(loot_sort.shutil, "which", return_value=None), (
                mock.patch.object(Path, "home", return_value=directory / "home")
            ):
                native, flatpak = tool._resource_candidates()

            self.assertIn(resource, native)
            self.assertEqual(flatpak, [])

    def test_stale_flatpak_config_is_not_a_resource_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            stale_cfg = home / ".var/app/org.openmw.OpenMW/config/openmw"
            stale_resource = _resource_root(Path(temporary), "stale")
            stale_cfg.mkdir(parents=True)
            (stale_cfg / "openmw.cfg").write_text(
                f"resources={stale_resource / 'resources'}\n",
                encoding="utf-8",
            )
            tool = loot_sort.OpenMWSortWithLoot()

            with mock.patch.object(Path, "home", return_value=home), mock.patch.object(
                loot_sort.shutil, "which", return_value=None
            ):
                _, flatpak = tool._resource_candidates()

            self.assertEqual(flatpak, [])

    def test_reports_unreadable_flatpak_and_no_installation(self) -> None:
        missing = Path("/definitely/missing/openmw")
        with self.assertRaisesRegex(ValueError, "not host-readable"):
            loot_sort.select_resource_root("", [], [missing])
        with self.assertRaisesRegex(ValueError, "No valid"):
            loot_sort.select_resource_root("", [], [])


class OpenMWLootMasterlistTests(unittest.TestCase):
    def test_loot_module_search_path_handles_extension_and_package(self) -> None:
        self.assertEqual(
            loot_sort._loot_module_search_path(
                "/runtime/site-packages/loot.cpython-312.so"
            ),
            "/runtime/site-packages",
        )
        self.assertEqual(
            loot_sort._loot_module_search_path(
                "/runtime/site-packages/loot/__init__.py"
            ),
            "/runtime/site-packages",
        )

    def test_verified_download_is_atomically_cached(self) -> None:
        data = b"plugins: []\n"
        checksum = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "masterlist.yaml"
            result = loot_sort.ensure_masterlist(
                cache,
                "https://example.invalid/pinned",
                checksum,
                True,
                opener=mock.Mock(return_value=_Response(data)),
            )
            self.assertEqual(result, cache)
            self.assertEqual(cache.read_bytes(), data)
            self.assertEqual(list(cache.parent.glob(".masterlist.yaml.*")), [])

    def test_checksum_mismatch_does_not_create_or_replace_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "masterlist.yaml"
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                loot_sort.ensure_masterlist(
                    cache,
                    "https://example.invalid/pinned",
                    "0" * 64,
                    True,
                    opener=mock.Mock(return_value=_Response(b"tampered")),
                )
            self.assertFalse(cache.exists())

    def test_verified_pinned_cache_is_used_offline(self) -> None:
        data = b"plugins: []\n"
        checksum = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "masterlist.yaml"
            cache.write_bytes(data)
            opener = mock.Mock(side_effect=OSError("offline"))

            result = loot_sort.ensure_masterlist(
                cache, "https://example.invalid/pinned", checksum, True, opener
            )
            self.assertEqual(result, cache)
            opener.assert_not_called()

    def test_download_failure_without_cache_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "masterlist.yaml"
            result = loot_sort.ensure_masterlist(
                cache,
                "https://example.invalid/pinned",
                "0" * 64,
                True,
                mock.Mock(side_effect=OSError("offline")),
            )
            self.assertIsNone(result)
            self.assertFalse(cache.exists())


class OpenMWLootIntegrationBoundaryTests(unittest.TestCase):
    def test_missing_state_backed_adapter_aborts_before_mutation(self) -> None:
        feature = SimpleNamespace(writePluginLists=mock.Mock())
        organizer = SimpleNamespace(
            gameFeatures=lambda: SimpleNamespace(
                gameFeature=lambda feature_type: feature
            )
        )
        tool = loot_sort.OpenMWSortWithLoot()
        tool._organizer = organizer
        plugin_list = SimpleNamespace(setLoadOrder=mock.Mock())

        with self.assertRaisesRegex(RuntimeError, "state-backed LOOT"):
            tool._loot_snapshot(plugin_list)
        plugin_list.setLoadOrder.assert_not_called()
        feature.writePluginLists.assert_not_called()

    def test_confirmation_cancellation_is_non_mutating(self) -> None:
        tool = loot_sort.OpenMWSortWithLoot()
        with mock.patch.object(
            loot_sort.QMessageBox,
            "question",
            return_value=loot_sort.QMessageBox.StandardButton.No,
            create=True,
        ):
            self.assertFalse(tool._confirm_sort())

    def test_apply_delegates_complete_order_to_transaction_adapter(self) -> None:
        slots = (
            loot_sort.PluginSlot("Morrowind.esm", True, primary=True),
            loot_sort.PluginSlot("Inactive.esp", False),
            loot_sort.PluginSlot("A.esp", True),
            loot_sort.PluginSlot("B.esp", True),
        )
        feature = SimpleNamespace(applyLootOrder=mock.Mock(return_value=True))
        organizer = SimpleNamespace(refresh=mock.Mock())
        tool = loot_sort.OpenMWSortWithLoot()
        tool._organizer = organizer
        plugin_list = object()

        moved = tool._apply(
            plugin_list,
            feature,
            "revision-1",
            slots,
            ["Morrowind.esm", "B.esp", "A.esp"],
            ["Morrowind.esm"],
        )
        self.assertEqual(moved, 2)
        feature.applyLootOrder.assert_called_once_with(
            plugin_list,
            "revision-1",
            ["Morrowind.esm", "Inactive.esp", "B.esp", "A.esp"],
        )
        organizer.refresh.assert_called_once_with()

    def test_libloot_process_is_mocked_and_receives_exact_request(self) -> None:
        worker = loot_sort._LootWorker(
            "/game",
            None,
            ["/data"],
            ["Morrowind.esm", "A.esp"],
            ["Morrowind.esm", "A.esp", "Fixed.esp"],
            None,
            loot_sort._DEFAULT_MASTERLIST_URL,
            loot_sort._DEFAULT_MASTERLIST_SHA256,
            False,
        )

        def fake_run(arguments, **kwargs):
            request = json.loads(Path(arguments[2]).read_text(encoding="utf-8"))
            self.assertEqual(request["active"], ["Morrowind.esm", "A.esp"])
            self.assertEqual(
                request["condition_active"],
                ["Morrowind.esm", "A.esp", "Fixed.esp"],
            )
            Path(arguments[3]).write_text(
                json.dumps({"sorted": ["Morrowind.esm", "A.esp"], "error": ""}),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout=b"")

        with mock.patch.object(
            worker, "_find_interpreter", return_value="python3"
        ), mock.patch.object(loot_sort.subprocess, "run", side_effect=fake_run):
            self.assertEqual(
                worker._sort_in_subprocess(
                    ["/data/Morrowind.esm", "/data/A.esp"], None
                ),
                ["Morrowind.esm", "A.esp"],
            )
        self.assertIn(
            "load_current_load_order_state", loot_sort._LOOT_SUBPROCESS_SRC
        )


if __name__ == "__main__":
    unittest.main()
