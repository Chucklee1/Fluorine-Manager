"""
openmw_cfg.py — generate the managed block of an ``openmw.cfg``.

OpenMW does not use a separate VFS injector: it reads its mods directly from an
ordered list of ``data=`` directories and loads plugins in the order of the
``content=`` lines.  This module rewrites *only* the keys we own, leaving every
other line (engine settings, comments, unrelated keys) untouched:

    data=               asset/plugin search dirs; LATER entries override earlier
    content=            ordered plugin load list (.esp/.esm/.omwaddon/.omwscripts)
    groundcover=        grass/groundcover plugins (kept out of content= for perf)
    fallback-archive=   .bsa archives; later entries override earlier

It is deliberately pure standard library (no Qt / mobase) so it can be unit
tested on its own and reused by the OpenMW game plugin.  The caller decides what
goes into ``data_dirs`` — a single merged dir (Fluorine FUSE) or one entry per
mod (native OpenMW VFS) — this module stays agnostic about that choice.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import tempfile
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Iterable, Iterator, TextIO, TypedDict

# Morrowind masters, in canonical load order.
#
# Do NOT list ``builtin.omwscripts`` here.  It is OpenMW's built-in Lua bundle,
# shipped inside the engine's ``resources/vfs-mw`` and loaded *implicitly* by the
# engine itself.  If we also emit ``content=builtin.omwscripts`` it ends up
# specified twice across the config chain and OpenMW aborts on startup with
# "Content file specified more than once: builtin.omwscripts. Aborting...".
VANILLA_MASTERS: list[str] = [
    "Morrowind.esm",
    "Tribunal.esm",
    "Bloodmoon.esm",
]

# Vanilla BSAs, always emitted as the lowest-priority fallback-archive entries.
VANILLA_BSAS: list[str] = [
    "Morrowind.bsa",
    "Tribunal.bsa",
    "Bloodmoon.bsa",
]

# Keys this module fully owns (lowercase, exact match).
_MANAGED_KEYS = frozenset({"data", "content", "groundcover", "fallback-archive"})
# The global OpenMW config contributes its required resources/vfs-mw data dir.
# Keep inherited data entries while replacing the other generated lists.
_REPLACED_MANAGED_KEYS = _MANAGED_KEYS - {"data"}

_PROFILE_BEGIN = "# BEGIN FLUORINE OPENMW PROFILE"
_PROFILE_END = "# END FLUORINE OPENMW PROFILE"
_LOCAL_SAVES_BEGIN = "# BEGIN FLUORINE OPENMW LOCAL SAVES"
_LOCAL_SAVES_END = "# END FLUORINE OPENMW LOCAL SAVES"
_LOCAL_SAVES_ORIGINAL = "# FLUORINE ORIGINAL USER-DATA "

_SELECTION_KEYS = ("content", "groundcover", "fallback-archive")
_SELECTION_STATE_VERSION = 2
_OPENMW_NATIVE_SUFFIXES = (".omwaddon", ".omwgame", ".omwscripts")
_OPENMW_PLAYER_STUB_SUFFIXES = tuple(
    suffix + ".esp" for suffix in _OPENMW_NATIVE_SUFFIXES
)


class OpenMWSelectionState(TypedDict):
    version: int
    known_plugins: list[str]
    enabled_plugins: list[str]
    groundcover: list[str]
    known_archives: list[str]
    archives: list[str]
    profile_config_entries: list[str]
    profile_config_entries_known: bool
    profile_config_terminal: bool


def find_openmw_cfg(
    native_cfg: Path, flatpak_cfg: Path, flatpak_launch: bool
) -> Path | None:
    candidate = flatpak_cfg if flatpak_launch else native_cfg
    return candidate if candidate.is_file() else None


def escape_data_path(path: str) -> str:
    """Quote/escape a path for a ``data=`` line.

    openmw.cfg uses boost::filesystem quoting: ``&`` and ``"`` are escaped with a
    leading ``&`` and the whole value is wrapped in double quotes.  This matches
    AnyOldName3's MO2 exporter so paths containing spaces or quotes round-trip.
    """
    out = ['"']
    for ch in path:
        if ch in ("&", '"'):
            out.append("&")
        out.append(ch)
    out.append('"')
    return "".join(out)


def _is_managed(line: str) -> bool:
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
        return False
    return s.split("=", 1)[0].strip().lower() in _MANAGED_KEYS


def _read_lines(cfg_path: Path) -> list[str]:
    if not cfg_path.is_file():
        return []
    return cfg_path.read_text(encoding="utf-8", errors="replace").splitlines()


def read_openmw_selection(cfg_path: Path) -> dict[str, list[str]]:
    """Read the ordered plugin and archive selections from an OpenMW config."""
    result = {key: [] for key in _SELECTION_KEYS}
    seen = {key: set() for key in _SELECTION_KEYS}
    for raw in _read_lines(cfg_path):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key not in result or not value:
            continue
        folded = value.casefold()
        if folded not in seen[key]:
            seen[key].add(folded)
            result[key].append(value)
    return result


def filter_selected_files(
    available: Iterable[str], selected: Iterable[str]
) -> list[str]:
    """Keep available files selected by name, preserving available-file order."""
    selected_keys = {name.casefold() for name in selected}
    return [name for name in available if name.casefold() in selected_keys]


def order_selected_files(
    available: Iterable[str], selected: Iterable[str]
) -> list[str]:
    """Return selected available files in selection order and provider casing."""
    available_by_name: dict[str, str] = {}
    for name in available:
        available_by_name[name.casefold()] = name

    result: list[str] = []
    emitted: set[str] = set()
    for name in selected:
        folded = name.casefold()
        if folded in available_by_name and folded not in emitted:
            emitted.add(folded)
            result.append(available_by_name[folded])
    return result


def _unique_names(*groups: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for name in group:
            folded = name.casefold()
            if name and folded not in seen:
                seen.add(folded)
                result.append(name)
    return result


def collapse_file_providers(available: Iterable[str]) -> list[str]:
    """Deduplicate logical names while retaining highest-priority provider casing."""
    result: list[str] = []
    positions: dict[str, int] = {}
    for name in available:
        folded = name.casefold()
        if folded in positions:
            result[positions[folded]] = name
        else:
            positions[folded] = len(result)
            result.append(name)
    return result


def is_openmw_player_stub(name: str) -> bool:
    return name.casefold().endswith(_OPENMW_PLAYER_STUB_SUFFIXES)


def destub_plugin_name(name: str) -> str:
    return name[:-4] if is_openmw_player_stub(name) else name


def normalize_plugin_loadorder(names: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = destub_plugin_name(raw)
        folded = name.casefold()
        if folded not in seen:
            seen.add(folded)
            result.append(name)
    return result


def order_plugins_by_loadorder(
    available: Iterable[str], loadorder: Iterable[str]
) -> list[str]:
    available = collapse_file_providers(available)
    normalized = normalize_plugin_loadorder(loadorder)
    if not normalized:
        return available
    rank = {name.casefold(): index for index, name in enumerate(normalized)}
    return sorted(
        available,
        key=lambda name: (
            (0, rank[name.casefold()])
            if name.casefold() in rank
            else (1, 0)
        ),
    )


def unranked_native_plugins(
    content_plugins: Iterable[str], loadorder: Iterable[str]
) -> list[str]:
    normalized = normalize_plugin_loadorder(loadorder)
    if not normalized:
        return []
    ranked = {name.casefold() for name in normalized}
    result: list[str] = []
    seen: set[str] = set()
    for name in content_plugins:
        folded = name.casefold()
        if (
            folded.endswith(_OPENMW_NATIVE_SUFFIXES)
            and folded not in ranked
            and folded not in seen
        ):
            seen.add(folded)
            result.append(name)
    return result


def format_name_sample(names: Iterable[str], limit: int = 10) -> str:
    names = list(names)
    shown = ", ".join(repr(name) for name in names[:limit])
    omitted = len(names) - limit
    return f"{shown} (+{omitted} more)" if omitted > 0 else shown


def create_selection_state(
    configured: dict[str, list[str]],
    loadorder: Iterable[str],
    available_plugins: Iterable[str],
    available_archives: Iterable[str],
    supplemental_archives: Iterable[str] = (),
) -> OpenMWSelectionState:
    """Capture durable activation state before replacing a legacy profile config."""
    available_plugins = list(available_plugins)
    available_archives = list(available_archives)
    configured_plugins = _unique_names(
        configured["content"], configured["groundcover"]
    )
    enabled_plugins = configured_plugins or _unique_names(available_plugins)

    configured_archives = _unique_names(
        configured["fallback-archive"], supplemental_archives
    )
    if not configured["fallback-archive"]:
        configured_archives = _unique_names(configured_archives, available_archives)

    return {
        "version": _SELECTION_STATE_VERSION,
        "known_plugins": _unique_names(loadorder, available_plugins, enabled_plugins),
        "enabled_plugins": enabled_plugins,
        "groundcover": _unique_names(configured["groundcover"]),
        "known_archives": _unique_names(available_archives, configured_archives),
        "archives": configured_archives,
        "profile_config_entries": [],
        "profile_config_entries_known": True,
        "profile_config_terminal": False,
    }


def update_selection_state(
    state: OpenMWSelectionState,
    available_plugins: Iterable[str],
    available_archives: Iterable[str],
    groundcover: Iterable[str],
) -> bool:
    """Enable newly discovered files and persist explicit groundcover changes."""
    original = json.dumps(state, sort_keys=True)
    known_plugin_keys = {name.casefold() for name in state["known_plugins"]}
    enabled_plugin_keys = {name.casefold() for name in state["enabled_plugins"]}
    for name in available_plugins:
        folded = name.casefold()
        if folded not in known_plugin_keys:
            known_plugin_keys.add(folded)
            state["known_plugins"].append(name)
            enabled_plugin_keys.add(folded)
            state["enabled_plugins"].append(name)

    groundcover = _unique_names(groundcover)
    for name in groundcover:
        folded = name.casefold()
        if folded not in known_plugin_keys:
            known_plugin_keys.add(folded)
            state["known_plugins"].append(name)
        if folded not in enabled_plugin_keys:
            enabled_plugin_keys.add(folded)
            state["enabled_plugins"].append(name)
    state["groundcover"] = groundcover

    known_archive_keys = {name.casefold() for name in state["known_archives"]}
    archive_keys = {name.casefold() for name in state["archives"]}
    for name in available_archives:
        folded = name.casefold()
        if folded not in known_archive_keys:
            known_archive_keys.add(folded)
            state["known_archives"].append(name)
            archive_keys.add(folded)
            state["archives"].append(name)
    return original != json.dumps(state, sort_keys=True)


def read_selection_state(state_path: Path) -> OpenMWSelectionState | None:
    if not state_path.is_file():
        return None
    data = json.loads(state_path.read_text(encoding="utf-8"))
    keys = (
        "known_plugins",
        "enabled_plugins",
        "groundcover",
        "known_archives",
        "archives",
    )
    if not isinstance(data, dict) or data.get("version") not in (
        1,
        _SELECTION_STATE_VERSION,
    ):
        raise ValueError(f"Unsupported OpenMW selection state: {state_path}")
    if any(
        not isinstance(data.get(key), list)
        or any(not isinstance(value, str) for value in data[key])
        for key in keys
    ):
        raise ValueError(f"Invalid OpenMW selection state: {state_path}")
    if data["version"] == _SELECTION_STATE_VERSION and (
        not isinstance(data.get("profile_config_entries"), list)
        or any(
            not isinstance(value, str)
            for value in data["profile_config_entries"]
        )
        or not isinstance(data.get("profile_config_entries_known"), bool)
        or not isinstance(data.get("profile_config_terminal"), bool)
    ):
        raise ValueError(f"Invalid OpenMW selection state: {state_path}")
    return data


def upgrade_selection_state(state: OpenMWSelectionState) -> bool:
    if state["version"] == _SELECTION_STATE_VERSION:
        return False
    state["version"] = _SELECTION_STATE_VERSION
    state["profile_config_entries"] = []
    state["profile_config_entries_known"] = False
    state["profile_config_terminal"] = False
    return True


def write_selection_state(
    state_path: Path, state: OpenMWSelectionState
) -> None:
    with _atomic_text_writer(state_path) as stream:
        json.dump(state, stream, ensure_ascii=True, indent=2)
        stream.write("\n")


def _trim_trailing_blanks(lines: list[str]) -> list[str]:
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _split_marked_blocks(
    lines: Iterable[str], begin: str, end: str
) -> tuple[list[str], list[list[str]]]:
    """Remove complete marker blocks and return their contents.

    Malformed or nested ownership markers are ambiguous, so fail without
    rewriting the file. The launch hook will then block OpenMW rather than use a
    stale profile or save path.
    """
    source = list(lines)
    out: list[str] = []
    blocks: list[list[str]] = []
    i = 0
    while i < len(source):
        marker = source[i].strip()
        if marker == end:
            raise ValueError(f"Found '{end}' without a matching '{begin}'")
        if marker != begin:
            out.append(source[i])
            i += 1
            continue
        end_index = None
        for j in range(i + 1, len(source)):
            marker = source[j].strip()
            if marker == begin:
                raise ValueError(f"Found nested '{begin}' marker")
            if marker == end:
                end_index = j
                break
        if end_index is None:
            raise ValueError(f"Found '{begin}' without a matching '{end}'")
        blocks.append(source[i + 1 : end_index])
        i = end_index + 1
    return out, blocks


def _without_marked_block(lines: Iterable[str], begin: str, end: str) -> list[str]:
    return _split_marked_blocks(lines, begin, end)[0]


def _option_value(line: str, option: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    return value.strip() if key.strip().lower() == option else None


def capture_profile_config_entries(cfg_path: Path) -> list[str]:
    """Capture raw nested config options before making a profile terminal."""
    return [
        line for line in _read_lines(cfg_path) if _option_value(line, "config") is not None
    ]


def suspend_profile_config_entries(
    state: OpenMWSelectionState, cfg_path: Path
) -> bool:
    """Save visible nested selectors and mark the profile as terminal."""
    original = json.dumps(state, sort_keys=True)
    visible = capture_profile_config_entries(cfg_path)
    if state["profile_config_terminal"]:
        saved_counts: dict[str, int] = {}
        for line in state["profile_config_entries"]:
            saved_counts[line] = saved_counts.get(line, 0) + 1
        visible_counts: dict[str, int] = {}
        for line in visible:
            visible_counts[line] = visible_counts.get(line, 0) + 1
            if visible_counts[line] > saved_counts.get(line, 0):
                state["profile_config_entries"].append(line)
    else:
        state["profile_config_entries"] = visible
    state["profile_config_terminal"] = True
    return original != json.dumps(state, sort_keys=True)


def restore_profile_config_entries(
    cfg_path: Path, entries: Iterable[str]
) -> bool:
    """Restore suspended nested selectors without duplicating visible occurrences."""
    lines = _read_lines(cfg_path)
    existing_counts: dict[str, int] = {}
    for line in capture_profile_config_entries(cfg_path):
        existing_counts[line] = existing_counts.get(line, 0) + 1

    seen: dict[str, int] = {}
    missing: list[str] = []
    for line in entries:
        seen[line] = seen.get(line, 0) + 1
        if seen[line] > existing_counts.get(line, 0):
            missing.append(line)
    if not missing:
        return False
    if lines and lines[-1].strip():
        lines.append("")
    lines.extend(missing)
    _write_lines(cfg_path, lines)
    return True


def _parse_openmw_path(value: str) -> str:
    if not value.startswith('"'):
        return value.strip()
    result: list[str] = []
    escaped = False
    for character in value[1:]:
        if escaped:
            result.append(character)
            escaped = False
        elif character == "&":
            escaped = True
        elif character == '"':
            break
        else:
            result.append(character)
    if escaped:
        result.append("&")
    return "".join(result)


def read_profile_selector(cfg_path: Path) -> Path | None:
    """Read the profile path from Fluorine's owned root selector block."""
    _, blocks = _split_marked_blocks(
        _read_lines(cfg_path), _PROFILE_BEGIN, _PROFILE_END
    )
    destinations: list[Path] = []
    for block in blocks:
        for line in block:
            value = _option_value(line, "config")
            if value is None:
                continue
            path = Path(_parse_openmw_path(value)).expanduser()
            if not path.is_absolute():
                path = cfg_path.parent / path
            destinations.append(path.resolve(strict=False))
    unique = list(dict.fromkeys(destinations))
    if len(unique) > 1:
        raise ValueError("Conflicting Fluorine OpenMW profile selectors")
    return unique[0] if unique else None


def _fsync_directory(path: Path) -> None:
    with suppress(OSError):
        directory = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


@contextmanager
def _atomic_text_writer(cfg_path: Path) -> Iterator[TextIO]:
    """Yield a same-directory temporary stream and atomically replace cfg_path."""
    target = cfg_path.absolute().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        if target.exists():
            shutil.copymode(target, temp_path)
            if hasattr(os, "listxattr"):
                for attribute in os.listxattr(target):
                    with suppress(OSError):
                        os.setxattr(
                            temp_path,
                            attribute,
                            os.getxattr(target, attribute),
                        )
        os.replace(temp_path, target)
        _fsync_directory(target.parent)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


class _FileSnapshot:
    def __init__(self, target: Path, existed: bool, backup: Path | None):
        self.target = target
        self.existed = existed
        self.backup = backup


def _transaction_target(path: Path) -> Path:
    return path.absolute().resolve(strict=False)


def validate_file_roles(roles: dict[str, Path]) -> None:
    """Reject different export roles that resolve to the same destination."""
    destinations: dict[Path, str] = {}
    for role, path in roles.items():
        target = _transaction_target(path)
        if target in destinations:
            raise ValueError(
                f"OpenMW export roles '{destinations[target]}' and '{role}' "
                f"resolve to the same file: {target}"
            )
        destinations[target] = role


def _create_file_snapshots(paths: Iterable[Path]) -> list[_FileSnapshot]:
    snapshots: list[_FileSnapshot] = []
    seen: set[Path] = set()
    try:
        for logical_path in paths:
            target = _transaction_target(logical_path)
            if target in seen:
                continue
            seen.add(target)
            if not target.parent.is_dir():
                raise ValueError(
                    f"Transaction target parent does not exist: {target.parent}"
                )
            if not target.exists():
                snapshots.append(_FileSnapshot(target, False, None))
                continue
            if not target.is_file():
                raise ValueError(f"Transaction target is not a file: {target}")

            fd, temporary = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".rollback", dir=target.parent
            )
            os.close(fd)
            backup = Path(temporary)
            try:
                backup.unlink()
                try:
                    os.link(target, backup)
                except OSError:
                    shutil.copy2(target, backup)
            except BaseException:
                backup.unlink(missing_ok=True)
                raise
            snapshots.append(_FileSnapshot(target, True, backup))
        return snapshots
    except BaseException:
        for snapshot in snapshots:
            if snapshot.backup is not None:
                snapshot.backup.unlink(missing_ok=True)
        raise


@contextmanager
def rollback_file_changes(paths: Iterable[Path]) -> Iterator[None]:
    """Restore every listed file if a later atomic export write fails."""
    snapshots = _create_file_snapshots(paths)
    try:
        yield
    except BaseException as original:
        rollback_errors: list[str] = []
        for snapshot in reversed(snapshots):
            try:
                if snapshot.existed:
                    if snapshot.backup is None:
                        raise RuntimeError("missing rollback snapshot")
                    os.replace(snapshot.backup, snapshot.target)
                    snapshot.backup = None
                else:
                    snapshot.target.unlink(missing_ok=True)
                _fsync_directory(snapshot.target.parent)
            except BaseException as error:
                rollback_errors.append(f"{snapshot.target}: {error}")
        if rollback_errors:
            raise RuntimeError(
                "OpenMW export failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from original
        raise
    else:
        cleanup_errors: list[str] = []
        for snapshot in snapshots:
            if snapshot.backup is not None:
                try:
                    snapshot.backup.unlink()
                except OSError as error:
                    cleanup_errors.append(f"{snapshot.backup}: {error}")
                _fsync_directory(snapshot.target.parent)
        if cleanup_errors:
            raise RuntimeError(
                "OpenMW export committed but rollback snapshot cleanup failed: "
                + "; ".join(cleanup_errors)
            )


def _write_lines(cfg_path: Path, lines: Iterable[str]) -> None:
    with _atomic_text_writer(cfg_path) as stream:
        for line in lines:
            stream.write(line)
            stream.write("\n")


def _preserve_non_managed(
    cfg_path: Path,
    *,
    strip_config: bool = False,
    strip_replace: bool = False,
) -> list[str]:
    """Return existing cfg lines minus the keys we manage, trailing blanks trimmed."""
    lines = _read_lines(cfg_path)
    return _trim_trailing_blanks(
        [
            line
            for line in lines
            if not _is_managed(line)
            and not (
                strip_config
                and "=" in line
                and line.split("=", 1)[0].strip().lower() == "config"
            )
            and not (
                strip_replace
                and "=" in line
                and line.split("=", 1)[0].strip().lower() == "replace"
                and line.split("=", 1)[1].strip().lower() in _MANAGED_KEYS
            )
        ]
    )


def _write_marked_path(
    cfg_path: Path,
    value: Path | None,
    *,
    begin: str,
    end: str,
    key: str,
    strip_managed: bool = False,
) -> bool:
    original = _read_lines(cfg_path)
    had_marker = any(line.strip() in (begin, end) for line in original)
    if value is None and not strip_managed and not had_marker:
        return False
    lines = _without_marked_block(original, begin, end)
    if strip_managed:
        lines = _trim_trailing_blanks(
            [line for line in lines if not _is_managed(line)]
        )
    lines = _trim_trailing_blanks(lines)
    if value is not None:
        if lines:
            lines.append("")
        lines.extend((begin, f"{key}={escape_data_path(str(value))}", end))
    if lines == original or (not lines and not cfg_path.exists()):
        return False
    _write_lines(cfg_path, lines)
    return True


def write_profile_selector(
    cfg_path: Path,
    profile_dir: Path | None,
    *,
    strip_managed: bool = False,
    log_fn=None,
) -> None:
    """Select ``profile_dir`` as OpenMW's highest-priority config directory.

    Only the Fluorine-owned marker block is replaced; existing user ``config=``
    entries and unrelated settings are preserved. When ``strip_managed`` is
    true, data/content/archive keys previously managed in the root config are
    removed because they now live in the selected profile's openmw.cfg.
    """
    changed = _write_marked_path(
        cfg_path,
        profile_dir,
        begin=_PROFILE_BEGIN,
        end=_PROFILE_END,
        key="config",
        strip_managed=strip_managed,
    )
    if changed:
        _log = log_fn or (lambda _: None)
        if profile_dir is None:
            _log(f"  Removed Fluorine profile selector from {cfg_path}.")
        else:
            _log(f"  Selected OpenMW profile config dir: {profile_dir}.")


def write_local_saves(
    cfg_path: Path,
    user_data: Path | None,
    *,
    log_fn=None,
) -> None:
    """Set or remove profile-local saves while restoring user-owned settings."""
    original = _read_lines(cfg_path)
    lines, blocks = _split_marked_blocks(
        original, _LOCAL_SAVES_BEGIN, _LOCAL_SAVES_END
    )

    restored: list[tuple[int, str]] = []
    for block in blocks:
        for line in block:
            if line.startswith(_LOCAL_SAVES_ORIGINAL):
                payload = line[len(_LOCAL_SAVES_ORIGINAL) :]
                try:
                    index_text, encoded = payload.split(":", 1)
                    restored.append(
                        (
                            int(index_text),
                            base64.b64decode(encoded, validate=True).decode("utf-8"),
                        )
                    )
                except (ValueError, binascii.Error, UnicodeDecodeError) as e:
                    raise ValueError("Invalid saved user-data setting") from e
    seen_indexes: set[int] = set()
    for index, line in sorted(restored):
        if index < 0 or index > len(lines) or index in seen_indexes:
            raise ValueError("Invalid saved user-data position")
        seen_indexes.add(index)
        lines.insert(index, line)

    if user_data is not None:
        user_data_lines = [
            (index, line)
            for index, line in enumerate(lines)
            if "=" in line
            and line.split("=", 1)[0].strip().lower() == "user-data"
        ]
        user_data_indexes = {index for index, _ in user_data_lines}
        insertion_index = (
            sum(1 for index in range(user_data_lines[0][0]) if index not in user_data_indexes)
            if user_data_lines
            else len(lines)
        )
        lines = [
            line for index, line in enumerate(lines) if index not in user_data_indexes
        ]
        block = [_LOCAL_SAVES_BEGIN]
        block.extend(
            f"{_LOCAL_SAVES_ORIGINAL}{index}:"
            + base64.b64encode(line.encode("utf-8")).decode("ascii")
            for index, line in user_data_lines
        )
        block.extend(
            (
                f"user-data={escape_data_path(str(user_data))}",
                _LOCAL_SAVES_END,
            )
        )
        lines[insertion_index:insertion_index] = block

    if lines == original or (not lines and not cfg_path.exists()):
        return
    _write_lines(cfg_path, lines)
    if user_data is not None:
        _log = log_fn or (lambda _: None)
        _log(f"  Selected profile-local OpenMW user data dir: {user_data}.")


def _dedup_preserving_order(
    base: Iterable[str], extra: Iterable[str]
) -> list[str]:
    """Concatenate ``base`` then ``extra``, dropping case-insensitive duplicates."""
    result: list[str] = []
    seen: set[str] = set()
    for item in (*base, *extra):
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _dedup_paths_preserving_order(paths: Iterable[Path | str]) -> list[str]:
    """Deduplicate paths without folding case on case-sensitive filesystems."""
    result: list[str] = []
    seen: set[str] = set()
    for path in paths:
        value = str(path)
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def write_openmw_launcher_cfg(
    cfg_path: Path,
    data_dirs: Iterable[Path | str],
    content_plugins: Iterable[str],
    fallback_archives: Iterable[str] = (),
    *,
    vanilla_masters: Iterable[str] = VANILLA_MASTERS,
    vanilla_bsas: Iterable[str] = VANILLA_BSAS,
    profile_name: str = "Fluorine",
    log_fn=None,
) -> None:
    """Synchronize OpenMW Launcher's content list with Fluorine's generated one.

    The launcher stores data paths and selected content separately in
    ``launcher.cfg`` and gives that list precedence over ``openmw.cfg``. Update
    only a named Fluorine profile and the current-profile selector; unrelated
    content lists and launcher settings remain intact.
    """
    _log = log_fn or (lambda _: None)
    data = _dedup_paths_preserving_order(data_dirs)
    content = _dedup_preserving_order(vanilla_masters, content_plugins)
    archives = _dedup_preserving_order(vanilla_bsas, fallback_archives)

    def write_line(stream: TextIO, line: str = "") -> None:
        stream.write(line)
        stream.write("\n")

    def write_generated_profile(stream: TextIO) -> None:
        for name in archives:
            write_line(stream, f"{profile_name}/fallback-archive={name}")
        for path in data:
            write_line(stream, f"{profile_name}/data={path}")
        for name in content:
            write_line(stream, f"{profile_name}/content={name}")

    saw_profiles = False
    saw_general = False
    in_profiles = False
    in_general = False
    general_has_first_run = False
    first_profiles_section = True

    with _atomic_text_writer(cfg_path) as output:
        def finish_section() -> None:
            nonlocal general_has_first_run, first_profiles_section
            if in_general and not general_has_first_run:
                write_line(output, "firstrun=false")
            if in_profiles and first_profiles_section:
                write_generated_profile(output)
                first_profiles_section = False

        if cfg_path.is_file():
            with cfg_path.open("r", encoding="utf-8", errors="replace") as source:
                for raw in source:
                    line = raw.rstrip("\r\n")
                    stripped = line.strip()
                    is_section = stripped.startswith("[") and stripped.endswith("]")
                    if is_section:
                        finish_section()
                        section = stripped[1:-1].strip().lower()
                        in_profiles = section == "profiles"
                        in_general = section == "general"
                        general_has_first_run = False
                        saw_profiles = saw_profiles or in_profiles
                        saw_general = saw_general or in_general
                        write_line(output, line)
                        if in_profiles and first_profiles_section:
                            write_line(output, f"currentprofile={profile_name}")
                        continue

                    if in_profiles and "=" in line:
                        key = line.split("=", 1)[0].strip()
                        profile, separator, _ = key.rpartition("/")
                        if key.lower() == "currentprofile" or (
                            separator and profile == profile_name
                        ):
                            continue
                    if in_general and "=" in line:
                        key = line.split("=", 1)[0].strip().lower()
                        general_has_first_run = general_has_first_run or key == "firstrun"
                    write_line(output, line)
            finish_section()

        if not saw_general:
            write_line(output)
            write_line(output, "[General]")
            write_line(output, "firstrun=false")
        if not saw_profiles:
            write_line(output)
            write_line(output, "[Profiles]")
            write_line(output, f"currentprofile={profile_name}")
            write_generated_profile(output)

    _log(
        f"  Wrote launcher.cfg content list: {len(data)} data dir(s) to "
        f"{cfg_path}."
    )


def build_managed_block(
    data_dirs: Iterable[Path | str],
    content_plugins: Iterable[str],
    groundcover_plugins: Iterable[str] = (),
    fallback_archives: Iterable[str] = (),
    *,
    vanilla_masters: Iterable[str] = VANILLA_MASTERS,
    vanilla_bsas: Iterable[str] = VANILLA_BSAS,
    replace_managed: bool = False,
) -> list[str]:
    """Build the managed cfg lines (no I/O), in the order OpenMW expects."""
    content = _dedup_preserving_order(vanilla_masters, content_plugins)
    archives = _dedup_preserving_order(vanilla_bsas, fallback_archives)

    block: list[str] = [""]  # blank separator from the preserved section
    if replace_managed:
        block += [f"replace={key}" for key in sorted(_REPLACED_MANAGED_KEYS)]
    block += [f"data={escape_data_path(str(d))}" for d in data_dirs]
    block += [f"content={c}" for c in content]
    block += [f"groundcover={g}" for g in groundcover_plugins]
    block += [f"fallback-archive={a}" for a in archives]
    return block


def write_openmw_cfg(
    cfg_path: Path,
    data_dirs: Iterable[Path | str],
    content_plugins: Iterable[str],
    groundcover_plugins: Iterable[str] = (),
    fallback_archives: Iterable[str] = (),
    *,
    vanilla_masters: Iterable[str] = VANILLA_MASTERS,
    vanilla_bsas: Iterable[str] = VANILLA_BSAS,
    replace_managed: bool = False,
    strip_config: bool = False,
    log_fn=None,
) -> None:
    """Rewrite the managed data=/content=/groundcover=/fallback-archive= block.

    ``strip_config`` makes this file a terminal config source. This is required
    for a selected MO2 profile because OpenMW writes settings and Lua storage to
    the final active config directory; a nested ``config=`` would otherwise
    redirect those writes away from the profile.
    """
    _log = log_fn or (lambda _: None)
    data_dirs = list(data_dirs)  # consumed twice (block + log); avoid generator exhaustion
    kept = _preserve_non_managed(
        cfg_path,
        strip_config=strip_config,
        strip_replace=replace_managed,
    )
    block = build_managed_block(
        data_dirs,
        content_plugins,
        groundcover_plugins,
        fallback_archives,
        vanilla_masters=vanilla_masters,
        vanilla_bsas=vanilla_bsas,
        replace_managed=replace_managed,
    )
    _write_lines(cfg_path, kept + block)
    _log(f"  Wrote openmw.cfg: {len(data_dirs)} data dir(s) to {cfg_path}.")


def restore_openmw_cfg(
    cfg_path: Path,
    data_dirs: Iterable[Path | str],
    *,
    vanilla_masters: Iterable[str] = VANILLA_MASTERS,
    vanilla_bsas: Iterable[str] = VANILLA_BSAS,
    log_fn=None,
) -> None:
    """Reset the managed block to vanilla-only (used on uninstall / 'clear')."""
    _log = log_fn or (lambda _: None)
    if not cfg_path.is_file():
        return
    kept = _preserve_non_managed(cfg_path)
    block = build_managed_block(
        data_dirs,
        (),
        (),
        (),
        vanilla_masters=vanilla_masters,
        vanilla_bsas=vanilla_bsas,
    )
    _write_lines(cfg_path, kept + block)
    _log(f"  Restored openmw.cfg to vanilla content at {cfg_path}.")
