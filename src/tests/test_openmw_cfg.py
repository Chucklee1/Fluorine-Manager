from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = (
    Path(__file__).parents[2]
    / "libs"
    / "basic_games"
    / "games"
    / "openmw_support"
    / "openmw_cfg.py"
)
SPEC = importlib.util.spec_from_file_location("openmw_cfg", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {MODULE_PATH}")
openmw_cfg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(openmw_cfg)


class OpenMWConfigTests(unittest.TestCase):
    def test_selects_only_the_launch_type_config_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            native = directory / "native" / "openmw.cfg"
            flatpak = directory / "flatpak" / "openmw.cfg"
            flatpak.parent.mkdir()
            flatpak.write_text("flatpak\n", encoding="utf-8")

            self.assertIsNone(openmw_cfg.find_openmw_cfg(native, flatpak, False))
            self.assertEqual(
                openmw_cfg.find_openmw_cfg(native, flatpak, True), flatpak
            )

            native.parent.mkdir()
            native.write_text("native\n", encoding="utf-8")
            self.assertEqual(
                openmw_cfg.find_openmw_cfg(native, flatpak, False), native
            )

    def test_normalizes_openmw_player_stub_loadorder(self) -> None:
        self.assertEqual(
            openmw_cfg.normalize_plugin_loadorder(
                [
                    "Addon.omwaddon.esp",
                    "addon.OMWADDON.ESP",
                    "Game.omwgame.ESP",
                    "Scripts.OMWSCRIPTS.esp",
                    "Ordinary.esp",
                ]
            ),
            [
                "Addon.omwaddon",
                "Game.omwgame",
                "Scripts.OMWSCRIPTS",
                "Ordinary.esp",
            ],
        )
        self.assertTrue(openmw_cfg.is_openmw_player_stub("Addon.OMWADDON.esp"))
        self.assertFalse(openmw_cfg.is_openmw_player_stub("Ordinary.esp"))

    def test_loadorder_keeps_ranked_plugins_before_unranked_plugins(self) -> None:
        self.assertEqual(
            openmw_cfg.order_plugins_by_loadorder(
                ["Unranked.omwaddon", "Ranked.omwaddon"],
                ["Duplicate.esp", "duplicate.ESP", "Ranked.omwaddon.esp"],
            ),
            ["Ranked.omwaddon", "Unranked.omwaddon"],
        )

    def test_loadorder_collapses_duplicate_providers(self) -> None:
        self.assertEqual(
            openmw_cfg.order_plugins_by_loadorder(
                ["Addon.omwaddon", "ADDON.OMWADDON"],
                ["Addon.omwaddon.esp"],
            ),
            ["ADDON.OMWADDON"],
        )

    def test_reports_only_unranked_native_content(self) -> None:
        self.assertEqual(
            openmw_cfg.unranked_native_plugins(
                [
                    "Ranked.omwaddon",
                    "Unranked.omwscripts",
                    "Ordinary.esp",
                    "Master.esm",
                    "UNRANKED.OMWSCRIPTS",
                ],
                ["Ranked.omwaddon.esp"],
            ),
            ["Unranked.omwscripts"],
        )
        self.assertEqual(
            openmw_cfg.unranked_native_plugins(
                ["Unranked.omwscripts"], []
            ),
            [],
        )

    def test_formats_bounded_unranked_name_sample(self) -> None:
        self.assertEqual(
            openmw_cfg.format_name_sample(["One", "Two", "Three"], limit=2),
            "'One', 'Two' (+1 more)",
        )

    def test_reads_curated_selection_and_deduplicates_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cfg_path = Path(temporary) / "openmw.cfg"
            cfg_path.write_text(
                "\n".join(
                    (
                        "# preserved profile selection",
                        " Content = Enabled.esp ",
                        "content=enabled.ESP",
                        "groundcover=Grass.esp",
                        "fallback-archive=Morrowind.bsa",
                        "Fallback-Archive=Morrowind - Invalidation.bsa",
                        "data=/ignored",
                    )
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                openmw_cfg.read_openmw_selection(cfg_path),
                {
                    "content": ["Enabled.esp"],
                    "groundcover": ["Grass.esp"],
                    "fallback-archive": [
                        "Morrowind.bsa",
                        "Morrowind - Invalidation.bsa",
                    ],
                },
            )

    def test_filters_curated_content_activation(self) -> None:
        available = [
            "Enabled.esp",
            "Siege at Firemoth.esp",
            "Helm of Tohan Naturalized.esp",
            "Grass.esp",
        ]
        configured = ["Enabled.esp", "Grass.esp"]

        self.assertEqual(
            openmw_cfg.filter_selected_files(available, configured),
            ["Enabled.esp", "Grass.esp"],
        )

    def test_preserves_curated_archive_order(self) -> None:
        available = [
            "Bloodmoon.bsa",
            "Morrowind - Invalidation.bsa",
            "dynamicsounds.bsa",
            "Morrowind.bsa",
            "Protection From Sun Damage.bsa",
            "Tribunal.bsa",
            "Hiding Vampirism Under Helmets.bsa",
            "Disabled.bsa",
        ]
        configured = [
            "Morrowind.bsa",
            "Tribunal.bsa",
            "Bloodmoon.bsa",
            "Morrowind - Invalidation.bsa",
            "Hiding Vampirism Under Helmets.bsa",
            "Protection From Sun Damage.bsa",
            "dynamicsounds.bsa",
        ]

        self.assertEqual(
            openmw_cfg.order_selected_files(available, configured),
            configured,
        )

    def test_migrates_curated_profile_to_durable_selection(self) -> None:
        configured = {
            "content": ["Morrowind.esm", "Enabled.esp"],
            "groundcover": ["Grass.esp"],
            "fallback-archive": [
                "Morrowind.bsa",
                "Tribunal.bsa",
                "Bloodmoon.bsa",
                "Morrowind - Invalidation.bsa",
                "Enabled Mod.bsa",
            ],
        }
        available_plugins = [
            "Enabled.esp",
            "Siege at Firemoth.esp",
            "Helm of Tohan Naturalized.esp",
            "Grass.esp",
        ]
        state = openmw_cfg.create_selection_state(
            configured,
            loadorder=available_plugins,
            available_plugins=available_plugins,
            available_archives=[
                "Morrowind.bsa",
                "Tribunal.bsa",
                "Bloodmoon.bsa",
                "Morrowind - Invalidation.bsa",
                "Enabled Mod.bsa",
                "Disabled Mod.bsa",
            ],
            supplemental_archives=["Morrowind - Invalidation.bsa"],
        )

        self.assertEqual(
            openmw_cfg.filter_selected_files(
                available_plugins, state["enabled_plugins"]
            ),
            ["Enabled.esp", "Grass.esp"],
        )
        self.assertEqual(state["groundcover"], ["Grass.esp"])
        self.assertNotIn("Disabled Mod.bsa", state["archives"])
        self.assertIn("Siege at Firemoth.esp", state["known_plugins"])
        self.assertNotIn("Siege at Firemoth.esp", state["enabled_plugins"])

    def test_selection_survives_missing_files_and_enables_new_files(self) -> None:
        state = openmw_cfg.create_selection_state(
            {
                "content": ["Enabled.esp"],
                "groundcover": ["Grass.esp"],
                "fallback-archive": ["Enabled.bsa"],
            },
            loadorder=["Enabled.esp", "Disabled.esp", "Grass.esp"],
            available_plugins=["Enabled.esp", "Disabled.esp", "Grass.esp"],
            available_archives=["Enabled.bsa", "Disabled.bsa"],
        )

        self.assertFalse(
            openmw_cfg.update_selection_state(
                state,
                available_plugins=["Disabled.esp"],
                available_archives=["Disabled.bsa"],
                groundcover=["Grass.esp"],
            )
        )
        self.assertIn("Enabled.esp", state["enabled_plugins"])
        self.assertIn("Enabled.bsa", state["archives"])

        self.assertTrue(
            openmw_cfg.update_selection_state(
                state,
                available_plugins=["Enabled.esp", "New.omwaddon"],
                available_archives=["Enabled.bsa", "New.bsa"],
                groundcover=["Grass.esp"],
            )
        )
        self.assertIn("New.omwaddon", state["enabled_plugins"])
        self.assertIn("New.bsa", state["archives"])
        self.assertNotIn("Disabled.esp", state["enabled_plugins"])
        self.assertNotIn("Disabled.bsa", state["archives"])

    def test_selection_state_round_trips_atomically(self) -> None:
        state = openmw_cfg.create_selection_state(
            {
                "content": ["Enabled.esp"],
                "groundcover": [],
                "fallback-archive": ["Enabled.bsa"],
            },
            loadorder=["Enabled.esp"],
            available_plugins=["Enabled.esp"],
            available_archives=["Enabled.bsa"],
        )
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "fluorine-openmw-selection.json"
            openmw_cfg.write_selection_state(state_path, state)

            self.assertEqual(openmw_cfg.read_selection_state(state_path), state)
            self.assertTrue(state_path.read_text(encoding="utf-8").endswith("\n"))

    def test_migrates_version_one_selection_state(self) -> None:
        state_v1 = {
            "version": 1,
            "known_plugins": ["Known.esp"],
            "enabled_plugins": ["Known.esp"],
            "groundcover": [],
            "known_archives": ["Known.bsa"],
            "archives": ["Known.bsa"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "fluorine-openmw-selection.json"
            state_path.write_text(json.dumps(state_v1), encoding="utf-8")
            state = openmw_cfg.read_selection_state(state_path)
            self.assertIsNotNone(state)

            self.assertTrue(openmw_cfg.upgrade_selection_state(state))
            self.assertEqual(state["version"], 2)
            self.assertEqual(state["profile_config_entries"], [])
            self.assertFalse(state["profile_config_entries_known"])
            self.assertFalse(state["profile_config_terminal"])
            self.assertFalse(openmw_cfg.upgrade_selection_state(state))

    def test_suspends_and_restores_exact_profile_config_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cfg_path = Path(temporary) / "openmw.cfg"
            entries = [
                '  Config = "../Nested &"Config"  ',
                "config=?local?/nested",
                "config=?local?/nested",
            ]
            cfg_path.write_text(
                "setting=value\n" + "\n".join(entries) + "\ncontent=Old.esp\n",
                encoding="utf-8",
            )
            state = openmw_cfg.create_selection_state(
                {
                    "content": ["Old.esp"],
                    "groundcover": [],
                    "fallback-archive": [],
                },
                loadorder=["Old.esp"],
                available_plugins=["Old.esp"],
                available_archives=[],
            )

            self.assertTrue(
                openmw_cfg.suspend_profile_config_entries(state, cfg_path)
            )
            self.assertEqual(state["profile_config_entries"], entries)
            self.assertTrue(state["profile_config_entries_known"])
            self.assertTrue(state["profile_config_terminal"])

            openmw_cfg.write_openmw_cfg(
                cfg_path,
                data_dirs=["/data"],
                content_plugins=["Old.esp"],
                strip_config=True,
                vanilla_masters=(),
                vanilla_bsas=(),
            )
            self.assertEqual(
                openmw_cfg.capture_profile_config_entries(cfg_path), []
            )
            self.assertFalse(
                openmw_cfg.suspend_profile_config_entries(state, cfg_path)
            )

            self.assertTrue(
                openmw_cfg.restore_profile_config_entries(
                    cfg_path, state["profile_config_entries"]
                )
            )
            self.assertEqual(
                openmw_cfg.capture_profile_config_entries(cfg_path), entries
            )
            self.assertFalse(
                openmw_cfg.restore_profile_config_entries(
                    cfg_path, state["profile_config_entries"]
                )
            )

    def test_restores_entries_captured_with_unknown_legacy_backup(self) -> None:
        state = openmw_cfg.create_selection_state(
            {"content": [], "groundcover": [], "fallback-archive": []},
            loadorder=[],
            available_plugins=[],
            available_archives=[],
        )
        state["profile_config_entries_known"] = False
        state["profile_config_terminal"] = True
        with tempfile.TemporaryDirectory() as temporary:
            cfg_path = Path(temporary) / "openmw.cfg"
            cfg_path.write_text("config=../re-added\n", encoding="utf-8")

            self.assertTrue(
                openmw_cfg.suspend_profile_config_entries(state, cfg_path)
            )
            self.assertFalse(state["profile_config_entries_known"])
            self.assertEqual(
                state["profile_config_entries"], ["config=../re-added"]
            )
            openmw_cfg.write_openmw_cfg(
                cfg_path,
                data_dirs=["/data"],
                content_plugins=[],
                strip_config=True,
                vanilla_masters=(),
                vanilla_bsas=(),
            )

            self.assertTrue(
                openmw_cfg.restore_profile_config_entries(
                    cfg_path, state["profile_config_entries"]
                )
            )
            self.assertEqual(
                openmw_cfg.capture_profile_config_entries(cfg_path),
                ["config=../re-added"],
            )

    def test_profile_selector_path_round_trips_escaped_characters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cfg_path = directory / "openmw.cfg"
            profile_path = directory / 'Profile & "Quoted"'

            openmw_cfg.write_profile_selector(cfg_path, profile_path)

            self.assertEqual(
                openmw_cfg.read_profile_selector(cfg_path),
                profile_path.resolve(strict=False),
            )

    def test_config_restoration_rolls_back_with_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cfg_path = directory / "openmw.cfg"
            state_path = directory / "fluorine-openmw-selection.json"
            cfg_path.write_text("terminal=true\n", encoding="utf-8")
            state = openmw_cfg.create_selection_state(
                {"content": [], "groundcover": [], "fallback-archive": []},
                loadorder=[],
                available_plugins=[],
                available_archives=[],
            )
            state["profile_config_entries"] = ["config=../nested"]
            state["profile_config_terminal"] = True
            openmw_cfg.write_selection_state(state_path, state)
            original_state = state_path.read_text(encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "injected failure"):
                with openmw_cfg.rollback_file_changes([cfg_path, state_path]):
                    openmw_cfg.restore_profile_config_entries(
                        cfg_path, state["profile_config_entries"]
                    )
                    state["profile_config_terminal"] = False
                    openmw_cfg.write_selection_state(state_path, state)
                    raise RuntimeError("injected failure")

            self.assertEqual(
                cfg_path.read_text(encoding="utf-8"), "terminal=true\n"
            )
            self.assertEqual(state_path.read_text(encoding="utf-8"), original_state)

    def test_transaction_rolls_back_existing_and_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cfg_path = directory / "openmw.cfg"
            launcher_path = directory / "launcher.cfg"
            state_path = directory / "fluorine-openmw-selection.json"
            cfg_path.write_text("original config\n", encoding="utf-8")
            launcher_path.write_text("original launcher\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "injected failure"):
                with openmw_cfg.rollback_file_changes(
                    [cfg_path, launcher_path, state_path, cfg_path]
                ):
                    openmw_cfg._write_lines(cfg_path, ["new config"])
                    openmw_cfg._write_lines(launcher_path, ["new launcher"])
                    openmw_cfg._write_lines(state_path, ["new state"])
                    raise RuntimeError("injected failure")

            self.assertEqual(
                cfg_path.read_text(encoding="utf-8"), "original config\n"
            )
            self.assertEqual(
                launcher_path.read_text(encoding="utf-8"), "original launcher\n"
            )
            self.assertFalse(state_path.exists())
            self.assertEqual(list(directory.glob(".*.rollback")), [])

    def test_transaction_commits_and_removes_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cfg_path = directory / "openmw.cfg"
            cfg_path.write_text("original\n", encoding="utf-8")

            with openmw_cfg.rollback_file_changes([cfg_path]):
                backups = list(directory.glob(".*.rollback"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(os.stat(backups[0]).st_ino, os.stat(cfg_path).st_ino)
                openmw_cfg._write_lines(cfg_path, ["committed"])

            self.assertEqual(cfg_path.read_text(encoding="utf-8"), "committed\n")
            self.assertEqual(list(directory.glob(".*.rollback")), [])

    def test_transaction_restores_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            target_path = directory / "target.cfg"
            link_path = directory / "openmw.cfg"
            target_path.write_text("original\n", encoding="utf-8")
            try:
                link_path.symlink_to(target_path)
            except OSError as error:
                self.skipTest(f"Symlinks unavailable: {error}")

            with self.assertRaisesRegex(RuntimeError, "injected failure"):
                with openmw_cfg.rollback_file_changes([link_path]):
                    openmw_cfg._write_lines(link_path, ["changed"])
                    raise RuntimeError("injected failure")

            self.assertTrue(link_path.is_symlink())
            self.assertEqual(target_path.read_text(encoding="utf-8"), "original\n")
            self.assertEqual(list(directory.glob(".*.rollback")), [])

    def test_late_marker_failure_restores_earlier_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cfg_path = directory / "profile.cfg"
            root_path = directory / "root.cfg"
            cfg_path.write_text("original profile\n", encoding="utf-8")
            root_path.write_text(
                "# BEGIN FLUORINE OPENMW LOCAL SAVES\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "without a matching"):
                with openmw_cfg.rollback_file_changes([cfg_path, root_path]):
                    openmw_cfg._write_lines(cfg_path, ["changed profile"])
                    openmw_cfg.write_local_saves(root_path, None)

            self.assertEqual(
                cfg_path.read_text(encoding="utf-8"), "original profile\n"
            )
            self.assertEqual(
                root_path.read_text(encoding="utf-8"),
                "# BEGIN FLUORINE OPENMW LOCAL SAVES\n",
            )

    def test_rejects_export_roles_aliased_through_parent_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            real_profile = directory / "real-profile"
            alias_profile = directory / "alias-profile"
            real_profile.mkdir()
            try:
                alias_profile.symlink_to(real_profile, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"Symlinks unavailable: {error}")

            with self.assertRaisesRegex(ValueError, "resolve to the same file"):
                openmw_cfg.validate_file_roles(
                    {
                        "root config": real_profile / "openmw.cfg",
                        "profile config": alias_profile / "openmw.cfg",
                    }
                )

    def test_rejects_absent_transaction_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing_path = Path(temporary) / "missing" / "openmw.cfg"

            with self.assertRaisesRegex(ValueError, "parent does not exist"):
                with openmw_cfg.rollback_file_changes([missing_path]):
                    self.fail("Transaction should not start")

            self.assertFalse(missing_path.parent.exists())

    def test_removes_partial_copy_when_snapshot_creation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cfg_path = directory / "openmw.cfg"
            cfg_path.write_text("original\n", encoding="utf-8")

            def fail_after_partial_copy(_source, destination):
                Path(destination).write_text("partial", encoding="utf-8")
                raise OSError("injected copy failure")

            with mock.patch.object(
                openmw_cfg.os, "link", side_effect=OSError("no hard links")
            ), mock.patch.object(
                openmw_cfg.shutil, "copy2", side_effect=fail_after_partial_copy
            ):
                with self.assertRaisesRegex(OSError, "injected copy failure"):
                    with openmw_cfg.rollback_file_changes([cfg_path]):
                        self.fail("Transaction should not start")

            self.assertEqual(cfg_path.read_text(encoding="utf-8"), "original\n")
            self.assertEqual(list(directory.glob(".*.rollback")), [])

    def test_profile_block_preserves_inherited_data(self) -> None:
        block = openmw_cfg.build_managed_block(
            ["/game/Data Files", "/mods/example"],
            ["Example.esp"],
            replace_managed=True,
        )

        self.assertEqual(
            [line for line in block if line.startswith("replace=")],
            [
                "replace=content",
                "replace=fallback-archive",
                "replace=groundcover",
            ],
        )
        self.assertNotIn("replace=data", block)
        self.assertIn('data="/game/Data Files"', block)
        self.assertIn('data="/mods/example"', block)

    def test_profile_rewrite_removes_stale_data_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cfg_path = Path(temporary) / "openmw.cfg"
            cfg_path.write_text(
                "\n".join(
                    (
                        'resources="/keep/resources"',
                        "replace=config",
                        "replace = DATA",
                        "replace=content",
                        "replace=groundcover",
                        "replace=fallback-archive",
                        'data="/stale/data"',
                        "content=Stale.esp",
                        "groundcover=StaleGrass.esp",
                        "fallback-archive=Stale.bsa",
                        "",
                    )
                ),
                encoding="utf-8",
            )

            def rewrite() -> str:
                openmw_cfg.write_openmw_cfg(
                    cfg_path,
                    data_dirs=["/game/Data Files", "/mods/current"],
                    content_plugins=["Current.esp"],
                    replace_managed=True,
                    vanilla_masters=(),
                    vanilla_bsas=(),
                )
                return cfg_path.read_text(encoding="utf-8")

            first = rewrite()
            second = rewrite()

            self.assertEqual(first, second)
            self.assertIn('resources="/keep/resources"', first)
            self.assertIn("replace=config", first)
            self.assertNotIn("replace=data", first.lower().replace(" ", ""))
            self.assertEqual(first.count("replace=content\n"), 1)
            self.assertEqual(first.count("replace=fallback-archive\n"), 1)
            self.assertEqual(first.count("replace=groundcover\n"), 1)
            self.assertNotIn("/stale/data", first)
            self.assertNotIn("Stale.esp", first)
            self.assertNotIn("StaleGrass.esp", first)
            self.assertNotIn("Stale.bsa", first)
            self.assertEqual(first.count("data="), 2)
            self.assertIn('data="/game/Data Files"', first)
            self.assertIn('data="/mods/current"', first)
            self.assertIn("content=Current.esp", first)


if __name__ == "__main__":
    unittest.main()
