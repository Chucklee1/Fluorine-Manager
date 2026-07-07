"""
sort_with_loot.py — an optional "Sort with LOOT" tool for OpenMW.

This is an ``IPluginTool``, but it does not live in the Tools menu: the game
declares it via ``sortToolName()`` and Fluorine's regular Sort button on the
Plugins tab — the same button every other game uses — invokes it, while the
core hides it from the Tools menu so sorting exists in exactly one place. For
other games that button downloads the *Windows* LOOT.exe and runs it under
Proton on the merged VFS, which cannot work for a native-Linux, VFS-less
OpenMW setup; this tool instead drives the native ``libloot`` Python bindings
(module name ``loot``) directly, so sorting stays native and fully optional.

Pipeline it slots into:

    modlist (Fluorine)
        -> Plugins tab (Fluorine, persistent load order)
        -> [optional] Sort button -> *this tool* reorders the tab with LOOT
        -> openmw.cfg content= lines written at launch (game_openmw.py)

Safety contract: this tool must NEVER corrupt the load order. Every libloot
call is guarded; on *any* failure we show the reason and leave the Plugins tab
exactly as it was. The tab is only ever rewritten from a LOOT result whose
plugin set is identical to the active set we handed in.

libloot is an optional native dependency. If the ``loot`` module is not bundled
(e.g. the wheel failed to build for this platform) the tool degrades to a clear
message instead of raising at import time.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from PyQt6.QtCore import (
    QCoreApplication,
    QObject,
    Qt,
    QThread,
    pyqtSignal,
    qInfo,
    qWarning,
)
from PyQt6.QtWidgets import QMessageBox, QProgressDialog

import mobase

# libloot is optional: probe for it without exploding the whole plugin import if
# the native wheel is missing. The real module is registered as ``loot``.
#
# loot.so STATICALLY links its own libstdc++/boost and dynamically needs only
# libc/libgcc_s. When imported into Mod Organizer's process (which dynamically
# links Qt's libstdc++.so.6), default ELF symbol interposition binds some of
# libloot's C++ runtime symbols to MO's libstdc++ — a cross-runtime mismatch
# that corrupts memory inside libloot's parallel plugin loader and segfaults
# (load_plugins crashes in-process but runs fine in a bare Python). Loading the
# extension with RTLD_DEEPBIND makes it prefer its own self-contained symbols
# first while still resolving the Python C-API from the global scope (loot.so
# does not link libpython), which eliminates the clash. Harmless standalone.
try:
    import sys as _sys

    _prev_dlopen_flags = None
    try:
        _deepbind = getattr(os, "RTLD_DEEPBIND", 0)
        if _deepbind:
            _prev_dlopen_flags = _sys.getdlopenflags()
            _sys.setdlopenflags(_prev_dlopen_flags | _deepbind)
    except Exception:
        _prev_dlopen_flags = None

    try:
        import loot as _loot  # type: ignore

        _LOOT_AVAILABLE = True
        _LOOT_IMPORT_ERROR = ""
    finally:
        if _prev_dlopen_flags is not None:
            _sys.setdlopenflags(_prev_dlopen_flags)
except Exception as exc:  # pragma: no cover - depends on bundled wheel
    _loot = None  # type: ignore
    _LOOT_AVAILABLE = False
    _LOOT_IMPORT_ERROR = str(exc)


# Directory holding the bundled ``loot`` package, so a child interpreter can find
# it via sys.path (see the subprocess pipeline below).
_LOOT_SITE_PACKAGES = ""
try:
    if _loot is not None and getattr(_loot, "__file__", None):
        _LOOT_SITE_PACKAGES = os.path.dirname(os.path.dirname(_loot.__file__))
except Exception:
    _LOOT_SITE_PACKAGES = ""


# Standalone script run in a CLEAN child interpreter to drive libloot. We do NOT
# call libloot in Mod Organizer's own process: its load_plugins deadlocks there
# (its statically-linked C++ runtime / internal parallel loader does not
# cooperate with MO's already-loaded libraries), even though the exact same call
# runs in well under a second in a bare Python. Isolating it in a child process
# sidesteps that entirely and lets us enforce a hard timeout, so the UI can never
# freeze. Protocol: argv[1]=request.json (inputs), argv[2]=response.json (result).
_LOOT_SUBPROCESS_SRC = r'''
import sys, os, json

def main():
    req_path, resp_path = sys.argv[1], sys.argv[2]
    with open(req_path, encoding="utf-8") as fh:
        req = json.load(fh)
    resp = {"sorted": None, "error": ""}
    try:
        sp = req.get("site_packages")
        if sp and sp not in sys.path:
            sys.path.insert(0, sp)
        import loot as L
        gt = getattr(L.GameType, "OpenMW")
        game_path = req["game_path"]
        local_path = req.get("local_path")
        if local_path:
            game = L.Game(gt, game_path, local_path)
        else:
            game = L.Game(gt, game_path)
        try:
            game.set_additional_data_paths(list(req.get("data_dirs", [])))
        except Exception:
            pass
        try:
            game.load_current_load_order_state()
        except Exception:
            pass
        masterlist = req.get("masterlist")
        if masterlist:
            try:
                game.database().load_masterlist(masterlist)
            except Exception:
                pass
        game.load_plugins(list(req["plugin_paths"]))
        resp["sorted"] = list(game.sort_plugins(list(req["active"])))
    except Exception as exc:
        resp["error"] = "%s: %s" % (type(exc).__name__, exc)
    with open(resp_path, "w", encoding="utf-8") as fh:
        json.dump(resp, fh)

main()
'''


# OpenMW shares Morrowind's LOOT masterlist (same plugins); there is no separate
# loot/openmw repo. The v0.26 branch matches the current metadata syntax and is
# self-contained (its prelude is inlined), so plain load_masterlist() suffices.
_DEFAULT_MASTERLIST_URL = (
    "https://raw.githubusercontent.com/loot/morrowind/v0.26/masterlist.yaml"
)
# Re-download the cached masterlist when it is older than this many seconds.
_MASTERLIST_MAX_AGE = 24 * 60 * 60
# Kezyma "OpenMW Player" stub esps — never feed these to LOOT.
_STUB_SUFFIXES = (".omwaddon.esp", ".omwscripts.esp", ".omwgame.esp")


class _LootWorker(QObject):
    """Runs the blocking libloot pipeline off the UI thread.

    It receives only plain data (paths, plugin filenames) — never a mobase or Qt
    object — computes the sorted active order with libloot, and emits it back.
    The caller applies the result on the main thread. This keeps the UI
    responsive and the progress dialog animated while LOOT works.
    """

    progress = pyqtSignal(str)
    # (sorted_active | None, error_text): None + text means "do not touch order".
    finished = pyqtSignal(object, str)

    def __init__(
        self,
        game_path: str,
        local_path: str | None,
        data_dirs: list[str],
        active: list[str],
        masterlist_cache: str | None,
        masterlist_url: str,
        masterlist_download: bool,
    ) -> None:
        super().__init__()
        self._game_path = game_path
        self._local_path = local_path
        self._data_dirs = data_dirs
        self._active = active
        self._ml_cache = masterlist_cache
        self._ml_url = masterlist_url
        self._ml_download = masterlist_download
        # Result, stashed here so the main thread can read it after join. The
        # finished signal is only used to stop the thread/close the dialog.
        self.result_sorted: list[str] | None = None
        self.result_error: str = ""
        self.result_done: bool = False

    def _ensure_masterlist(self) -> str | None:
        if not self._ml_cache:
            return None
        path = Path(self._ml_cache)
        fresh = (
            path.is_file()
            and (time.time() - path.stat().st_mtime) < _MASTERLIST_MAX_AGE
        )
        if self._ml_download and not fresh:
            try:
                qInfo(f"OpenMW LOOT: downloading masterlist from {self._ml_url}")
                with urllib.request.urlopen(self._ml_url, timeout=15) as resp:
                    data = resp.read()
                if data:
                    path.write_bytes(data)
            except Exception as exc:
                qWarning(
                    f"OpenMW LOOT: masterlist download failed ({exc}); "
                    "using cache if present."
                )
        return str(path) if path.is_file() else None

    def _resolve_plugin_paths(self) -> tuple[list[str], list[str]]:
        """Map each active plugin name to its absolute file path.

        openmw.cfg's data= lines are ascending precedence (the last entry wins),
        so we search them in reverse and take the first hit — matching OpenMW's
        own override rules. Returns (resolved_abs_paths, unresolved_names).
        """
        resolved: list[str] = []
        missing: list[str] = []
        # Pre-list each data dir once (case-insensitive match without a stat per
        # candidate): {dir_index: {lower_name: real_name}}.
        listings: list[dict[str, str]] = []
        for d in self._data_dirs:
            entry_map: dict[str, str] = {}
            try:
                for name in os.listdir(d):
                    entry_map.setdefault(name.lower(), name)
            except OSError:
                pass
            listings.append(entry_map)

        for plugin in self._active:
            key = plugin.lower()
            found: str | None = None
            for idx in range(len(self._data_dirs) - 1, -1, -1):
                real = listings[idx].get(key)
                if real is not None:
                    found = os.path.join(self._data_dirs[idx], real)
                    break
            if found is not None:
                resolved.append(found)
            else:
                missing.append(plugin)
        return resolved, missing

    def run(self) -> None:
        try:
            self.progress.emit(self.tr("Updating the LOOT masterlist..."))
            masterlist = self._ensure_masterlist()

            self.progress.emit(self.tr("Resolving plugin files..."))
            # Absolute plugin paths (not bare names): libloot resolves bare names
            # against the game_path's resources/vfs, the wrong dir. Resolving each
            # to its real file in the data dirs is both correct and fast.
            plugin_paths, missing = self._resolve_plugin_paths()
            if missing:
                qWarning(
                    "OpenMW LOOT: could not locate %d plugin file(s) in the data "
                    "dirs; sorting the rest: %s"
                    % (len(missing), ", ".join(missing[:10]))
                )

            self.progress.emit(
                self.tr("Sorting %d plugins with LOOT...") % len(plugin_paths)
            )
            sorted_active = self._sort_in_subprocess(plugin_paths, masterlist)

            self.result_sorted = sorted_active
            self.result_error = ""
            self.result_done = True
            self.finished.emit(sorted_active, "")
        except Exception as exc:  # any failure -> leave the order untouched
            self.result_sorted = None
            self.result_error = str(exc)
            self.result_done = True
            self.finished.emit(None, str(exc))

    def _sort_in_subprocess(
        self, plugin_paths: list[str], masterlist: str | None
    ) -> list[str]:
        """Run the whole libloot pipeline in a clean child interpreter.

        See _LOOT_SUBPROCESS_SRC for why we never call libloot in MO's process.
        A hard timeout means a libloot hang can never freeze the UI: the child is
        killed and the load order is left untouched.
        """
        interpreter = self._find_interpreter()
        if interpreter is None:
            raise RuntimeError(
                "No compatible Python 3.12 interpreter was found to run LOOT "
                "out-of-process."
            )

        request = {
            "site_packages": _LOOT_SITE_PACKAGES,
            "game_path": self._game_path,
            "local_path": self._local_path,
            "data_dirs": list(self._data_dirs),
            "plugin_paths": list(plugin_paths),
            "active": list(self._active),
            "masterlist": masterlist,
        }

        tmpdir = tempfile.mkdtemp(prefix="openmw_loot_")
        try:
            helper_path = os.path.join(tmpdir, "loot_sort_worker.py")
            req_path = os.path.join(tmpdir, "request.json")
            resp_path = os.path.join(tmpdir, "response.json")
            with open(helper_path, "w", encoding="utf-8") as fh:
                fh.write(_LOOT_SUBPROCESS_SRC)
            with open(req_path, "w", encoding="utf-8") as fh:
                json.dump(request, fh)

            qInfo(
                "OpenMW LOOT: launching child %r for %d plugins"
                % (interpreter, len(plugin_paths))
            )
            try:
                proc = subprocess.run(
                    [interpreter, helper_path, req_path, resp_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=180,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    "LOOT took too long and was stopped; the load order was left "
                    "unchanged."
                )

            if proc.returncode != 0:
                tail = (proc.stdout or b"").decode("utf-8", "replace")[-1500:]
                raise RuntimeError(
                    "The LOOT helper process failed (exit %d).\n%s"
                    % (proc.returncode, tail)
                )

            try:
                with open(resp_path, encoding="utf-8") as fh:
                    resp = json.load(fh)
            except Exception as exc:
                raise RuntimeError(f"Could not read the LOOT result ({exc}).")

            if resp.get("error"):
                raise RuntimeError(resp["error"])
            sorted_active = resp.get("sorted")
            if not sorted_active:
                raise RuntimeError("LOOT returned no sorted order.")
            qInfo("OpenMW LOOT: child returned %d sorted plugins" % len(sorted_active))
            return list(sorted_active)
        finally:
            try:
                import shutil

                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass

    def _find_interpreter(self) -> str | None:
        """Locate a Python 3.12 able to import the bundled loot.so.

        loot.cpython-312 requires a 3.12 interpreter. We prefer one shipped next
        to the bundled runtime, then fall back to the system python3.12/python3.
        """
        import shutil

        candidates: list[str] = []
        if _LOOT_SITE_PACKAGES:
            # …/python/lib/python3.12/site-packages -> …/python/bin/python3.12
            runtime_root = os.path.dirname(
                os.path.dirname(os.path.dirname(_LOOT_SITE_PACKAGES))
            )
            candidates.append(os.path.join(runtime_root, "bin", "python3.12"))
        candidates += ["python3.12", "python3", "python"]

        for cand in candidates:
            exe = cand if os.path.isabs(cand) else shutil.which(cand)
            if exe and os.path.exists(exe) and self._interpreter_is_312(exe):
                return exe
        return None

    @staticmethod
    def _interpreter_is_312(exe: str) -> bool:
        try:
            out = subprocess.run(
                [exe, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            return out.stdout.decode("utf-8", "replace").strip() == "3.12"
        except Exception:
            return False


class OpenMWSortWithLoot(mobase.IPluginTool, mobase.IPlugin):
    # NB: inherit BOTH mobase.IPluginTool and mobase.IPlugin and init both.
    # IPluginTool is bound with py::multiple_inheritance() and IPlugin as a base,
    # so a Python subclass that lists only IPluginTool raises a TypeError at
    # construction — which basic_games' createPlugins() loop silently swallows
    # (`except TypeError: pass`), leaving the tool unregistered with no log.
    def __init__(self) -> None:
        mobase.IPluginTool.__init__(self)
        mobase.IPlugin.__init__(self)
        self._organizer: mobase.IOrganizer | None = None
        # Transient per-run state for the threaded sort (see _run).
        self._sort_dialog: QProgressDialog | None = None
        self._sort_thread: QThread | None = None
        self._sort_worker: _LootWorker | None = None

    # ------------------------------------------------------------------
    # IPlugin
    # ------------------------------------------------------------------
    def init(self, organizer: mobase.IOrganizer) -> bool:
        self._organizer = organizer
        return True

    def name(self) -> str:
        return "OpenMW Sort With LOOT"

    def author(self) -> str:
        return "Fluorine OpenMW contributors"

    def description(self) -> str:
        return (
            "Sort the OpenMW Plugins tab with LOOT (libloot). Optional, native, "
            "and non-destructive: the load order is only changed if LOOT returns "
            "a valid result."
        )

    def version(self) -> mobase.VersionInfo:
        return mobase.VersionInfo(0, 1, 0)

    def settings(self) -> list[mobase.PluginSetting]:
        return [
            mobase.PluginSetting(
                "download_masterlist",
                "Download/refresh the LOOT masterlist before sorting",
                True,
            ),
            mobase.PluginSetting(
                "masterlist_url",
                "URL of the LOOT masterlist to download",
                _DEFAULT_MASTERLIST_URL,
            ),
            mobase.PluginSetting(
                "openmw_install_path",
                "OpenMW install dir (contains resources/). Empty = auto-detect "
                "from openmw.cfg.",
                "",
            ),
        ]

    # ------------------------------------------------------------------
    # IPluginTool
    # ------------------------------------------------------------------
    def displayName(self) -> str:
        return "Sort with LOOT (OpenMW)"

    def tooltip(self) -> str:
        return "Sort the OpenMW Plugins tab using LOOT (libloot)."

    def icon(self):  # noqa: ANN201 - QIcon, default empty
        from PyQt6.QtGui import QIcon

        return QIcon()

    def display(self) -> None:
        try:
            self._run()
        except Exception as exc:  # never let the tool take down the UI
            qWarning(f"OpenMW LOOT: unexpected failure: {exc}")
            self._error(
                "LOOT sorting failed unexpectedly. The load order was not "
                f"changed.\n\n{exc}"
            )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _tr(self, text: str) -> str:
        return QCoreApplication.translate("OpenMWSortWithLoot", text)

    def _message(self, icon: QMessageBox.Icon, title: str, text: str) -> None:
        parent = None
        try:
            parent = self._parentWidget()
        except Exception:
            parent = None
        box = QMessageBox(
            icon,
            self._tr(title),
            self._tr(text),
            QMessageBox.StandardButton.Ok,
            parent,
        )
        box.exec()

    def _error(self, text: str) -> None:
        self._message(QMessageBox.Icon.Warning, "Sort with LOOT", text)

    def _info(self, text: str) -> None:
        self._message(QMessageBox.Icon.Information, "Sort with LOOT", text)

    def _setting(self, key: str, default):  # noqa: ANN001
        assert self._organizer is not None
        try:
            value = self._organizer.pluginSetting(self.name(), key)
        except Exception:
            return default
        return default if value is None else value

    # --- inputs from the game / mod list -------------------------------

    def _active_plugins_from_tab(self, game) -> list[str]:  # noqa: ANN001
        """Active plugin filenames in the tab's load order, stubs dropped.

        Reuses the game's own helper so the tool and the launch-time cfg export
        agree on exactly which plugins are active and in what order.
        """
        assert self._organizer is not None
        plugin_list = self._organizer.pluginList()
        try:
            return list(game._content_from_plugin_list(plugin_list))
        except Exception:
            # Fallback: derive it ourselves if the helper is unavailable.
            names = list(plugin_list.pluginNames())
            active = [
                n
                for n in names
                if plugin_list.state(n) == mobase.PluginState.ACTIVE
                and not n.lower().endswith(_STUB_SUFFIXES)
            ]
            active.sort(key=lambda n: plugin_list.priority(n))
            return active

    def _data_directories(self, game) -> list[Path]:  # noqa: ANN001
        """Every directory LOOT must search to resolve a plugin filename.

        Mirrors the data= ordering game_openmw.py writes to openmw.cfg: vanilla
        Data Files first (lowest priority), then each active mod in profile
        order, then Overwrite last. libloot searches OpenMW data dirs in reverse,
        so the last entry wins — matching OpenMW's own precedence.
        """
        assert self._organizer is not None
        dirs: list[Path] = []
        try:
            data_files = Path(game.gameDirectory().absolutePath()) / "Data Files"
            if data_files.is_dir():
                dirs.append(data_files)
        except Exception:
            pass

        modlist = self._organizer.modList()
        try:
            ordered = modlist.allModsByProfilePriority()
        except Exception:
            ordered = []
        for mod_name in ordered:
            if mod_name == "Overwrite":
                continue
            try:
                if not (modlist.state(mod_name) & mobase.ModState.ACTIVE):
                    continue
                mod = modlist.getMod(mod_name)
            except Exception:
                continue
            if mod is None:
                continue
            mod_path = Path(mod.absolutePath())
            if mod_path.is_dir():
                dirs.append(mod_path)

        try:
            overwrite = modlist.getMod("Overwrite")
            if overwrite is not None:
                ov_path = Path(overwrite.absolutePath())
                if ov_path.is_dir() and any(ov_path.iterdir()):
                    dirs.append(ov_path)
        except Exception:
            pass
        return dirs

    def _locate_cfg(self, game) -> Path | None:  # noqa: ANN001
        """Find the openmw.cfg, reusing the game module's detection."""
        try:
            from ...game_openmw import _detect_openmw_cfg, _flatpak_installed

            return _detect_openmw_cfg(prefer_flatpak=_flatpak_installed())
        except Exception:
            return None

    def _resolve_game_path(self, cfg: Path | None) -> Path | None:
        """OpenMW install dir (the one whose resources/vfs holds the engine VFS).

        Order of preference: the user override setting, then the ``resources=``
        line in openmw.cfg (its parent), then the cfg's own directory as a last
        resort. libloot only reads engine builtins from here; for sorting we feed
        the real plugin dirs via set_additional_data_paths, so a slightly-off
        game_path (e.g. a Flatpak path unreachable from the host) is tolerated.
        """
        override = str(self._setting("openmw_install_path", "")).strip()
        if override:
            p = Path(override)
            if p.is_dir():
                return p
            qWarning(f"OpenMW LOOT: openmw_install_path '{override}' is not a dir.")

        if cfg is not None and cfg.is_file():
            try:
                for raw in cfg.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines():
                    line = raw.strip()
                    if line.startswith("resources"):
                        _, _, value = line.partition("=")
                        value = value.strip().strip('"')
                        if value:
                            res = Path(value)
                            if res.name.lower() == "resources":
                                return res.parent
                            return res.parent
            except Exception:
                pass
            return cfg.parent
        return None

    def _masterlist_plan(self) -> tuple[str | None, str, bool]:
        """Prepare the masterlist cache path/url on the main thread.

        The actual (blocking) download happens in the worker thread; here we only
        touch the organizer (main-thread only) to resolve the cache dir + settings.
        Returns (cache_path | None, url, want_download).
        """
        assert self._organizer is not None
        url = str(self._setting("masterlist_url", _DEFAULT_MASTERLIST_URL))
        want_download = bool(self._setting("download_masterlist", True))
        try:
            cache_dir = Path(self._organizer.pluginDataPath()) / "openmw_loot"
            cache_dir.mkdir(parents=True, exist_ok=True)
            return str(cache_dir / "masterlist.yaml"), url, want_download
        except Exception as exc:
            qWarning(f"OpenMW LOOT: cannot prepare masterlist cache: {exc}")
            return None, url, want_download

    # --- apply ---------------------------------------------------------

    def _current_order(self, plugin_list: mobase.IPluginList) -> list[str]:
        names = list(plugin_list.pluginNames())

        def key(n: str):
            try:
                lo = plugin_list.loadOrder(n)
                if lo is not None and lo >= 0:
                    return lo
            except Exception:
                pass
            try:
                return plugin_list.priority(n)
            except Exception:
                return 0

        return sorted(names, key=key)

    def _apply(
        self,
        plugin_list: mobase.IPluginList,
        active_old: list[str],
        sorted_active: list[str],
    ) -> int:
        """Rewrite the tab from the LOOT result. Returns plugins moved.

        Validates that LOOT returned exactly the active set before touching
        anything: a mismatch means we abort with no change.
        """
        old_set = {n.lower() for n in active_old}
        new_set = {n.lower() for n in sorted_active}
        if not sorted_active or old_set != new_set:
            raise ValueError(
                "LOOT returned a plugin set that does not match the active "
                "plugins; refusing to apply."
            )

        current = self._current_order(plugin_list)
        active_lower = old_set
        inactive_tail = [n for n in current if n.lower() not in active_lower]
        new_full = list(sorted_active) + inactive_tail

        moved = sum(1 for a, b in zip(active_old, sorted_active) if a != b)
        # IPluginList::setLoadOrder is void (it sets priorities in place); it has
        # no return value to test. Apply, then verify by reading priorities back.
        # NB: setLoadOrder refreshes priority() immediately but NOT loadOrder()
        # (that is only resynced on a later refresh), so verify via priority().
        plugin_list.setLoadOrder(new_full)

        def _prio(name: str) -> int:
            try:
                return plugin_list.priority(name)
            except Exception:
                return -1

        applied_active = sorted(active_old, key=_prio)
        if [n.lower() for n in applied_active] != [n.lower() for n in sorted_active]:
            raise RuntimeError(
                "the core did not accept the new load order (read-back mismatch)."
            )

        # Persist to disk. setLoadOrder() only updates in-memory priorities;
        # organizer.refresh(save_changes=True) saves the MODLIST, not the plugin
        # order, and actually re-reads the ESP list from disk — so without an
        # explicit write the new order is lost on the next refresh/restart (and
        # re-running LOOT would recompute the same moves). The GamePlugins feature
        # writes <profile>/plugins.txt + loadorder.txt from the current priorities,
        # which is exactly what the launch-time openmw.cfg export then reads.
        self._persist_load_order(plugin_list)

        try:
            self._organizer.refresh()  # type: ignore[union-attr]
        except Exception:
            pass
        return moved

    def _persist_load_order(self, plugin_list: mobase.IPluginList) -> None:
        """Write <profile>/plugins.txt + loadorder.txt to disk.

        Must run BEFORE any refresh: a refresh re-reads the ESP list from disk,
        so persisting first is what makes the new order survive and reload.

        We first ask the GamePlugins feature (the "proper" MO path), but that
        call can silently no-op (e.g. its internal _last_read guard, or a pybind
        object-identity quirk when the feature is fetched back from Python), so
        we always verify the files exist and write them directly if not. The
        direct write mirrors MO's own format: one plugin per line, ordered by
        priority(), with a generated-by-MO header — loadorder.txt lists every
        plugin, plugins.txt only the active ones.
        """
        assert self._organizer is not None

        profile_dir = Path(self._organizer.profile().absolutePath())
        plugins_txt = profile_dir / "plugins.txt"
        loadorder_txt = profile_dir / "loadorder.txt"

        # 1) Best-effort: the canonical GamePlugins path.
        try:
            game_plugins = self._organizer.gameFeatures().gameFeature(
                mobase.GamePlugins
            )
            if game_plugins is not None:
                game_plugins.writePluginLists(plugin_list)
        except Exception as exc:  # never let this abort the (verified) direct write
            qWarning(f"OpenMW LOOT: GamePlugins.writePluginLists failed: {exc}")

        # 2) Verify; if the feature did not actually write, do it ourselves.
        if self._files_nonempty(plugins_txt, loadorder_txt):
            qInfo(f"OpenMW LOOT: persisted load order to {profile_dir}")
            return

        names = list(plugin_list.pluginNames())

        def _prio(name: str) -> int:
            try:
                return plugin_list.priority(name)
            except Exception:
                return 1 << 30

        ordered = sorted(names, key=_prio)

        def _is_active(name: str) -> bool:
            try:
                return plugin_list.state(name) == mobase.PluginState.ACTIVE
            except Exception:
                return False

        header = "# This file was automatically generated by Mod Organizer.\n"
        try:
            loadorder_txt.write_text(
                header + "".join(f"{n}\n" for n in ordered), encoding="utf-8"
            )
            active_lines = [n for n in ordered if _is_active(n)]
            plugins_txt.write_text(
                header + "".join(f"{n}\n" for n in active_lines), encoding="utf-8"
            )
        except OSError as exc:
            raise RuntimeError(f"could not write the load order to disk ({exc}).")

        qInfo(
            "OpenMW LOOT: persisted load order to %s (%d plugins, %d active)"
            % (profile_dir, len(ordered), len(active_lines))
        )

    @staticmethod
    def _files_nonempty(*paths: Path) -> bool:
        try:
            return all(p.is_file() and p.stat().st_size > 0 for p in paths)
        except OSError:
            return False

    # --- main ----------------------------------------------------------

    def _run(self) -> None:
        assert self._organizer is not None
        if not _LOOT_AVAILABLE:
            self._error(
                "LOOT support (libloot) is not available in this build, so "
                "sorting cannot run. The Plugins tab is unchanged.\n\n"
                f"Import error: {_LOOT_IMPORT_ERROR}"
            )
            return

        game = self._organizer.managedGame()
        try:
            from ...game_openmw import OpenMWGame

            if not isinstance(game, OpenMWGame):
                self._error("This tool only works with the OpenMW game plugin.")
                return
        except Exception:
            # If we cannot even import the game class, bail safely.
            self._error("Could not resolve the OpenMW game plugin.")
            return

        active = self._active_plugins_from_tab(game)
        if not active:
            self._info(
                "There are no active plugins to sort. Enable some plugins in "
                "the Plugins tab first."
            )
            return

        cfg = self._locate_cfg(game)
        game_path = self._resolve_game_path(cfg)
        if game_path is None:
            self._error(
                "Could not locate the OpenMW install. Run OpenMW once to create "
                "openmw.cfg, or set 'openmw_install_path' in this tool's "
                "settings, then try again."
            )
            return
        local_path = cfg.parent if cfg is not None else None
        data_dirs = self._data_directories(game)
        ml_cache, ml_url, ml_download = self._masterlist_plan()
        qInfo(
            "OpenMW LOOT: [ck0] inputs gathered on main thread; game_path=%r "
            "cfg=%r data_dirs=%d active=%d ml_cache=%r"
            % (str(game_path), str(cfg), len(data_dirs), len(active), ml_cache)
        )

        # --- run the blocking libloot pipeline off the UI thread -------
        # All inputs are plain data; the worker never touches a mobase/Qt object.
        # The result is applied back here, on the main thread, after the dialog
        # closes. On any failure the load order is left exactly as it was.
        worker = _LootWorker(
            str(game_path),
            str(local_path) if local_path is not None else None,
            [str(p) for p in data_dirs],
            list(active),
            ml_cache,
            ml_url,
            ml_download,
        )
        # No parent: `self` is a mobase plugin (IPluginTool/IPlugin), NOT a
        # QObject, so it can't parent a QThread. We keep a strong ref in
        # self._sort_thread below to stop it being GC'd while it runs.
        thread = QThread()
        worker.moveToThread(thread)

        parent = None
        try:
            parent = self._parentWidget()
        except Exception:
            parent = None

        dialog = QProgressDialog(
            self._tr("Preparing to sort with LOOT..."), "", 0, 0, parent
        )
        dialog.setWindowTitle(self._tr("Sort with LOOT (OpenMW)"))
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setCancelButton(None)  # libloot can't be safely interrupted
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumWidth(380)

        self._sort_dialog = dialog
        self._sort_thread = thread
        self._sort_worker = worker

        # Route the worker's signals to QObjects that live on the main thread
        # (the dialog and the thread). `self` is a mobase plugin, not a QObject,
        # so it can't be a queued-connection receiver — connecting to its bound
        # methods would run the slots on the worker thread and touch the GUI off
        # the UI thread. The worker stashes its result on itself; we read it
        # after thread.wait() (a join, so the read is safely ordered).
        worker.progress.connect(
            dialog.setLabelText, Qt.ConnectionType.QueuedConnection
        )
        # Stop the thread's event loop and close the modal dialog (which makes
        # exec() return) once the worker is done.
        worker.finished.connect(thread.quit, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(dialog.close, Qt.ConnectionType.QueuedConnection)
        thread.started.connect(worker.run)

        try:
            thread.start()
            dialog.exec()  # spins the event loop until the worker is done
            thread.wait(5000)
        finally:
            self._sort_dialog = None
            self._sort_thread = None

        done = worker.result_done
        error = worker.result_error
        sorted_active = worker.result_sorted
        self._sort_worker = None

        if not done:
            self._error(
                "LOOT sorting did not complete, so the load order was not changed."
            )
            return
        if error:
            self._error(
                "LOOT could not sort the plugins, so the load order was left "
                f"unchanged.\n\n{error}"
            )
            return

        if not sorted_active:
            self._error(
                "LOOT returned no result, so the load order was not changed."
            )
            return

        try:
            moved = self._apply(
                self._organizer.pluginList(), list(active), list(sorted_active)
            )
        except Exception as exc:
            import traceback

            qWarning("OpenMW LOOT: _apply failed: %s\n%s"
                     % (exc, traceback.format_exc()))
            self._error(
                "The sorted order from LOOT could not be applied safely, so the "
                f"load order was left unchanged.\n\n{exc}"
            )
            return

        if moved == 0:
            self._info("Nothing was moved.")
        else:
            self._info(f"{moved} plugin(s) were moved.")
