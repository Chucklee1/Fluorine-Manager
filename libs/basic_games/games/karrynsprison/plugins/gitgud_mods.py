from __future__ import annotations

# PyQt's dynamically generated signal types are intentionally incomplete.
# pyright: reportUnknownMemberType=false
import html
import json
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypedDict, cast
from urllib.parse import unquote, urlparse

from PyQt6.QtCore import QSize, QStandardPaths, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPalette,
    QPixmap,
)
from PyQt6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkDiskCache,
    QNetworkReply,
    QNetworkRequest,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import mobase

MODS_DATABASE_URL = (
    "https://gitgud.io/karryn-prison-mods/modding-wiki/-/raw/master/modslist-db.json"
)
GAME_NAME = "Karryn's Prison"
DETAIL_IMAGE_SIZE = QSize(384, 216)
INSTALLED_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class ModVersion(TypedDict, total=False):
    version: str
    createdAt: str
    urls: list[str]


class ModEntry(TypedDict, total=False):
    id: int
    projectId: int
    title: str
    titles: list[str]
    author: str | None
    stars: int
    dependencies: list[int]
    metadata: dict[str, str]
    previewUrl: str
    versions: list[ModVersion]
    url: str


def latest_version(mod: ModEntry) -> ModVersion | None:
    versions = mod.get("versions")
    if not versions:
        return None
    return max(versions, key=lambda version: version.get("createdAt", ""))


def primary_title(mod: ModEntry) -> str:
    titles = mod.get("titles")
    if isinstance(titles, list) and titles:
        return str(titles[0])
    return str(mod.get("title") or f"GitGud project {mod.get('projectId', '?')}")


def dependency_order(
    selected: ModEntry, mods_by_id: dict[int, ModEntry]
) -> list[ModEntry]:
    """Return dependencies before the selected mod, without duplicates."""
    ordered: list[ModEntry] = []
    visited: set[int] = set()

    def visit(mod: ModEntry) -> None:
        mod_id = mod.get("id")
        if mod_id is None:
            return
        if mod_id in visited:
            return
        visited.add(mod_id)
        for dependency_id in mod.get("dependencies") or []:
            dependency = mods_by_id.get(dependency_id)
            if dependency is not None:
                visit(dependency)
        ordered.append(mod)

    visit(selected)
    return ordered


def is_direct_download(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname is not None
        and parsed.hostname.casefold().endswith("gitgud.io")
        and parsed.path.startswith("/api/v4/")
    )


def plain_description(mod: ModEntry) -> str:
    metadata = mod.get("metadata") or {}
    value = metadata.get("description") or metadata.get("shortDescription") or ""
    value = re.sub(r"<br\s*/?>", "\n", str(value), flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).strip()


def newest_date(mod: ModEntry) -> str:
    latest = latest_version(mod)
    return latest.get("createdAt", "") if latest else ""


def preview_pixmap(source: QPixmap) -> QPixmap:
    """Scale and center-crop a preview to a 16:9 details image."""
    if source.isNull():
        return placeholder_pixmap()
    scaled = source.scaled(
        DETAIL_IMAGE_SIZE,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    left = max(0, (scaled.width() - DETAIL_IMAGE_SIZE.width()) // 2)
    top = max(0, (scaled.height() - DETAIL_IMAGE_SIZE.height()) // 2)
    return scaled.copy(left, top, DETAIL_IMAGE_SIZE.width(), DETAIL_IMAGE_SIZE.height())


def placeholder_pixmap() -> QPixmap:
    pixmap = QPixmap(DETAIL_IMAGE_SIZE)
    pixmap.fill(QColor("#171d24"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#aeb7c2"))
    font = painter.font()
    font.setBold(True)
    font.setPointSize(max(12, font.pointSize() + 4))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "GitGud Mods")
    painter.end()
    return pixmap


def normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def download_filename(url: str) -> str:
    return unquote(Path(urlparse(url).path).name)


def comparable_download_name(filename: str) -> str:
    """Remove MO2's numeric collision prefix before comparing archives."""
    return re.sub(r"^\d+_", "", filename).casefold()


@dataclass
class InstallTask:
    mod: ModEntry
    urls: list[str]
    filename: str
    is_selected: bool
    force_reinstall: bool = False
    archive_path: str | None = None

    @property
    def title(self) -> str:
        return primary_title(self.mod)

    @property
    def version(self) -> str:
        latest = latest_version(self.mod)
        return str(latest.get("version", "")) if latest else ""


class GitGudInstallController:
    """Download and install one dependency-ordered task at a time."""

    def __init__(self, organizer: mobase.IOrganizer):
        self._organizer = organizer
        self._manager = organizer.downloadManager()
        self._queue: deque[InstallTask] = deque()
        self._active: InstallTask | None = None
        self._installing: InstallTask | None = None
        self._status_callback: Callable[[str], None] | None = None
        self._state_callback: Callable[[], None] | None = None
        self._manager.onDownloadComplete(self._download_complete)
        self._manager.onDownloadFailed(self._download_failed)

    def set_status_callback(self, callback: Callable[[str], None] | None) -> None:
        self._status_callback = callback

    def set_state_callback(self, callback: Callable[[], None] | None) -> None:
        self._state_callback = callback

    def _report(self, message: str) -> None:
        if self._status_callback is not None:
            self._status_callback(message)

    def is_installed(self, mod: ModEntry) -> bool:
        latest = latest_version(mod)
        urls = (latest.get("urls") if latest else None) or []
        filename = download_filename(urls[0]) if urls else ""
        return (
            self._matching_installed(InstallTask(mod, [], filename, is_selected=True))
            is not None
        )

    def enqueue(
        self,
        mods: list[ModEntry],
        selected: ModEntry,
        reinstall_selected: bool = False,
    ) -> None:
        queued_names = {comparable_download_name(task.filename) for task in self._queue}
        if self._active is not None:
            queued_names.add(comparable_download_name(self._active.filename))
        if self._installing is not None:
            queued_names.add(comparable_download_name(self._installing.filename))

        installed = 0
        downloaded = 0
        downloading = 0
        queued = 0
        for mod in mods:
            latest = latest_version(mod)
            urls = [
                url
                for url in (latest.get("urls") if latest else None) or []
                if is_direct_download(url)
            ]
            if not urls:
                continue
            filename = download_filename(urls[0])
            if not filename:
                continue
            task = InstallTask(
                mod,
                urls,
                filename,
                is_selected=mod is selected,
                force_reinstall=reinstall_selected and mod is selected,
            )
            key = comparable_download_name(filename)
            if key in queued_names:
                downloading += 1
                continue
            if self._installed_satisfies(task):
                existing = self._matching_installed(task)
                if existing is not None:
                    self._organizer.modList().setActive(existing.name(), True)
                installed += 1
                continue
            archive = self._downloaded_archive(task)
            if archive is not None:
                task.archive_path = str(archive)
                downloaded += 1
            elif self._download_in_progress(task):
                downloading += 1
                continue
            self._queue.append(task)
            queued_names.add(key)
            queued += 1

        if queued == 0:
            parts: list[str] = []
            if installed:
                parts.append(f"{installed} already installed")
            if downloaded:
                parts.append(f"{downloaded} already downloaded")
            if downloading:
                parts.append(f"{downloading} already downloading")
            self._report("Nothing new queued: " + ", ".join(parts) + ".")
            return

        self._report(
            f"Queued {queued} mod(s) for sequential download and installation; "
            f"skipped {installed} installed and {downloading} active."
        )
        self._advance()

    def _task_aliases(self, task: InstallTask) -> set[str]:
        aliases = {normalized_name(title) for title in task.mod.get("titles") or []}
        aliases.add(normalized_name(task.title))
        project_path = str(task.mod.get("url") or "").split("/-/", 1)[0]
        aliases.add(normalized_name(Path(urlparse(project_path).path).name))
        archive_stem = normalized_name(Path(task.filename).stem)
        version = normalized_name(task.version)
        if version and archive_stem.endswith(version):
            archive_stem = archive_stem[: -len(version)]
        aliases.add(archive_stem)
        return {alias for alias in aliases if alias}

    def _matching_installed(self, task: InstallTask) -> mobase.IModInterface | None:
        aliases = self._task_aliases(task)
        mod_list = self._organizer.modList()
        for internal_name in mod_list.allMods():
            installed = cast(
                mobase.IModInterface | None, mod_list.getMod(internal_name)
            )
            if installed is None:
                continue
            values = {
                normalized_name(internal_name),
                normalized_name(mod_list.displayName(internal_name)),
                normalized_name(Path(installed.installationFile()).stem),
            }
            if aliases.intersection(values):
                return installed
        return None

    def _installed_satisfies(self, task: InstallTask) -> bool:
        installed = self._matching_installed(task)
        if installed is None:
            return False
        if task.force_reinstall:
            return False
        # Dependencies have no minimum-version constraint in the GitGud database,
        # so any installed match satisfies them. The explicitly selected mod can
        # still update when both versions are known.
        if not task.is_selected:
            return True
        current = installed.version()
        target = mobase.VersionInfo(task.version)
        return not current.isValid() or not target.isValid() or current >= target

    def _downloaded_archive(self, task: InstallTask) -> Path | None:
        downloads = Path(self._organizer.downloadsPath())
        if not downloads.is_dir():
            return None
        expected = comparable_download_name(task.filename)
        for candidate in downloads.iterdir():
            if (
                candidate.is_file()
                and not candidate.name.endswith((".meta", ".unfinished"))
                and comparable_download_name(candidate.name) == expected
            ):
                return candidate
        return None

    def _download_in_progress(self, task: InstallTask) -> bool:
        downloads = Path(self._organizer.downloadsPath())
        if not downloads.is_dir():
            return False
        expected = comparable_download_name(task.filename)
        for candidate in downloads.iterdir():
            name = candidate.name.removesuffix(".meta")
            if not name.endswith(".unfinished"):
                continue
            name = name.removesuffix(".unfinished")
            if comparable_download_name(name) == expected:
                return True
        return False

    def _advance(self) -> None:
        if self._active is not None or self._installing is not None:
            return
        while self._queue:
            task = self._queue.popleft()
            if self._installed_satisfies(task):
                continue
            archive = (
                Path(task.archive_path)
                if task.archive_path is not None
                else self._downloaded_archive(task)
            )
            if archive is not None and archive.is_file():
                self._schedule_install(task, archive)
                return
            self._active = task
            if self._manager.startDownloadURLs(task.urls) == 0:
                self._report(f"Could not start the download for {task.title}.")
                self._active = None
                self._queue.clear()
                return
            self._report(f"Downloading {task.title} {task.version}…")
            return
        self._report("GitGud download and installation queue complete.")

    def _callback_path(self, download_id: int) -> Path | None:
        try:
            return Path(self._manager.downloadPath(download_id))
        except Exception:
            return None

    def _is_active_download(self, path: Path | None) -> bool:
        return (
            self._active is not None
            and path is not None
            and comparable_download_name(path.name)
            == comparable_download_name(self._active.filename)
        )

    def _download_complete(self, download_id: int) -> None:
        path = self._callback_path(download_id)
        if not self._is_active_download(path) or path is None:
            return
        task = self._active
        self._active = None
        if task is not None:
            self._schedule_install(task, path)
            return
        self._advance()

    def _download_failed(self, download_id: int) -> None:
        path = self._callback_path(download_id)
        if not self._is_active_download(path):
            return
        task = self._active
        self._active = None
        self._queue.clear()
        self._report(
            f"Download failed for {task.title if task is not None else 'GitGud mod'}."
        )

    def _schedule_install(self, task: InstallTask, archive: Path) -> None:
        """Leave the download callback before entering Fluorine's installer."""
        if self._installing is not None:
            return
        self._installing = task
        self._report(f"Installing {task.title} {task.version}…")
        QTimer.singleShot(0, lambda: self._install(task, archive))

    def _install(self, task: InstallTask, archive: Path) -> None:
        existing = self._matching_installed(task)
        suggestion = existing.name() if existing is not None else task.title
        try:
            installed = cast(
                mobase.IModInterface | None,
                self._organizer.installMod(str(archive), suggestion),
            )
        except Exception as error:
            self._abort_install(task, f"Installation failed for {task.title}: {error}")
            return
        if installed is None:
            self._abort_install(task, f"Installation was cancelled for {task.title}.")
            return
        try:
            version = mobase.VersionInfo(task.version)
            if version.isValid():
                installed.setVersion(version)
                installed.setNewestVersion(version)
            installed.setUrl(str(task.mod.get("url") or ""))
            installed_name = installed.name()
            registered = self._organizer.onNextRefresh(
                lambda: self._finish_install(task, installed_name), False
            )
        except Exception as error:
            self._abort_install(task, f"Installation failed for {task.title}: {error}")
            return
        if not registered:
            QTimer.singleShot(0, lambda: self._finish_install(task, installed_name))

    def _finish_install(self, task: InstallTask, installed_name: str) -> None:
        if self._installing is not task:
            return
        try:
            enabled = self._organizer.modList().setActive(installed_name, True)
        except Exception as error:
            self._abort_install(task, f"Could not enable {task.title}: {error}")
            return
        self._installing = None
        if self._state_callback is not None:
            self._state_callback()
        if enabled:
            self._report(f"Installed and enabled {task.title} {task.version}.")
        else:
            self._report(
                f"Installed {task.title} {task.version}, but Fluorine could not "
                "enable it automatically."
            )
        self._advance()

    def _abort_install(self, task: InstallTask, message: str) -> None:
        if self._installing is task:
            self._installing = None
        self._queue.clear()
        self._report(message)


class GitGudModsDialog(QDialog):
    def __init__(
        self,
        organizer: mobase.IOrganizer,
        installer: GitGudInstallController,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._organizer = organizer
        self._installer = installer
        self._mods: list[ModEntry] = []
        self._mods_by_id: dict[int, ModEntry] = {}
        self._network = QNetworkAccessManager(self)
        self._cache = QNetworkDiskCache(self._network)
        cache_root = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.CacheLocation
        )
        self._cache.setCacheDirectory(f"{cache_root}/gitgud-mod-images")
        self._cache.setMaximumCacheSize(64 * 1024 * 1024)
        self._network.setCache(self._cache)
        self._reply: QNetworkReply | None = None
        self._selection_serial = 0
        self._placeholder = placeholder_pixmap()

        self.setWindowTitle("Karryn's Prison — GitGud Mods")
        self.resize(1180, 760)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Community-maintained integrated mods. Fluorine downloads, installs, and "
            "enables the selected mod and its dependencies in order."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        filter_row = QHBoxLayout()
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Search by title, author, or description…")
        self._sort = QComboBox()
        self._sort.addItem("Newest", "newest")
        self._sort.addItem("Alphabetical", "alphabetical")
        self._refresh = QPushButton("Refresh")
        filter_row.addWidget(self._filter, 1)
        filter_row.addWidget(self._sort)
        filter_row.addWidget(self._refresh)
        layout.addLayout(filter_row)

        splitter = QSplitter()
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Mod", "Latest", "Author", "Stars"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        header = self._tree.header()
        if header is not None:
            header.setStretchLastSection(False)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        details = QWidget()
        details_layout = QVBoxLayout(details)
        self._title = QLabel("Select a mod")
        title_font = self._title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 2)
        self._title.setFont(title_font)
        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumHeight(DETAIL_IMAGE_SIZE.height())
        self._preview.setPixmap(self._placeholder)
        self._description = QLabel()
        self._description.setWordWrap(True)
        self._description.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._dependencies = QLabel()
        self._dependencies.setWordWrap(True)
        readme_title = QLabel("README")
        readme_font = readme_title.font()
        readme_font.setBold(True)
        readme_title.setFont(readme_font)
        self._readme = QTextBrowser()
        self._readme.setOpenExternalLinks(True)
        self._readme.setMarkdown("Select a mod to load its project README.")
        details_layout.addWidget(self._title)
        details_layout.addWidget(self._preview)
        details_layout.addWidget(self._description)
        details_layout.addWidget(self._dependencies)
        details_layout.addWidget(readme_title)
        details_layout.addWidget(self._readme, 1)

        splitter.addWidget(self._tree)
        splitter.addWidget(details)
        splitter.setSizes([650, 500])
        layout.addWidget(splitter, 1)

        actions = QHBoxLayout()
        self._include_dependencies = QCheckBox("Include dependencies")
        self._include_dependencies.setChecked(True)
        self._open_page = QPushButton("Open project page")
        self._download = QPushButton("Download and Install")
        self._open_page.setEnabled(False)
        self._download.setEnabled(False)
        actions.addWidget(self._include_dependencies)
        actions.addStretch(1)
        actions.addWidget(self._open_page)
        actions.addWidget(self._download)
        layout.addLayout(actions)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.reject)
        layout.addWidget(close_buttons)

        self._filter.textChanged.connect(self._apply_filter)
        self._sort.currentIndexChanged.connect(self._populate)
        self._refresh.clicked.connect(self.load)
        self._tree.itemSelectionChanged.connect(self._selection_changed)
        self._tree.itemDoubleClicked.connect(self._item_double_clicked)
        self._open_page.clicked.connect(self._open_selected_page)
        self._download.clicked.connect(self._download_selected)

        self.load()

    def set_status(self, message: str) -> None:
        self._status.setText(message)

    def load(self) -> None:
        if self._reply is not None:
            return
        self._status.setText("Loading the GitGud mod list…")
        self._refresh.setEnabled(False)
        request = QNetworkRequest(QUrl(MODS_DATABASE_URL))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Fluorine")
        request.setAttribute(QNetworkRequest.Attribute.Http2AllowedAttribute, False)
        request.setTransferTimeout(15_000)
        reply = self._network.get(request)
        if reply is None:
            self._refresh.setEnabled(True)
            self._status.setText("Could not start the GitGud mod-list request.")
            return
        self._reply = reply
        reply.finished.connect(self._loaded)

    def _loaded(self) -> None:
        reply = self._reply
        self._reply = None
        self._refresh.setEnabled(True)
        if reply is None:
            return
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise RuntimeError(reply.errorString())
            payload = cast(object, json.loads(reply.readAll().data().decode("utf-8")))
            if not isinstance(payload, list):
                raise ValueError("the server returned an unexpected database format")
            entries = cast(list[object], payload)
            if not all(isinstance(entry, dict) for entry in entries):
                raise ValueError("the mod database contains an invalid entry")
            self._mods = cast(list[ModEntry], entries)
            self._mods_by_id = {}
            for mod in self._mods:
                mod_id = mod.get("id")
                if mod_id is not None:
                    self._mods_by_id[mod_id] = mod
            self._populate()
        except (json.JSONDecodeError, RuntimeError, ValueError) as error:
            self._tree.clear()
            self._status.setText(f"Could not load the GitGud mod list: {error}")
        finally:
            reply.deleteLater()

    def _populate(self, *_: object) -> None:
        self._tree.clear()
        mods = sorted(self._mods, key=lambda mod: primary_title(mod).casefold())
        if self._sort.currentData() == "newest":
            mods.sort(key=newest_date, reverse=True)

        for mod in mods:
            latest = latest_version(mod)
            version = str(latest.get("version", "")) if latest else "No release"
            item = QTreeWidgetItem(
                [
                    primary_title(mod),
                    version,
                    str(mod.get("author") or ""),
                    str(mod.get("stars") or 0),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, mod)
            item.setTextAlignment(3, Qt.AlignmentFlag.AlignRight)
            self._set_installed_style(item, self._installer.is_installed(mod))
            self._tree.addTopLevelItem(item)

        self._apply_filter(self._filter.text())

    def _set_installed_style(self, item: QTreeWidgetItem, installed: bool) -> None:
        item.setData(0, INSTALLED_ROLE, installed)
        muted = QBrush(
            self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        )
        for column in range(item.columnCount()):
            font = item.font(column)
            font.setItalic(installed)
            item.setFont(column, font)
            item.setForeground(column, muted if installed else QBrush())

    def refresh_installed_state(self) -> None:
        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            if item is None:
                continue
            mod = cast(ModEntry, item.data(0, Qt.ItemDataRole.UserRole))
            self._set_installed_style(item, self._installer.is_installed(mod))
        selected = self._selected()
        if selected is not None:
            self._update_download_action(selected)

    def _update_download_action(self, mod: ModEntry) -> None:
        self._download.setText(
            "Download and Reinstall"
            if self._installer.is_installed(mod)
            else "Download and Install"
        )

    def _request(self, url_string: str) -> QNetworkReply | None:
        url = QUrl(url_string)
        if not url.isValid() or url.scheme() not in {"http", "https"}:
            return None
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Fluorine")
        request.setAttribute(QNetworkRequest.Attribute.Http2AllowedAttribute, False)
        request.setAttribute(
            QNetworkRequest.Attribute.CacheLoadControlAttribute,
            QNetworkRequest.CacheLoadControl.PreferCache,
        )
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        request.setTransferTimeout(15_000)
        return self._network.get(request)

    def _load_preview(self, mod: ModEntry, serial: int) -> None:
        preview_url = str(mod.get("previewUrl") or "")
        if not preview_url:
            return
        reply = self._request(preview_url)
        if reply is not None:
            reply.finished.connect(
                lambda reply=reply, serial=serial: self._preview_loaded(reply, serial)
            )

    def _preview_loaded(self, reply: QNetworkReply, serial: int) -> None:
        try:
            if (
                serial != self._selection_serial
                or reply.error() != QNetworkReply.NetworkError.NoError
            ):
                return
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll().data()):
                self._preview.setPixmap(preview_pixmap(pixmap))
        finally:
            reply.deleteLater()

    def _load_project_readme(self, mod: ModEntry, serial: int) -> None:
        project_id = mod.get("projectId")
        if project_id is None:
            self._load_readme_url(str(mod.get("url") or ""), serial)
            return
        reply = self._request(f"https://gitgud.io/api/v4/projects/{project_id}")
        if reply is None:
            self._load_readme_url(str(mod.get("url") or ""), serial)
            return
        reply.finished.connect(
            lambda reply=reply, mod=mod, serial=serial: self._project_loaded(
                reply, mod, serial
            )
        )

    def _project_loaded(self, reply: QNetworkReply, mod: ModEntry, serial: int) -> None:
        try:
            if serial != self._selection_serial:
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._load_readme_url(str(mod.get("url") or ""), serial)
                return
            value = cast(object, json.loads(reply.readAll().data().decode("utf-8")))
            if not isinstance(value, dict):
                self._load_readme_url(str(mod.get("url") or ""), serial)
                return
            project = cast(dict[str, object], value)
            if not plain_description(mod):
                project_description = project.get("description")
                if isinstance(project_description, str) and project_description:
                    self._description.setText(project_description)
            readme_url = project.get("readme_url")
            self._load_readme_url(
                readme_url
                if isinstance(readme_url, str)
                else str(mod.get("url") or ""),
                serial,
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._load_readme_url(str(mod.get("url") or ""), serial)
        finally:
            reply.deleteLater()

    def _load_readme_url(self, readme_url: str, serial: int) -> None:
        raw_url = readme_url.replace("/-/blob/", "/-/raw/")
        if raw_url == readme_url and "/-/raw/" not in raw_url:
            self._readme.setMarkdown("No project README is available.")
            return
        reply = self._request(raw_url)
        if reply is None:
            self._readme.setMarkdown("Could not request the project README.")
            return
        reply.finished.connect(
            lambda reply=reply, serial=serial: self._readme_loaded(reply, serial)
        )

    def _readme_loaded(self, reply: QNetworkReply, serial: int) -> None:
        try:
            if serial != self._selection_serial:
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._readme.setMarkdown(
                    f"Could not load the project README: {reply.errorString()}"
                )
                return
            markdown = reply.readAll().data().decode("utf-8", errors="replace")
            self._readme.setMarkdown(markdown or "The project README is empty.")
        finally:
            reply.deleteLater()

    def _apply_filter(self, query: str) -> None:
        needle = query.casefold().strip()
        visible = 0
        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            if item is None:
                continue
            mod = cast(ModEntry, item.data(0, Qt.ItemDataRole.UserRole))
            haystack = " ".join(
                [
                    " ".join(str(title) for title in mod.get("titles") or []),
                    str(mod.get("author") or ""),
                    plain_description(mod),
                ]
            ).casefold()
            hidden = bool(needle and needle not in haystack)
            item.setHidden(hidden)
            visible += int(not hidden)
        self._status.setText(f"Showing {visible} of {len(self._mods)} integrated mods.")

    def _selected(self) -> ModEntry | None:
        selected = self._tree.selectedItems()
        if not selected:
            return None
        value = selected[0].data(0, Qt.ItemDataRole.UserRole)
        return cast(ModEntry, value) if isinstance(value, dict) else None

    def _selection_changed(self) -> None:
        self._selection_serial += 1
        serial = self._selection_serial
        mod = self._selected()
        self._open_page.setEnabled(mod is not None)
        if mod is None:
            self._download.setEnabled(False)
            self._download.setText("Download and Install")
            self._title.setText("Select a mod")
            self._preview.setPixmap(self._placeholder)
            self._description.clear()
            self._dependencies.clear()
            self._readme.setMarkdown("Select a mod to load its project README.")
            return

        latest = latest_version(mod)
        self._update_download_action(mod)
        self._download.setEnabled(latest is not None)
        version = str(latest.get("version", "")) if latest else "no release"
        self._title.setText(f"{primary_title(mod)}  ·  {version}")
        self._preview.setPixmap(self._placeholder)
        self._description.setText(
            plain_description(mod) or "No database description; see the README below."
        )
        dependency_names: list[str] = []
        for dependency_id in mod.get("dependencies") or []:
            dependency = self._mods_by_id.get(dependency_id)
            if dependency is not None:
                dependency_names.append(primary_title(dependency))
        self._dependencies.setText(
            "Dependencies: " + (", ".join(dependency_names) or "none")
        )
        self._readme.setMarkdown("Loading project README…")
        self._load_preview(mod, serial)
        self._load_project_readme(mod, serial)

    def _open_selected_page(self) -> None:
        mod = self._selected()
        url = mod.get("url") if mod is not None else None
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _item_double_clicked(self, _item: QTreeWidgetItem, _column: int) -> None:
        self._open_selected_page()

    def _download_selected(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        mods = (
            dependency_order(selected, self._mods_by_id)
            if self._include_dependencies.isChecked()
            else [selected]
        )
        automatic: list[ModEntry] = []
        manual: list[tuple[str, str]] = []
        missing: list[str] = []

        for mod in mods:
            latest = latest_version(mod)
            urls = latest.get("urls") if latest else None
            urls = [url for url in urls or [] if url]
            title = primary_title(mod)
            if not urls:
                missing.append(title)
            elif any(is_direct_download(url) for url in urls):
                automatic.append(mod)
            else:
                manual.append((title, urls[0]))

        messages: list[str] = []
        if automatic:
            self._installer.enqueue(
                automatic,
                selected,
                reinstall_selected=self._installer.is_installed(selected),
            )
        if manual:
            names = ", ".join(title for title, _ in manual)
            messages.append(f"Manual download required: {names}.")
        if missing:
            messages.append("No release URL: " + ", ".join(missing) + ".")
        if messages:
            self._status.setText(" ".join(messages))

        # Open only the selected mod's external download. Opening every external
        # dependency would create a surprising burst of browser tabs.
        selected_manual = next(
            (url for title, url in manual if title == primary_title(selected)), None
        )
        if selected_manual:
            QDesktopServices.openUrl(QUrl(selected_manual))
            QMessageBox.information(
                self,
                "Manual download",
                "This release is hosted on a site that does not expose a direct "
                "download to Fluorine. Its download page was opened in your browser.",
            )


class GitGudModsTool(mobase.IPluginTool, mobase.IPlugin):
    def __init__(self) -> None:
        mobase.IPluginTool.__init__(self)
        mobase.IPlugin.__init__(self)
        self._organizer: mobase.IOrganizer | None = None
        self._parent: QWidget | None = None
        self._dialog: GitGudModsDialog | None = None
        self._installer: GitGudInstallController | None = None

    def init(self, organizer: mobase.IOrganizer) -> bool:
        self._organizer = organizer
        self._installer = GitGudInstallController(organizer)
        return True

    def name(self) -> str:
        return "Karryn's Prison GitGud Mods"

    def author(self) -> str:
        return "Fluorine contributors"

    def description(self) -> str:
        return "Browse integrated Karryn's Prison mods hosted through GitGud."

    def version(self) -> mobase.VersionInfo:
        return mobase.VersionInfo(1, 0, 0)

    def requirements(self):
        return [mobase.PluginRequirementFactory.gameDependency(GAME_NAME)]

    def settings(self) -> list[mobase.PluginSetting]:
        return []

    def displayName(self) -> str:
        return "Karryn's Prison/GitGud Mods"

    def tooltip(self) -> str:
        return "Browse the community GitGud mod list for Karryn's Prison."

    def icon(self) -> QIcon:
        return QIcon.fromTheme("applications-internet")

    def setParentWidget(self, parent: QWidget) -> None:
        self._parent = parent

    def display(self) -> None:
        if self._organizer is None or self._installer is None:
            return
        self._dialog = GitGudModsDialog(self._organizer, self._installer, self._parent)
        self._installer.set_status_callback(self._dialog.set_status)
        self._installer.set_state_callback(self._dialog.refresh_installed_state)
        self._dialog.exec()
        self._installer.set_status_callback(None)
        self._installer.set_state_callback(None)
        self._dialog = None
