"""
game_openmw.py — Fluorine game plugin for The Elder Scrolls III: Morrowind run
under OpenMW (the native Linux engine).

Unlike the Windows Morrowind plugin this:
  - is a native Linux launch (no Proton/Wine) via isNativeLinux();
  - does NOT rely on Fluorine's FUSE VFS — OpenMW has its own VFS, so we hand it
    one data= directory per active mod (in priority order) plus the load order
    as content= lines, written into openmw.cfg right before launch. The FUSE
    mount is skipped for this game by returning usesVFS() == False (wired in the
    C++ core; harmless until then);
  - keeps OpenMW-native plugins (.omwaddon/.omwgame/.omwscripts) in the load
    order instead of dropping them, and routes groundcover plugins to
    groundcover= lines (listed in <profile>/groundcover.txt) so they don't tank
    performance as content= entries.
  - uses OpenMW's native config-directory chaining for MO2 profiles with local
    settings, making the profile OpenMW's writable user-config directory without
    copying or classifying settings/storage files, and synchronizes the
    launcher's separate content list with the generated native paths.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from PyQt6.QtCore import QDir, QFileInfo, qInfo, qWarning

import mobase

from ..basic_game import BasicGame
from .openmw_support.openmw_cfg import (
    write_local_saves,
    write_openmw_cfg,
    write_openmw_launcher_cfg,
    write_profile_selector,
)

_FLATPAK_ID = "org.openmw.OpenMW"

# openmw.cfg candidates, Flatpak first (matches Amethyst's detection order).
_FLATPAK_CFG = (
    Path.home() / ".var" / "app" / _FLATPAK_ID / "config" / "openmw" / "openmw.cfg"
)


def _native_cfg() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "openmw" / "openmw.cfg"


def _flatpak_installed() -> bool:
    return (Path.home() / ".var" / "app" / _FLATPAK_ID).is_dir()


def _detect_openmw_cfg(prefer_flatpak: bool) -> Path | None:
    """Return the openmw.cfg to manage, or None if none exists yet."""
    candidates = (
        [_FLATPAK_CFG, _native_cfg()]
        if prefer_flatpak
        else [_native_cfg(), _FLATPAK_CFG]
    )
    for cfg in candidates:
        if cfg.is_file():
            return cfg
    return None


# Directories/extensions that mark a folder as valid OpenMW/Morrowind mod data.
_VALID_DIRS = {
    "bookart", "fonts", "icons", "meshes", "music", "shaders", "sound",
    "splash", "textures", "video", "mwse", "distantland",
    "l10n", "mygui", "scripts",  # OpenMW-native (Lua / localisation / GUI)
}
_PLUGIN_EXTS = {".esp", ".esm", ".omwaddon", ".omwgame", ".omwscripts"}

# Kezyma's "OpenMW Player" drops an empty TES3 stub ESP next to each
# OpenMW-native plugin so MO2's right pane can list and order it. The stub is
# named "<plugin>.esp" (e.g. "Sun's Dusk.omwaddon.esp" for the real
# "Sun's Dusk.omwaddon"). MO2's loadorder.txt therefore records STUB names, but
# we emit the real files (_scan_mod skips the stubs), so a stub's rank must be
# mapped onto the real name when sorting content= — otherwise every
# .omwaddon/.omwscripts/.omwgame plugin is unranked and the content= sort
# ignores master-before-dependent order (e.g. SDServiceRefusal.omwaddon before
# its parent Sun's Dusk.omwaddon, which makes OpenMW abort on launch).
_KEZYMA_STUB_SUFFIXES = (".omwaddon.esp", ".omwscripts.esp", ".omwgame.esp")


def _destub_plugin_name(name: str) -> str:
    """Return the real OpenMW-native plugin name for a Kezyma stub, else ``name``.

    Strips the trailing ``.esp`` wrapper from names like
    ``Sun's Dusk.omwaddon.esp`` -> ``Sun's Dusk.omwaddon``. Real .esp/.esm plugins
    (no OpenMW-native stem) and names that are already real pass through
    unchanged. The suffix check is case-insensitive; the returned name
    preserves the original casing of the stem.
    """
    if name.lower().endswith(_KEZYMA_STUB_SUFFIXES):
        return name[:-4]  # strip the trailing ".esp" wrapper
    return name


class OpenMWModDataChecker(mobase.ModDataChecker):
    def __init__(self):
        super().__init__()

    def dataLooksValid(
        self, filetree: mobase.IFileTree
    ) -> mobase.ModDataChecker.CheckReturn:
        for entry in filetree:
            if entry.isDir():
                if entry.name().lower() in _VALID_DIRS:
                    return mobase.ModDataChecker.VALID
            else:
                if Path(entry.name().lower()).suffix in _PLUGIN_EXTS:
                    return mobase.ModDataChecker.VALID
        return mobase.ModDataChecker.INVALID


class OpenMWGame(BasicGame):
    Name = "OpenMW Support Plugin"
    Author = "Fluorine OpenMW contributors"
    Version = "0.1.0"

    GameName = "Morrowind (OpenMW)"
    GameShortName = "morrowind"
    GameNexusName = "morrowind"
    GameNexusId = 100
    GameSteamId = 22320
    # Detection only — the Steam Morrowind install owns Morrowind.exe. We never
    # launch it; executables() returns the native OpenMW binary instead and
    # isNativeLinux() keeps Proton out of the picture.
    GameBinary = "Morrowind.exe"
    GameLauncher = "openmw-launcher"
    GameDataPath = "Data Files"
    GameSaveExtension = "omwsave"
    GameSupportURL = "https://openmw.org/"

    def init(self, organizer: mobase.IOrganizer) -> bool:
        super().init(organizer)
        self._register_feature(OpenMWModDataChecker())
        organizer.onAboutToRun(self._export_openmw_cfg)
        return True

    # OpenMW is always a native Linux launch — never Proton/Wine.
    def isNativeLinux(self) -> bool:
        return True

    # OpenMW manages its own VFS via data= dirs, so Fluorine must NOT FUSE-mount
    # over Data Files for this game. Honoured by the C++ core once usesVFS() is
    # wired there; defining it here makes the plugin forward-compatible.
    def usesVFS(self) -> bool:
        return False

    def documentsDirectory(self) -> QDir:
        return self.gameDirectory()

    def executables(self) -> list[mobase.ExecutableInfo]:
        out: list[mobase.ExecutableInfo] = []
        flatpak = shutil.which("flatpak")
        if _flatpak_installed() and flatpak:
            out.append(
                mobase.ExecutableInfo("OpenMW (Flatpak)", QFileInfo(flatpak))
                .withArgument("run")
                .withArgument(_FLATPAK_ID)
            )
            out.append(
                mobase.ExecutableInfo("OpenMW Launcher (Flatpak)", QFileInfo(flatpak))
                .withArgument("run")
                .withArgument("--command=openmw-launcher")
                .withArgument(_FLATPAK_ID)
            )
        launcher = shutil.which("openmw-launcher")
        if launcher:
            out.append(mobase.ExecutableInfo("OpenMW Launcher", QFileInfo(launcher)))
        openmw = shutil.which("openmw")
        if openmw:
            out.append(mobase.ExecutableInfo("OpenMW", QFileInfo(openmw)))
        return out

    # ------------------------------------------------------------------
    # openmw.cfg export (runs on every launch via onAboutToRun)
    # ------------------------------------------------------------------

    def _is_openmw_binary(self, app_name: str) -> bool:
        base = Path(app_name).name.lower()
        # 'flatpak' here is our OpenMW launcher (we only register it for OpenMW).
        return base in {"openmw", "openmw-launcher", "flatpak"}

    def _read_groundcover_txt(self) -> list[str]:
        """Plugins flagged as groundcover, from <profile>/groundcover.txt,
        falling back to groundcover= entries in <profile>/openmw.cfg (Kezyma's
        OpenMW Player output) when groundcover.txt is absent."""
        try:
            profile_dir = Path(self._organizer.profile().absolutePath())
        except Exception:
            return []

        # Primary source: Fluorine-native groundcover.txt (user-controlled).
        # Takes precedence over Kezyma's list so a user who creates this file
        # stays in control of what loads as groundcover.
        gc_file = profile_dir / "groundcover.txt"
        if gc_file.is_file():
            out: list[str] = []
            for raw in gc_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip().lstrip("*").strip()
                if line and not line.startswith("#"):
                    out.append(line)
            return out

        # Fallback: groundcover= entries in the profile's openmw.cfg. Kezyma's
        # OpenMW Player writes these directly (Wabbajack modlists like NEMAS
        # ship them instead of a groundcover.txt), so parsing them here makes
        # Fluorine route grass mods to groundcover= out-of-the-box. We split on
        # the first '=' (not startswith) so 'groundcover = X' with spaces around
        # '=' is handled the same as 'groundcover=X'.
        profile_cfg = profile_dir / "openmw.cfg"
        if not profile_cfg.is_file():
            return []
        out = []
        for raw in profile_cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip().lower() == "groundcover":
                value = value.strip()
                if value:
                    out.append(value)
        return out

    def _read_loadorder_txt(self) -> list[str]:
        """Plugin load order from <profile>/loadorder.txt (MO2 right-pane order).

        loadorder.txt records Kezyma stub names for OpenMW-native plugins (e.g.
        ``Sun's Dusk.omwaddon.esp``), but we emit the real files (the stubs are
        skipped in _scan_mod). Map each entry through _destub_plugin_name so the
        returned names match the content= plugins we sort against — otherwise
        every .omwaddon/.omwscripts/.omwgame plugin is unranked and the sort
        falls back to scan order, ignoring master-before-dependent ordering
        (e.g. SDServiceRefusal.omwaddon before its parent Sun's Dusk.omwaddon,
        which makes OpenMW abort on launch).
        """
        try:
            profile_dir = Path(self._organizer.profile().absolutePath())
        except Exception:
            return []
        lo_file = profile_dir / "loadorder.txt"
        if not lo_file.is_file():
            return []
        out: list[str] = []
        for raw in lo_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                out.append(_destub_plugin_name(line))
        return out

    def _export_openmw_cfg(self, app_name: str) -> bool:
        # onAboutToRun fires for every launched program; only act for OpenMW.
        if not self._is_openmw_binary(app_name):
            return True
        try:
            organizer = self._organizer
            profile = organizer.profile()
            profile_dir = Path(profile.absolutePath())
            local_settings = profile.localSettingsEnabled()
            local_saves = profile.localSavesEnabled()
            game_dir = Path(self.gameDirectory().absolutePath())
            data_files = game_dir / "Data Files"

            root_cfg = _detect_openmw_cfg(
                prefer_flatpak="flatpak" in Path(app_name).name.lower()
            )
            if root_cfg is None:
                qWarning(
                    "OpenMW: no openmw.cfg found. Run openmw-launcher once to "
                    "create it, then mods will be applied on the next launch."
                )
                return True
            profile_cfg = profile_dir / "openmw.cfg"
            chained_profile = local_settings and profile_cfg != root_cfg
            cfg = profile_cfg if chained_profile else root_cfg

            modlist = organizer.modList()

            # data=: vanilla Data Files first (lowest prio), then each active mod
            # in profile-priority order, then Overwrite last (wins). Mirrors the
            # ordering of AnyOldName3's MO2 exporter.
            data_dirs: list[Path] = [data_files]
            bsa_archives: list[str] = []
            # content= is built by scanning each active mod's directory for plugin
            # files, NOT from the core plugin list. The core plugin list (right
            # pane) is empty for this game: BasicGame returns the default
            # loadOrderMechanism()==None, so pluginlist.cpp force-disables every
            # esp/esm (loadOrder == -1) and there is no Plugins tab. So we are the
            # source of truth. Tiers follow OpenMW convention: masters
            # (.esm/.omwgame) before plugins (.esp/.omwaddon), and .omwscripts
            # (Lua manifests, no records) last. Within a tier we keep mod-priority
            # order (and alphabetical within a single mod). The tier order is the
            # fallback; when <profile>/loadorder.txt exists it is the authoritative
            # order and we stable-sort by it (unranked OpenMW-native plugins stay
            # after the ranked ones, keeping their tier order).
            masters: list[str] = []         # .esm / .omwgame
            normal_plugins: list[str] = []  # .esp / .omwaddon
            omw_scripts: list[str] = []     # .omwscripts

            def _scan_mod(path: Path) -> None:
                data_dirs.append(path)
                try:
                    entries = sorted(path.iterdir(), key=lambda p: p.name.lower())
                except OSError:
                    return
                for f in entries:
                    if not f.is_file():
                        continue
                    low = f.name.lower()
                    # Skip Kezyma "OpenMW Player" stub esps: empty TES3 esps named
                    # <name>.omwaddon.esp / <name>.omwscripts.esp that some MO2<->OpenMW
                    # tools drop next to the real .omwaddon/.omwscripts purely so the
                    # entry shows up in MO2's plugin list. The real file is scanned
                    # separately; loading the empty stub as content= is at best useless
                    # and at worst aborts OpenMW ("sub-record incomplete").
                    if low.endswith(_KEZYMA_STUB_SUFFIXES):
                        continue
                    ext = f.suffix.lower()
                    if ext in {".esm", ".omwgame"}:
                        masters.append(f.name)
                    elif ext in {".esp", ".omwaddon"}:
                        normal_plugins.append(f.name)
                    elif ext == ".omwscripts":
                        omw_scripts.append(f.name)
                    elif ext == ".bsa":
                        bsa_archives.append(f.name)

            for name in modlist.allModsByProfilePriority():
                if name == "Overwrite":
                    continue
                try:
                    if not (modlist.state(name) & mobase.ModState.ACTIVE):
                        continue
                    mod = modlist.getMod(name)
                except Exception:
                    continue
                if mod is None:
                    continue
                mod_path = Path(mod.absolutePath())
                if mod_path.is_dir():
                    _scan_mod(mod_path)

            try:
                overwrite = modlist.getMod("Overwrite")
                if overwrite is not None:
                    ov_path = Path(overwrite.absolutePath())
                    if ov_path.is_dir() and any(ov_path.iterdir()):
                        _scan_mod(ov_path)
            except Exception:
                pass

            # content=: masters → normal plugins → Lua scripts (see _scan_mod),
            # minus any the user routed to groundcover. build_managed_block
            # prepends the vanilla masters and dedups case-insensitively, so a mod
            # re-shipping a vanilla esm (or two mods sharing a plugin name) won't
            # produce duplicate content= lines.
            all_plugins = masters + normal_plugins + omw_scripts
            loadorder = self._read_loadorder_txt()
            if loadorder:
                rank = {name.lower(): i for i, name in enumerate(loadorder)}
                # Stable sort: ranked plugins by loadorder.txt position, unranked
                # (.omwaddon/.omwscripts/.omwgame not in MO2's list) keep their
                # current order after all ranked ones.
                all_plugins.sort(
                    key=lambda p: rank.get(p.lower(), len(rank))
                )
            plugin_lower = {p.lower() for p in all_plugins}

            groundcover = self._read_groundcover_txt()
            gc_lower = {g.lower() for g in groundcover}

            content = [p for p in all_plugins if p.lower() not in gc_lower]
            # Only emit groundcover= for plugins that are actually present/active.
            active_groundcover = [g for g in groundcover if g.lower() in plugin_lower]

            # Helpful, non-destructive nudge: flag likely groundcover plugins the
            # user hasn't listed yet (we never reroute automatically).
            for p in masters + normal_plugins:
                low = p.lower()
                if low not in gc_lower and ("grass" in low or "groundcover" in low):
                    qInfo(
                        f"OpenMW: '{p}' looks like a groundcover plugin. If it is, "
                        f"add it to {Path(self._organizer.profile().absolutePath()) / 'groundcover.txt'} "
                        "so it loads as groundcover= (better performance)."
                    )

            write_openmw_cfg(
                cfg,
                data_dirs=data_dirs,
                content_plugins=content,
                groundcover_plugins=active_groundcover,
                fallback_archives=bsa_archives,
                replace_managed=chained_profile,
                strip_config=chained_profile,
                log_fn=lambda m: qInfo("OpenMW:" + m),
            )

            log_fn = lambda m: qInfo("OpenMW:" + m)
            write_openmw_launcher_cfg(
                cfg.parent / "launcher.cfg",
                data_dirs=data_dirs,
                content_plugins=content,
                fallback_archives=bsa_archives,
                log_fn=log_fn,
            )
            if chained_profile:
                # The profile is the highest-priority OpenMW config directory.
                # OpenMW consequently reads and writes settings.cfg, Lua storage,
                # key bindings, shaders.yaml, launcher.cfg, and future config
                # artifacts there without Fluorine needing a filename list.
                write_local_saves(
                    profile_cfg,
                    profile_dir if local_saves else None,
                    log_fn=log_fn,
                )
                # Clear a stale root-level local-saves override before selecting
                # the profile. Only Fluorine's marked block is removed.
                write_local_saves(root_cfg, None, log_fn=log_fn)
                write_profile_selector(
                    root_cfg,
                    profile_dir,
                    strip_managed=True,
                    log_fn=log_fn,
                )
            else:
                # Without a separate profile config, keep the generated config
                # in OpenMW's normal user directory. Local saves remain
                # independent of that choice.
                write_local_saves(
                    root_cfg,
                    profile_dir if local_saves else None,
                    log_fn=log_fn,
                )
                # Remove a stale local-saves marker left in this profile if the
                # profile previously used local settings.
                if profile_cfg != root_cfg:
                    write_local_saves(profile_cfg, None, log_fn=log_fn)
                write_profile_selector(root_cfg, None, log_fn=log_fn)
            qInfo(
                f"OpenMW: wrote {len(data_dirs)} data dir(s) and "
                f"{len(content)} content plugin(s) to {cfg}."
            )
        except Exception as e:
            qWarning(f"OpenMW: openmw.cfg export failed: {e}")
            # The profile selector, openmw.cfg, and launcher.cfg form one
            # configuration. Launching after a partial update can select stale
            # paths or the wrong profile; let the user retry instead.
            return False
        return True
