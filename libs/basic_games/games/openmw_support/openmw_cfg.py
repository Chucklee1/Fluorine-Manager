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
import os
import shutil
import tempfile
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Iterable, Iterator, TextIO

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

_PROFILE_BEGIN = "# BEGIN FLUORINE OPENMW PROFILE"
_PROFILE_END = "# END FLUORINE OPENMW PROFILE"
_LOCAL_SAVES_BEGIN = "# BEGIN FLUORINE OPENMW LOCAL SAVES"
_LOCAL_SAVES_END = "# END FLUORINE OPENMW LOCAL SAVES"
_LOCAL_SAVES_ORIGINAL = "# FLUORINE ORIGINAL USER-DATA "


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


@contextmanager
def _atomic_text_writer(cfg_path: Path) -> Iterator[TextIO]:
    """Yield a same-directory temporary stream and atomically replace cfg_path."""
    target = cfg_path.resolve() if cfg_path.is_symlink() else cfg_path
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
        with suppress(OSError):
            directory = os.open(
                target.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


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
        block += [f"replace={key}" for key in sorted(_MANAGED_KEYS)]
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
