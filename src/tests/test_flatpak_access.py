from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


MODULE_PATH = (
    Path(__file__).parents[2]
    / "libs"
    / "basic_games"
    / "games"
    / "openmw_support"
    / "flatpak_access.py"
)
SPEC = importlib.util.spec_from_file_location("flatpak_access", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {MODULE_PATH}")
flatpak_access = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(flatpak_access)


class FlatpakAccessTests(unittest.TestCase):
    def test_merges_duplicate_paths_using_stronger_requirement(self) -> None:
        path = Path("/tmp/example")

        self.assertEqual(
            flatpak_access.merge_requirements(
                [
                    flatpak_access.PathRequirement(path, False),
                    flatpak_access.PathRequirement(path, True),
                ]
            ),
            [flatpak_access.PathRequirement(path, True)],
        )

    def test_parses_hidden_and_read_only_results(self) -> None:
        requirements = [
            flatpak_access.PathRequirement(Path("/read-only-data"), False),
            flatpak_access.PathRequirement(Path("/hidden-data"), False),
            flatpak_access.PathRequirement(Path("/writable-profile"), True),
        ]

        failures = flatpak_access.parse_probe_output(
            b"read-only\0hidden\0read-only\0", requirements
        )

        self.assertEqual(
            failures,
            [
                flatpak_access.AccessFailure(requirements[1], "hidden"),
                flatpak_access.AccessFailure(requirements[2], "read-only"),
            ],
        )

    def test_rejects_malformed_probe_output(self) -> None:
        requirement = flatpak_access.PathRequirement(Path("/data"), False)
        with self.assertRaisesRegex(RuntimeError, "unterminated"):
            flatpak_access.parse_probe_output(b"ok", [requirement])
        with self.assertRaisesRegex(RuntimeError, "result count"):
            flatpak_access.parse_probe_output(b"ok\0hidden\0", [requirement])
        with self.assertRaisesRegex(RuntimeError, "unknown status"):
            flatpak_access.parse_probe_output(b"surprise\0", [requirement])

    def test_probes_all_paths_in_one_flatpak_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / 'Data Files "quoted"'
            profile = root / "Profile\nWith Newline"
            data.mkdir()
            profile.mkdir()
            completed = SimpleNamespace(
                returncode=0,
                stdout=b"ok\0read-only\0",
                stderr=b"",
            )

            with mock.patch.object(
                flatpak_access.subprocess, "run", return_value=completed
            ) as run:
                failures = flatpak_access.probe_flatpak_access(
                    "/usr/bin/flatpak",
                    "org.openmw.OpenMW",
                    [
                        flatpak_access.PathRequirement(data, False),
                        flatpak_access.PathRequirement(profile, True),
                    ],
                )

            self.assertEqual(
                failures,
                [
                    flatpak_access.AccessFailure(
                        flatpak_access.PathRequirement(profile, True),
                        "read-only",
                    )
                ],
            )
            run.assert_called_once()
            arguments = run.call_args.args[0]
            self.assertIn(str(data), arguments)
            self.assertIn(str(profile), arguments)
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_reports_probe_process_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            with mock.patch.object(
                flatpak_access.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("flatpak", 30),
            ):
                with self.assertRaisesRegex(RuntimeError, "Unable to run"):
                    flatpak_access.probe_flatpak_access(
                        "flatpak",
                        "org.openmw.OpenMW",
                        [flatpak_access.PathRequirement(path, False)],
                    )

            completed = SimpleNamespace(
                returncode=1,
                stdout=b"",
                stderr=b"not installed",
            )
            with mock.patch.object(
                flatpak_access.subprocess, "run", return_value=completed
            ):
                with self.assertRaisesRegex(RuntimeError, "not installed"):
                    flatpak_access.probe_flatpak_access(
                        "flatpak",
                        "org.openmw.OpenMW",
                        [flatpak_access.PathRequirement(path, False)],
                    )


if __name__ == "__main__":
    unittest.main()
