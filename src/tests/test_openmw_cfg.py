from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


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
