from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable, NamedTuple


_PROBE_SCRIPT = r"""
while [ "$#" -ge 3 ]; do
    required=$1
    expected=$2
    path=$3
    shift 3

    actual=$(stat -Lc '%d:%i' -- "$path" 2>/dev/null) || {
        printf 'hidden\000'
        continue
    }
    if [ "$actual" != "$expected" ] ||
       [ ! -d "$path" ] || [ ! -r "$path" ] || [ ! -x "$path" ]; then
        printf 'hidden\000'
    elif [ "$required" = rw ] && [ ! -w "$path" ]; then
        printf 'read-only\000'
    else
        printf 'ok\000'
    fi
done
[ "$#" -eq 0 ] || exit 64
"""


class PathRequirement(NamedTuple):
    path: Path
    writable: bool


class AccessFailure(NamedTuple):
    requirement: PathRequirement
    status: str


def merge_requirements(
    requirements: Iterable[PathRequirement],
) -> list[PathRequirement]:
    result: list[PathRequirement] = []
    positions: dict[str, int] = {}
    for requirement in requirements:
        path = Path(os.path.abspath(requirement.path))
        key = os.path.normcase(str(path))
        normalized = PathRequirement(path, requirement.writable)
        if key not in positions:
            positions[key] = len(result)
            result.append(normalized)
        elif requirement.writable and not result[positions[key]].writable:
            result[positions[key]] = normalized
    return result


def parse_probe_output(
    output: bytes, requirements: list[PathRequirement]
) -> list[AccessFailure]:
    records = output.split(b"\0")
    if not records or records[-1] != b"":
        raise RuntimeError("Flatpak access probe returned unterminated output")
    records.pop()
    if len(records) != len(requirements):
        raise RuntimeError(
            "Flatpak access probe returned an unexpected result count: "
            f"expected {len(requirements)}, got {len(records)}"
        )

    failures: list[AccessFailure] = []
    for requirement, raw_status in zip(requirements, records):
        try:
            status = raw_status.decode("ascii")
        except UnicodeDecodeError as error:
            raise RuntimeError("Flatpak access probe returned invalid output") from error
        if status not in {"ok", "hidden", "read-only"}:
            raise RuntimeError(
                f"Flatpak access probe returned an unknown status: {status!r}"
            )
        if status == "hidden" or (status == "read-only" and requirement.writable):
            failures.append(AccessFailure(requirement, status))
    return failures


def probe_flatpak_access(
    flatpak: str,
    app_id: str,
    requirements: Iterable[PathRequirement],
    timeout: float = 30,
) -> list[AccessFailure]:
    requirements = merge_requirements(requirements)
    arguments = [
        flatpak,
        "run",
        "--command=sh",
        app_id,
        "-c",
        _PROBE_SCRIPT,
        "fluorine-flatpak-preflight",
    ]
    for requirement in requirements:
        try:
            stat = requirement.path.stat()
        except OSError as error:
            raise RuntimeError(
                f"Required OpenMW path is unavailable: {requirement.path}: {error}"
            ) from error
        if not requirement.path.is_dir():
            raise RuntimeError(
                f"Required OpenMW path is not a directory: {requirement.path}"
            )
        arguments.extend(
            (
                "rw" if requirement.writable else "ro",
                f"{stat.st_dev}:{stat.st_ino}",
                str(requirement.path),
            )
        )

    try:
        completed = subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"Unable to run Flatpak access probe: {error}") from error
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        detail = f": {stderr}" if stderr else ""
        raise RuntimeError(
            f"Flatpak access probe exited with code {completed.returncode}{detail}"
        )
    return parse_probe_output(completed.stdout, requirements)


def format_access_failures(failures: Iterable[AccessFailure], limit: int = 10) -> str:
    failures = list(failures)
    lines: list[str] = []
    for failure in failures[:limit]:
        required = "read/write" if failure.requirement.writable else "read"
        lines.append(
            f"{failure.requirement.path} requires {required} access "
            f"(sandbox status: {failure.status})"
        )
    omitted = len(failures) - limit
    if omitted > 0:
        lines.append(f"(+{omitted} more inaccessible paths)")
    return "\n".join(lines)
