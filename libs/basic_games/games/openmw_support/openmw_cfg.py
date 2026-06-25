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

from pathlib import Path
from typing import Iterable

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


def _preserve_non_managed(cfg_path: Path) -> list[str]:
    """Return existing cfg lines minus the keys we manage, trailing blanks trimmed."""
    kept: list[str] = []
    if cfg_path.is_file():
        for raw in cfg_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not _is_managed(raw):
                kept.append(raw)
    while kept and not kept[-1].strip():
        kept.pop()
    return kept


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


def build_managed_block(
    data_dirs: Iterable[Path | str],
    content_plugins: Iterable[str],
    groundcover_plugins: Iterable[str] = (),
    fallback_archives: Iterable[str] = (),
    *,
    vanilla_masters: Iterable[str] = VANILLA_MASTERS,
    vanilla_bsas: Iterable[str] = VANILLA_BSAS,
) -> list[str]:
    """Build the managed cfg lines (no I/O), in the order OpenMW expects."""
    content = _dedup_preserving_order(vanilla_masters, content_plugins)
    archives = _dedup_preserving_order(vanilla_bsas, fallback_archives)

    block: list[str] = [""]  # blank separator from the preserved section
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
    log_fn=None,
) -> None:
    """Rewrite the managed data=/content=/groundcover=/fallback-archive= block."""
    _log = log_fn or (lambda _: None)
    data_dirs = list(data_dirs)  # consumed twice (block + log); avoid generator exhaustion
    kept = _preserve_non_managed(cfg_path)
    block = build_managed_block(
        data_dirs,
        content_plugins,
        groundcover_plugins,
        fallback_archives,
        vanilla_masters=vanilla_masters,
        vanilla_bsas=vanilla_bsas,
    )
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("\n".join(kept + block) + "\n", encoding="utf-8")
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
    cfg_path.write_text("\n".join(kept + block) + "\n", encoding="utf-8")
    _log(f"  Restored openmw.cfg to vanilla content at {cfg_path}.")
