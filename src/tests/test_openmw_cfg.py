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
