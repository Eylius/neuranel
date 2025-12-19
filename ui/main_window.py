from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from getpass import getuser
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets, QtNetwork

from config import BASE_DIR, DEFAULT_PRESETS, PROJECT_MANAGER_VERSION, SUITE_VERSION, load_config, save_config
from storage import list_projects, load_loans, save_loans
from workers import MoveWorker, _handle_remove_readonly
from ui.dialogs import SetupDialog
from ui.widgets import ProjectCard, ProjectItem, TitleBar


class MainWindow(QtWidgets.QMainWindow):
    UPDATE_URL = "https://raw.githubusercontent.com/Eylius/neuranel/main/updates/version.json"

    def __init__(self, splash: QtWidgets.QSplashScreen | None = None) -> None:
        super().__init__()
        self._startup_splash = splash
        self.setWindowTitle("Neuranel")
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.Window
            | QtCore.Qt.WindowSystemMenuHint
            | QtCore.Qt.WindowMinimizeButtonHint
            | QtCore.Qt.WindowMaximizeButtonHint
        )
        self.setAttribute(QtCore.Qt.WA_NativeWindow, True)
        self.resize(1000, 640)
        self._setup_palette()
        self._suite_version = SUITE_VERSION
        self._pm_version = PROJECT_MANAGER_VERSION
        self.config: dict = load_config()
        self._ensure_theme_defaults()
        self.theme: str = self.config.get("theme", "dark")
        if self.theme not in DEFAULT_PRESETS:
            self.theme = "dark"
        self.accent_color: str = (
            self.config.get("presets", {}).get(self.theme, {}).get("accent")
            or self.config.get("accent_color", DEFAULT_PRESETS["dark"]["accent"])
        )
        self.accent_color2: str = (
            self.config.get("presets", {}).get(self.theme, {}).get("accent2")
            or self.config.get("accent_color2", DEFAULT_PRESETS["dark"]["accent2"])
        )
        self.loans: dict = {}
        self.local_borrowed: dict = {}
        self._threads: list[QtCore.QThread] = []
        self._workers: list[MoveWorker] = []
        self._worker_context: dict[MoveWorker, dict] = {}
        self._busy: bool = False
        self._shared_all: list[str] = []
        self._local_all: list[str] = []
        self._last_loans: dict | None = None
        self._last_shared: list[str] | None = None
        self._last_local: list[str] | None = None
        self._nav_anim: QtCore.QPropertyAnimation | None = None
        self._update_check_manager: QtNetwork.QNetworkAccessManager | None = None
        self._update_download_manager: QtNetwork.QNetworkAccessManager | None = None
        self._update_download_reply: QtNetwork.QNetworkReply | None = None
        self._update_progress: QtWidgets.QProgressDialog | None = None
        self._update_checked = False
        self._update_check_thread: QtCore.QThread | None = None
        self._update_check_worker: UpdateCheckWorker | None = None
        self._update_retry_count = 0

        self._ensure_config()
        # Sync theme after setup; setup may have updated config.
        self.theme = self.config.get("theme", self.theme)
        if self.theme not in DEFAULT_PRESETS:
            self.theme = "dark"
        self._apply_config_paths()
        self.library_paths: list[str] = self._load_library_paths()
        self._refresh_local_borrowed()

        central = QtWidgets.QWidget()
        central.setObjectName("background")
        self.setCentralWidget(central)

        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.title_bar = TitleBar(self, BASE_DIR / "assets" / "Neuranel_Logo_64x64.png")
        self.file_btn = QtWidgets.QToolButton()
        self.file_btn.setText("File")
        self.file_btn.setObjectName("settingsButton")
        self.file_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.file_btn.setAutoRaise(True)
        self.title_bar.extra_layout.addWidget(self.file_btn)
        self.options_btn = QtWidgets.QToolButton()
        self.options_btn.setText("Optionen ˅")
        self.options_btn.setObjectName("settingsButton")
        self.options_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.options_btn.setAutoRaise(True)
        self.options_btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        self.options_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.options_menu = QtWidgets.QMenu(self.options_btn)
        self.options_menu.setWindowFlag(QtCore.Qt.NoDropShadowWindowHint, True)
        self.options_menu.setProperty("menuRole", "top")
        self.options_menu.addAction("Settings", self._open_settings_dialog)
        self.options_btn.setMenu(self.options_menu)
        self.options_btn.installEventFilter(self)
        self.options_menu.setMouseTracking(True)
        self.options_menu.installEventFilter(self)
        self._options_menu_close_timer: QtCore.QTimer | None = None
        self._options_menu_watch_timer: QtCore.QTimer | None = None
        self.options_menu.aboutToHide.connect(self._stop_options_menu_watch)
        self.title_bar.extra_layout.addWidget(self.options_btn)

        self.help_btn = QtWidgets.QToolButton()
        self.help_btn.setText("Hilfe ˅")
        self.help_btn.setObjectName("settingsButton")
        self.help_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.help_btn.setAutoRaise(True)
        self.help_btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        self.help_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.help_menu = QtWidgets.QMenu(self.help_btn)
        self.help_menu.setWindowFlag(QtCore.Qt.NoDropShadowWindowHint, True)
        self.help_menu.setProperty("menuRole", "top")
        self.onboarding_menu = QtWidgets.QMenu("Onboarding", self.help_menu)
        self.onboarding_menu.setProperty("menuRole", "top")
        self.onboarding_menu.aboutToShow.connect(self._position_onboarding_submenu)
        self.onboarding_menu.addAction(
            "Projekt Manager", lambda: self._start_project_manager_onboarding(force=True)
        )
        self._onboarding_action = self.help_menu.addMenu(self.onboarding_menu)
        self._onboarding_action.setText("Onboarding ˃")
        self.help_menu.addAction("About", self._show_about_dialog)
        self.help_btn.setMenu(self.help_menu)
        self.help_btn.installEventFilter(self)
        self.help_menu.setMouseTracking(True)
        self.help_menu.installEventFilter(self)
        self.onboarding_menu.setMouseTracking(True)
        self.onboarding_menu.installEventFilter(self)
        self._help_menu_close_timer: QtCore.QTimer | None = None
        self._help_menu_watch_timer: QtCore.QTimer | None = None
        self.help_menu.aboutToHide.connect(self._stop_help_menu_watch)
        self.title_bar.extra_layout.addWidget(self.help_btn)
        main_layout.addWidget(self.title_bar)

        content_layout = QtWidgets.QHBoxLayout()
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self.nav_list = NavListWidget()
        self.nav_list.setObjectName("navList")
        self.nav_list.setIconSize(QtCore.QSize(22, 22))
        self.nav_list.setMouseTracking(True)
        self.nav_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.nav_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        def add_nav_item(icon_filename: str, tooltip: str) -> None:
            icon_path = BASE_DIR / "assets" / icon_filename
            icon = self._build_nav_icon(icon_path) if icon_path.exists() else self.style().standardIcon(QtWidgets.QStyle.SP_FileIcon)
            item = QtWidgets.QListWidgetItem()
            item.setIcon(icon)
            item.setToolTip(tooltip)
            item.setData(QtCore.Qt.UserRole + 2, tooltip)
            item.setData(QtCore.Qt.UserRole + 3, icon_filename)
            item.setText("")
            self.nav_list.addItem(item)

        add_nav_item("Projects.png", "Projects")
        add_nav_item("Project_Manager.png", "Project Manager")
        add_nav_item("Block_Editor.png", "Block Editor")
        add_nav_item("Placeholder.png", "Tab 2")
        add_nav_item("Placeholder.png", "Tab 3")
        self.nav_list.hoverEntered.connect(self._expand_nav)
        self.nav_list.hoverLeft.connect(self._schedule_nav_collapse)

        nav_container = QtWidgets.QFrame()
        nav_container.setObjectName("navContainer")
        nav_container.setFixedWidth(48)
        self.nav_container = nav_container
        self.nav_container.setMouseTracking(True)
        self.nav_container.installEventFilter(self)
        self.nav_list.installEventFilter(self)
        nav_layout = QtWidgets.QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)
        nav_layout.addWidget(self.nav_list)
        self._nav_dock_layout = nav_layout
        self._nav_overlay: QtWidgets.QFrame | None = None
        self._nav_overlay_layout: QtWidgets.QVBoxLayout | None = None
        self._nav_expanded = False
        self._nav_overlay_anim: QtCore.QAbstractAnimation | None = None
        self._nav_close_timer: QtCore.QTimer | None = None
        self._nav_hover_watch_timer: QtCore.QTimer | None = None

        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self._build_title_tab())
        projects_tab = self._build_projects_tab()
        self.stack.addWidget(projects_tab)
        self.block_editor_tab = self._build_block_editor_tab()
        self.stack.addWidget(self.block_editor_tab)
        self.stack.addWidget(self._build_placeholder_tab("Tab 2 Inhalt"))
        self.stack.addWidget(self._build_placeholder_tab("Tab 3 Inhalt"))
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        self.nav_list.setCurrentRow(1)

        main_panel = QtWidgets.QWidget()
        main_panel_layout = QtWidgets.QVBoxLayout(main_panel)
        main_panel_layout.setContentsMargins(5, 5, 5, 5)
        main_panel_layout.setSpacing(0)
        main_panel_layout.addWidget(self.stack)

        separator = QtWidgets.QFrame()
        separator.setObjectName("navSeparator")
        separator.setFixedWidth(1)

        content_layout.addWidget(nav_container)
        content_layout.addWidget(separator)
        content_layout.addWidget(main_panel, 1)
        main_layout.addLayout(content_layout, 1)

        self.bottom_bar = QtWidgets.QFrame()
        self.bottom_bar.setObjectName("bottomBar")
        self.bottom_bar.setFixedHeight(20)
        bottom_layout = QtWidgets.QHBoxLayout(self.bottom_bar)
        bottom_layout.setContentsMargins(16, 4, 16, 4)
        bottom_layout.setSpacing(8)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("holderLabel")
        bottom_layout.addWidget(self.status_label)
        bottom_layout.addStretch(1)
        main_layout.addWidget(self.bottom_bar)

        self._apply_styles()
        self._refresh_nav_icons()
        self.refresh_lists()
        self._start_loans_poll()
        self._nav_hover_enabled = False
        self._nav_ignore_enter = False
        QtCore.QTimer.singleShot(0, self._init_nav_collapsed)
        QtCore.QTimer.singleShot(350, self._maybe_show_project_manager_onboarding)
        QtCore.QTimer.singleShot(600, self._maybe_show_pending_changelog)
        QtCore.QTimer.singleShot(900, self._check_for_updates)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if getattr(self, "_nav_overlay", None) is not None:
            self._update_nav_overlay_geometry()

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # type: ignore[override]
        super().showEvent(event)
        # Defer update check until the window is visible to avoid timing issues.
        if not self._update_checked:
            QtCore.QTimer.singleShot(500, self._check_for_updates)

    def _start_loans_poll(self) -> None:
        self._loans_poll_timer = QtCore.QTimer(self)
        self._loans_poll_timer.setInterval(5000)
        self._loans_poll_timer.timeout.connect(self._poll_loans_json)
        self._loans_poll_timer.start()

    def _poll_loans_json(self) -> None:
        # Cheap polling: only reload loans.json; refresh lists only when the content changes.
        if not getattr(self, "loans_file", None):
            return
        try:
            new_loans = load_loans(self.loans_file)
        except Exception:
            return
        self._refresh_local_borrowed()
        if new_loans == self._last_loans:
            return
        self.loans = new_loans
        self._last_loans = new_loans
        if hasattr(self, "shared_view"):
            self._apply_shared_filter()
        if hasattr(self, "local_view"):
            self._apply_local_filter()

    def _init_nav_collapsed(self) -> None:
        # Ensure the navbar starts collapsed even if the cursor is already over it on startup.
        self._nav_expanded = False
        self._collapse_nav()
        self._nav_hover_enabled = True

    def _maybe_show_project_manager_onboarding(self) -> None:
        # Nur automatisch anzeigen, wenn Onboarding-Flag noch nicht gesetzt ist.
        self._start_project_manager_onboarding(force=False)

    def _maybe_show_pending_changelog(self) -> None:
        pending_version = self.config.get("pending_suite_version")
        pending_text = self.config.get("pending_changelog")
        current_version = self._suite_version

        if pending_version and pending_text and pending_version == current_version:
            self._show_update_success_dialog(current_version, pending_text)
            self.config["last_seen_suite_version"] = current_version
            self.config["pending_suite_version"] = ""
            self.config["pending_changelog"] = ""
            save_config(self.config)
            return

        if not self.config.get("last_seen_suite_version"):
            self.config["last_seen_suite_version"] = current_version
            save_config(self.config)

    def _show_update_success_dialog(self, version: str, changelog: str) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Update erfolgreich")
        dialog.setObjectName("background")
        dialog.setModal(True)
        dialog.setMinimumSize(520, 360)
        dialog.setStyleSheet(self._build_stylesheet(self._current_colors()))

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QtWidgets.QLabel(f"Update erfolgreich – Version {version}")
        header.setObjectName("cardTitle")
        layout.addWidget(header)

        text = QtWidgets.QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(changelog)
        text.setObjectName("card")
        layout.addWidget(text, 1)

        close_btn = QtWidgets.QPushButton("Schließen")
        close_btn.setObjectName("primaryButton")
        close_btn.clicked.connect(dialog.accept)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        dialog.exec()

    @staticmethod
    def _parse_version(value: str) -> list[int]:
        parts = []
        number = ""
        for ch in value:
            if ch.isdigit():
                number += ch
            elif number:
                parts.append(int(number))
                number = ""
        if number:
            parts.append(int(number))
        return parts or [0]

    @classmethod
    def _is_newer_version(cls, current: str, candidate: str) -> bool:
        left = cls._parse_version(current)
        right = cls._parse_version(candidate)
        max_len = max(len(left), len(right))
        left.extend([0] * (max_len - len(left)))
        right.extend([0] * (max_len - len(right)))
        return right > left

    def _check_for_updates(self) -> None:
        if self._update_checked:
            return
        self._update_checked = True
        if not self.UPDATE_URL:
            return
        if self._update_check_thread and self._update_check_thread.isRunning():
            return
        thread = QtCore.QThread(self)
        worker = UpdateCheckWorker(self.UPDATE_URL)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_update_check_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._update_check_thread = thread
        self._update_check_worker = worker
        thread.start()

    def _handle_update_check_result(self, data: object, error: str) -> None:
        if error:
            short_error = error.strip().replace("\n", " ")
            if len(short_error) > 120:
                short_error = short_error[:117] + "..."
            self._set_status(f"Updatecheck fehlgeschlagen: {short_error}")
            if self._update_retry_count < 1:
                self._update_retry_count += 1
                self._update_checked = False
                QtCore.QTimer.singleShot(8000, self._check_for_updates)
            return
        if not isinstance(data, dict):
            self._set_status("Updatecheck: ungueltige Antwort.")
            return
        self._set_status("")
        self._handle_update_payload(data)

    def _handle_update_payload(self, data: dict) -> None:
        latest = str(data.get("suite_version") or "").strip()
        if not latest:
            return
        if not self._is_newer_version(self._suite_version, latest):
            return

        info = {
            "version": latest,
            "changelog": str(data.get("changelog") or "").strip(),
            "url": str(data.get("windows_url") or data.get("url") or "").strip(),
        }
        if not info["url"]:
            return
        self._show_update_prompt(info)

    def _show_update_prompt(self, info: dict) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Update verfügbar")
        dialog.setObjectName("background")
        dialog.setModal(True)
        dialog.setMinimumSize(520, 260)
        dialog.setStyleSheet(self._build_stylesheet(self._current_colors()))

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QtWidgets.QLabel("Update verfügbar")
        header.setObjectName("cardTitle")
        layout.addWidget(header)

        version_line = QtWidgets.QLabel(f"Neue Suite-Version: {info['version']}")
        version_line.setObjectName("holderLabel")
        layout.addWidget(version_line)

        copy = QtWidgets.QLabel(
            "Möchtest du das Update jetzt herunterladen und installieren?"
        )
        copy.setObjectName("holderLabel")
        copy.setWordWrap(True)
        layout.addWidget(copy)

        if info.get("changelog"):
            preview = QtWidgets.QLabel(info["changelog"])
            preview.setObjectName("holderLabel")
            preview.setWordWrap(True)
            layout.addWidget(preview)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        later_btn = QtWidgets.QPushButton("Später")
        later_btn.setObjectName("secondaryButton")
        later_btn.setCursor(QtCore.Qt.PointingHandCursor)
        later_btn.clicked.connect(dialog.reject)
        update_btn = QtWidgets.QPushButton("Update")
        update_btn.setObjectName("primaryButton")
        update_btn.setCursor(QtCore.Qt.PointingHandCursor)
        update_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(later_btn)
        btn_row.addWidget(update_btn)
        layout.addLayout(btn_row)

        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self._start_update_download(info)

    def _start_update_download(self, info: dict) -> None:
        if self._update_download_manager is None:
            self._update_download_manager = QtNetwork.QNetworkAccessManager(self)
        url = QtCore.QUrl(info["url"])
        reply = self._update_download_manager.get(QtNetwork.QNetworkRequest(url))
        self._update_download_reply = reply

        progress = QtWidgets.QProgressDialog("Update wird heruntergeladen...", "Abbrechen", 0, 100, self)
        progress.setWindowTitle("Update")
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setStyleSheet(self._build_stylesheet(self._current_colors()))
        progress.canceled.connect(lambda: reply.abort())
        self._update_progress = progress
        progress.show()

        reply.downloadProgress.connect(self._on_update_progress)
        reply.finished.connect(lambda: self._finish_update_download(info, reply))

    def _on_update_progress(self, received: int, total: int) -> None:
        if not self._update_progress:
            return
        if total > 0:
            pct = int(received * 100 / total)
            self._update_progress.setValue(pct)
        else:
            self._update_progress.setRange(0, 0)

    def _finish_update_download(self, info: dict, reply: QtNetwork.QNetworkReply) -> None:
        if self._update_progress:
            self._update_progress.hide()
            self._update_progress.deleteLater()
            self._update_progress = None
        try:
            if reply.error() != QtNetwork.QNetworkReply.NoError:
                QtWidgets.QMessageBox.warning(
                    self, "Update fehlgeschlagen", "Download fehlgeschlagen."
                )
                return
            status_code = reply.attribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute)
            if isinstance(status_code, int) and status_code >= 400:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Update fehlgeschlagen",
                    f"Download fehlgeschlagen (HTTP {status_code}).",
                )
                return
            data = bytes(reply.readAll())
            if data.lstrip().startswith(b"<!DOCTYPE") or data.lstrip().startswith(b"<html"):
                QtWidgets.QMessageBox.warning(
                    self,
                    "Update fehlgeschlagen",
                    "Download lieferte HTML statt einer EXE. Bitte pruefe die Release-URL.",
                )
                return
            if len(data) < 50_000:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Update fehlgeschlagen",
                    "Download ist zu klein und scheint ungueltig zu sein.",
                )
                return
            temp_dir = Path(tempfile.gettempdir())
            filename = f"NeuranelUpdate_{info['version']}.exe"
            target = temp_dir / filename
            with target.open("wb") as f:
                f.write(data)
            self.config["pending_suite_version"] = info.get("version", "")
            self.config["pending_changelog"] = info.get("changelog", "")
            save_config(self.config)

            started = QtCore.QProcess.startDetached(str(target))
            if not started:
                try:
                    if hasattr(os, "startfile"):
                        os.startfile(str(target))
                        started = True
                except OSError:
                    started = False

            if started:
                QtWidgets.QApplication.instance().quit()
            else:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Update fehlgeschlagen",
                    f"Installer konnte nicht gestartet werden.\nPfad: {target}",
                )
        finally:
            reply.deleteLater()

    def _show_changelog_dialog(self, changelog: str) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Changelog")
        dialog.setObjectName("background")
        dialog.setModal(True)
        dialog.setMinimumSize(520, 360)
        dialog.setStyleSheet(self._build_stylesheet(self._current_colors()))

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QtWidgets.QLabel("Changelog")
        header.setObjectName("cardTitle")
        layout.addWidget(header)

        text = QtWidgets.QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(changelog)
        text.setObjectName("card")
        layout.addWidget(text, 1)

        close_btn = QtWidgets.QPushButton("Schließen")
        close_btn.setObjectName("primaryButton")
        close_btn.clicked.connect(dialog.accept)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        dialog.exec()

    def _start_project_manager_onboarding(self, *, force: bool = False) -> None:
        if not hasattr(self, "shared_view") or not hasattr(self, "local_view"):
            return
        if not force and self.config.get("onboarding"):
            return
        if getattr(self, "_onboarding_overlay", None) is not None:
            try:
                self._onboarding_overlay.hide()
                self._onboarding_overlay.deleteLater()
            except Exception:
                pass
            self._onboarding_overlay = None

        try:
            self.nav_list.setCurrentRow(1)
        except Exception:
            pass

        steps: list[CoachMarkStep] = [
            CoachMarkStep(
                target=self.nav_container,
                title="Navigation",
                body="Hier wechselst du zwischen den Tools. Die Leiste expandiert beim Hover.",
            ),
            CoachMarkStep(
                target=self.options_btn,
                title="Optionen",
                body="Unter „Optionen“ findest du Settings und About.",
            ),
            CoachMarkStep(
                target=self.help_btn,
                title="Hilfe",
                body="Hier kannst du das Onboarding jederzeit erneut starten.",
            ),
            CoachMarkStep(
                target=self.shared_view.search_edit,
                title="Suche",
                body="Filtere Projekte in Shared oder Local mit den jeweiligen Suchfeldern.",
            ),
            CoachMarkStep(
                target=self.shared_view,
                title="Shared",
                body="Hier siehst du alle Projekte im Shared Ordner (NAS). Mit „Ausleihen“ kopierst du ein Projekt nach Local.",
            ),
            CoachMarkStep(
                target=self.local_view,
                title="Local",
                body="Hier liegen deine lokalen Kopien. Mit „Zurueckgeben“ wird das Projekt wieder ins Shared übertragen und im Shared als frei markiert. Von der aktuellen Projektversion in Shared wird ein Backup erstellt und bis zu 5 Backups gehalten.",
            ),
        ]

        overlay = CoachMarkOverlay(self, steps)
        overlay.finished.connect(self._on_project_manager_onboarding_finished)
        self._onboarding_overlay = overlay
        overlay.start()

    def _on_project_manager_onboarding_finished(self) -> None:
        self._onboarding_overlay = None
        self.config["onboarding"] = True
        save_config(self.config)

    def _on_nav_changed(self, index: int) -> None:
        if index < 0 or not hasattr(self, "stack"):
            return
        self.stack.setCurrentIndex(index)

    def _on_editor_dirty_changed(self, dirty: bool) -> None:
        if hasattr(self, "save_component_btn"):
            self.save_component_btn.setVisible(dirty)

    def _on_component_loaded(self, name: str) -> None:
        if hasattr(self, "component_name_label"):
            self.component_name_label.setText(name or "Komponente")
        if hasattr(self, "save_component_btn"):
            self.save_component_btn.setVisible(False)

    def _save_current_component(self) -> None:
        if not getattr(self.block_editor, "current_component_path", None):
            QtWidgets.QMessageBox.information(self, "Keine Komponente", "Es ist keine Komponente geöffnet.")
            return
        ok, error = self.block_editor.save_current_component()
        if not ok:
            QtWidgets.QMessageBox.critical(self, "Speichern fehlgeschlagen", error or "Unbekannter Fehler")
            return
        QtWidgets.QMessageBox.information(self, "Gespeichert", "Komponente gespeichert.")

    def _expand_nav(self) -> None:
        if not getattr(self, "_nav_hover_enabled", True) or getattr(self, "_nav_ignore_enter", False):
            return
        if self._nav_close_timer:
            self._nav_close_timer.stop()
        if self._nav_expanded:
            return
        self._nav_expanded = True

        for i in range(self.nav_list.count()):
            item = self.nav_list.item(i)
            label = item.data(QtCore.Qt.UserRole + 2) or ""
            item.setText(label)

        overlay = self._ensure_nav_overlay()
        if self.nav_list.parent() is not overlay:
            self.nav_list.setParent(overlay)
            self._nav_overlay_layout.addWidget(self.nav_list)  # type: ignore[union-attr]
        overlay.show()
        overlay.raise_()
        self._animate_nav_overlay(start_width=48, to_width=140)
        self._start_nav_hover_watch()

    def _collapse_nav(self) -> None:
        if not self._nav_expanded:
            self._clear_nav_text()
            return
        self._nav_expanded = False
        self._animate_nav_overlay(to_width=48, hide_on_finish=True)
        self._stop_nav_hover_watch()

    def _animate_nav(self, target: int, show_text: bool) -> None:
        if not hasattr(self, "nav_container"):
            return
        if self._nav_anim:
            self._nav_anim.stop()
        start = self.nav_container.width()
        animator = WidthAnimator(self.nav_container, self)
        anim = QtCore.QPropertyAnimation(animator, b"width", self)
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setDuration(180)
        anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        if show_text:
            for i in range(self.nav_list.count()):
                item = self.nav_list.item(i)
                label = item.data(QtCore.Qt.UserRole + 2) or ""
                item.setText(label)
        else:
            anim.finished.connect(self._clear_nav_text)

        anim.start()
        self._nav_anim = anim

    def _clear_nav_text(self) -> None:
        for i in range(self.nav_list.count()):
            self.nav_list.item(i).setText("")

    def _build_nav_icon(self, path: Path) -> QtGui.QIcon:
        # Light theme: tint icons to black for contrast on light backgrounds.
        pix = QtGui.QPixmap(str(path))
        if pix.isNull() or self.theme != "light":
            return QtGui.QIcon(pix) if not pix.isNull() else QtGui.QIcon(str(path))

        dpr = pix.devicePixelRatioF()

        def tint(color: str) -> QtGui.QPixmap:
            tinted = QtGui.QPixmap(pix.size())
            tinted.setDevicePixelRatio(dpr)
            tinted.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(tinted)
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
            painter.drawPixmap(0, 0, pix)
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
            painter.fillRect(tinted.rect(), QtGui.QColor(color))
            painter.end()
            return tinted

        normal = tint("#111111")
        disabled = tint("#6b7280")
        icon = QtGui.QIcon()
        for mode in (QtGui.QIcon.Normal, QtGui.QIcon.Active, QtGui.QIcon.Selected):
            icon.addPixmap(normal, mode, QtGui.QIcon.Off)
            icon.addPixmap(normal, mode, QtGui.QIcon.On)
        icon.addPixmap(disabled, QtGui.QIcon.Disabled, QtGui.QIcon.Off)
        icon.addPixmap(disabled, QtGui.QIcon.Disabled, QtGui.QIcon.On)
        return icon

    def _refresh_nav_icons(self) -> None:
        if not hasattr(self, "nav_list"):
            return
        for i in range(self.nav_list.count()):
            item = self.nav_list.item(i)
            filename = item.data(QtCore.Qt.UserRole + 3)
            if not filename:
                continue
            icon_path = BASE_DIR / "assets" / str(filename)
            if icon_path.exists():
                item.setIcon(self._build_nav_icon(icon_path))

    def _add_block_if_component(self) -> None:
        if not getattr(self.block_editor, "current_component_path", None):
            QtWidgets.QMessageBox.information(self, "Keine Komponente", "Bitte erst eine Komponente öffnen.")
            return
        QtWidgets.QMessageBox.information(
            self,
            "Nur Basic-Elemente",
            "Komponenten bestehen nur aus Basic-Blocks. Ziehe sie aus dem Ordner 'basic' der Libraries in das Fenster.",
        )

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if obj == getattr(self, "options_btn", None):
            if event.type() == QtCore.QEvent.Enter:
                if not self.options_menu.isVisible():
                    # Use a single shot to ensure the menu pops after the hover event is processed.
                    QtCore.QTimer.singleShot(0, self._popup_options_menu)
            return False
        if obj == getattr(self, "options_menu", None):
            if event.type() in (QtCore.QEvent.Leave, QtCore.QEvent.HoverLeave):
                self._schedule_close_options_menu()
            elif event.type() in (QtCore.QEvent.Enter, QtCore.QEvent.HoverEnter):
                if self._options_menu_close_timer:
                    self._options_menu_close_timer.stop()
            return False
        if obj == getattr(self, "help_btn", None):
            if event.type() == QtCore.QEvent.Enter:
                if not self.help_menu.isVisible():
                    QtCore.QTimer.singleShot(0, self._popup_help_menu)
            return False
        if obj in (getattr(self, "help_menu", None), getattr(self, "onboarding_menu", None)):
            if event.type() in (QtCore.QEvent.Leave, QtCore.QEvent.HoverLeave):
                self._schedule_close_help_menu()
            elif event.type() in (QtCore.QEvent.Enter, QtCore.QEvent.HoverEnter):
                if self._help_menu_close_timer:
                    self._help_menu_close_timer.stop()
            return False
        if obj in (getattr(self, "nav_container", None), self.nav_list, getattr(self, "_nav_overlay", None)):
            if not getattr(self, "_nav_hover_enabled", True):
                return False
            if event.type() == QtCore.QEvent.Enter:
                self._expand_nav()
            elif event.type() in (QtCore.QEvent.Leave, QtCore.QEvent.HoverLeave):
                self._nav_ignore_enter = False
                self._schedule_nav_collapse()
        return super().eventFilter(obj, event)

    def _ensure_nav_overlay(self) -> QtWidgets.QFrame:
        if self._nav_overlay is not None:
            return self._nav_overlay
        parent = self.centralWidget() or self
        overlay = QtWidgets.QFrame(parent)
        overlay.setObjectName("navOverlay")
        overlay.setMouseTracking(True)
        overlay.installEventFilter(self)
        overlay.hide()

        layout = QtWidgets.QVBoxLayout(overlay)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._nav_overlay = overlay
        self._nav_overlay_layout = layout
        return overlay

    def _update_nav_overlay_geometry(self) -> None:
        overlay = getattr(self, "_nav_overlay", None)
        if overlay is None or not overlay.isVisible():
            return
        central = self.centralWidget()
        if not central:
            return
        top = self.title_bar.height() if hasattr(self, "title_bar") else 0
        bottom = self.bottom_bar.height() if hasattr(self, "bottom_bar") else 0
        height = max(0, central.height() - top - bottom)
        width = overlay.width() or 140
        overlay.setGeometry(0, top, width, height)

    def _animate_nav_overlay(
        self, *, to_width: int, hide_on_finish: bool = False, start_width: int | None = None
    ) -> None:
        overlay = self._ensure_nav_overlay()
        central = self.centralWidget()
        if not central:
            return
        top = self.title_bar.height() if hasattr(self, "title_bar") else 0
        bottom = self.bottom_bar.height() if hasattr(self, "bottom_bar") else 0
        height = max(0, central.height() - top - bottom)

        if self._nav_overlay_anim:
            self._nav_overlay_anim.stop()

        start_width = int(start_width if start_width is not None else (overlay.width() if overlay.isVisible() else 48))
        overlay.setGeometry(0, top, start_width, height)

        anim = QtCore.QPropertyAnimation(overlay, b"geometry", self)
        anim.setStartValue(QtCore.QRect(0, top, start_width, height))
        anim.setEndValue(QtCore.QRect(0, top, to_width, height))
        anim.setDuration(180)
        anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        def finish() -> None:
            if hide_on_finish and self._nav_overlay:
                self._nav_overlay.hide()
                if self.nav_list.parent() is self._nav_overlay:
                    self.nav_list.setParent(self.nav_container)
                    self._nav_dock_layout.addWidget(self.nav_list)
            if hide_on_finish:
                self._clear_nav_text()

        if hide_on_finish:
            anim.finished.connect(finish)
        self._nav_overlay_anim = anim
        anim.start()

    def _schedule_nav_collapse(self) -> None:
        if self._nav_close_timer is None:
            self._nav_close_timer = QtCore.QTimer(self)
            self._nav_close_timer.setSingleShot(True)
            self._nav_close_timer.timeout.connect(self._collapse_nav_if_not_hovered)
        self._nav_close_timer.start(120)

    def _collapse_nav_if_not_hovered(self) -> None:
        if not self._nav_expanded:
            return

        def cursor_over(widget: QtWidgets.QWidget | None) -> bool:
            if widget is None or not widget.isVisible():
                return False
            pos = widget.mapFromGlobal(QtGui.QCursor.pos())
            return widget.rect().contains(pos)

        if cursor_over(self._nav_overlay) or cursor_over(self.nav_container):
            return
        self._collapse_nav()

    def _start_nav_hover_watch(self) -> None:
        if self._nav_hover_watch_timer is None:
            timer = QtCore.QTimer(self)
            timer.setInterval(120)
            timer.timeout.connect(self._collapse_nav_if_not_hovered)
            self._nav_hover_watch_timer = timer
        if not self._nav_hover_watch_timer.isActive():
            self._nav_hover_watch_timer.start()

    def _stop_nav_hover_watch(self) -> None:
        if self._nav_hover_watch_timer and self._nav_hover_watch_timer.isActive():
            self._nav_hover_watch_timer.stop()

    def _popup_options_menu(self) -> None:
        if not hasattr(self, "options_btn") or not hasattr(self, "options_menu"):
            return
        if self._options_menu_close_timer:
            self._options_menu_close_timer.stop()
        self._hide_help_menus()
        pos = self.options_btn.mapToGlobal(QtCore.QPoint(0, self.options_btn.height()))
        self.options_menu.popup(pos)
        self._start_options_menu_watch()

    def _schedule_close_options_menu(self) -> None:
        if not hasattr(self, "options_menu"):
            return
        if self._options_menu_close_timer is None:
            self._options_menu_close_timer = QtCore.QTimer(self)
            self._options_menu_close_timer.setSingleShot(True)
            self._options_menu_close_timer.timeout.connect(self._close_options_menu_if_not_hovered)
        self._options_menu_close_timer.start(320)

    def _start_options_menu_watch(self) -> None:
        if self._options_menu_watch_timer is None:
            timer = QtCore.QTimer(self)
            timer.setInterval(150)
            timer.timeout.connect(self._close_options_menu_if_not_hovered)
            self._options_menu_watch_timer = timer
        if not self._options_menu_watch_timer.isActive():
            self._options_menu_watch_timer.start()

    def _stop_options_menu_watch(self) -> None:
        if self._options_menu_watch_timer and self._options_menu_watch_timer.isActive():
            self._options_menu_watch_timer.stop()

    def _close_options_menu_if_not_hovered(self) -> None:
        if not hasattr(self, "options_menu") or not hasattr(self, "options_btn"):
            return
        if not self.options_menu.isVisible():
            self._stop_options_menu_watch()
            return

        def cursor_over(widget: QtWidgets.QWidget | None) -> bool:
            if widget is None or not widget.isVisible():
                return False
            pos = widget.mapFromGlobal(QtGui.QCursor.pos())
            return widget.rect().contains(pos)

        if cursor_over(self.options_btn) or cursor_over(self.options_menu):
            return
        self.options_menu.hide()

    def _popup_help_menu(self) -> None:
        if not hasattr(self, "help_btn") or not hasattr(self, "help_menu"):
            return
        if self._help_menu_close_timer:
            self._help_menu_close_timer.stop()
        self._hide_options_menu()
        pos = self.help_btn.mapToGlobal(QtCore.QPoint(0, self.help_btn.height()))
        self.help_menu.popup(pos)
        self._start_help_menu_watch()

    def _position_onboarding_submenu(self) -> None:
        if not hasattr(self, "help_menu") or not hasattr(self, "onboarding_menu") or not hasattr(self, "_onboarding_action"):
            return
        if not self.help_menu.isVisible():
            return
        try:
            rect = self.help_menu.actionGeometry(self._onboarding_action)
            pos = self.help_menu.mapToGlobal(rect.topRight()) + QtCore.QPoint(10, -2)
            QtCore.QTimer.singleShot(0, lambda: self.onboarding_menu.move(pos))
        except Exception:
            return

    def _schedule_close_help_menu(self) -> None:
        if not hasattr(self, "help_menu"):
            return
        if self._help_menu_close_timer is None:
            self._help_menu_close_timer = QtCore.QTimer(self)
            self._help_menu_close_timer.setSingleShot(True)
            self._help_menu_close_timer.timeout.connect(self._close_help_menu_if_not_hovered)
        self._help_menu_close_timer.start(320)

    def _start_help_menu_watch(self) -> None:
        if self._help_menu_watch_timer is None:
            timer = QtCore.QTimer(self)
            timer.setInterval(150)
            timer.timeout.connect(self._close_help_menu_if_not_hovered)
            self._help_menu_watch_timer = timer
        if not self._help_menu_watch_timer.isActive():
            self._help_menu_watch_timer.start()

    def _stop_help_menu_watch(self) -> None:
        if self._help_menu_watch_timer and self._help_menu_watch_timer.isActive():
            self._help_menu_watch_timer.stop()

    def _close_help_menu_if_not_hovered(self) -> None:
        if not hasattr(self, "help_menu") or not hasattr(self, "help_btn") or not hasattr(self, "onboarding_menu"):
            return
        if not self.help_menu.isVisible() and not self.onboarding_menu.isVisible():
            self._stop_help_menu_watch()
            return

        def cursor_over(widget: QtWidgets.QWidget | None) -> bool:
            if widget is None or not widget.isVisible():
                return False
            pos = widget.mapFromGlobal(QtGui.QCursor.pos())
            return widget.rect().contains(pos)

        if cursor_over(self.help_btn) or cursor_over(self.help_menu) or cursor_over(self.onboarding_menu):
            return
        self.help_menu.hide()

    def _hide_options_menu(self) -> None:
        if hasattr(self, "options_menu") and self.options_menu.isVisible():
            if self._options_menu_close_timer:
                self._options_menu_close_timer.stop()
            self.options_menu.hide()
        self._stop_options_menu_watch()

    def _hide_help_menus(self) -> None:
        if hasattr(self, "help_menu") and self.help_menu.isVisible():
            if self._help_menu_close_timer:
                self._help_menu_close_timer.stop()
            self.help_menu.hide()
        if hasattr(self, "onboarding_menu") and self.onboarding_menu.isVisible():
            self.onboarding_menu.hide()
        self._stop_help_menu_watch()

    def _add_basic_block_from_item(self, item: QtWidgets.QTreeWidgetItem) -> None:
        path_data = item.data(0, QtCore.Qt.UserRole)
        if not path_data:
            return
        path_obj = Path(str(path_data))
        if not path_obj.exists() or path_obj.is_dir():
            return
        if not self.block_editor.current_component_path:
            QtWidgets.QMessageBox.information(self, "Keine Komponente", "Bitte erst eine Komponente öffnen.")
            return
        try:
            with path_obj.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        if not (data.get("kind") == "basic" or data.get("basic") is True or self._is_basic_item(item, path_obj)):
            QtWidgets.QMessageBox.information(self, "Nur Basic-Block", "Dieses Element ist keine Basic-Definition.")
            return
        self.block_editor.add_basic_block(data, path_obj.stem)

    def _load_component_from_item(self, item: QtWidgets.QTreeWidgetItem) -> None:
        path_data = item.data(0, QtCore.Qt.UserRole)
        if not path_data:
            return
        path_obj = Path(str(path_data))
        if not path_obj.exists() or path_obj.is_dir():
            QtWidgets.QMessageBox.warning(self, "Nicht gefunden", f"Pfad nicht gefunden: {path_obj}")
            return
        if self._is_basic_item(item, path_obj):
            QtWidgets.QMessageBox.information(self, "Basic-Element", "Basic-Elemente k\u00f6nnen nicht als Komponente geladen werden.")
            return
        if path_obj.suffix.lower() != ".json":
            QtWidgets.QMessageBox.information(self, "Format", "Nur JSON-Komponenten k\u00f6nnen geladen werden.")
            return
        loaded = self.block_editor.load_component(path_obj)
        if not loaded:
            QtWidgets.QMessageBox.warning(
                self, "Laden fehlgeschlagen", f"Komponente konnte nicht geladen werden:\n{path_obj}"
            )
        else:
            self.component_name_label.setText(path_obj.stem)

    def _normalize_path(self, value, fallback: Path) -> Path:
        if not value:
            return Path(fallback).resolve()
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = (BASE_DIR / path).resolve()
        return path

    def _load_library_paths(self) -> list[str]:
        libs = self.config.get("libraries")
        cleaned: list[str] = []
        if isinstance(libs, list):
            for entry in libs:
                if not isinstance(entry, str):
                    continue
                text = entry.strip()
                if text and text not in cleaned:
                    cleaned.append(text)
        default_lib = (BASE_DIR / "libraries").resolve()
        if not cleaned and default_lib.exists():
            cleaned.append(str(default_lib))
        return cleaned

    def _apply_config_paths(self) -> None:
        shared_cfg = self.config.get("shared_dir") or self.config.get("common_dir")
        self.shared_dir = self._normalize_path(shared_cfg, BASE_DIR / "shared")
        self.local_dir = self._normalize_path(self.config.get("local_dir"), BASE_DIR / "local")
        backup_cfg = self.config.get("backup_dir")
        self.backup_dir = self._normalize_path(backup_cfg, BASE_DIR / "backups") if backup_cfg is not None else None
        self.loans_file = self.shared_dir / "neuranel_data" / "loans.json"
        self.local_loans_file = self.local_dir / "neuranel_data" / "loans_local.json"

    def _load_local_loan_config(self) -> tuple[dict, dict]:
        default_data = {"borrowed_projects": {}}
        target = getattr(self, "local_loans_file", None)
        if target is None:
            return default_data, default_data["borrowed_projects"]
        path = target
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return default_data, default_data["borrowed_projects"]
        if not path.exists():
            try:
                target.write_text(json.dumps(default_data, indent=2, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
            return {"borrowed_projects": {}}, {}
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        borrowed = data.get("borrowed_projects")
        if not isinstance(borrowed, dict):
            borrowed = {}
            data["borrowed_projects"] = borrowed
        return data, borrowed

    def _write_local_loan_config(self, data: dict) -> None:
        path = getattr(self, "local_loans_file", None)
        if path is None:
            return
        tmp = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(data, indent=2, ensure_ascii=False)
            tmp = path.with_suffix(path.suffix + ".tmp")
            try:
                tmp.unlink()
            except OSError:
                pass
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            return
        finally:
            if tmp:
                try:
                    tmp.unlink()
                except OSError:
                    pass
    def _refresh_local_borrowed(self, local_projects: list[str] | None = None) -> None:
        data, borrowed = self._load_local_loan_config()
        if not isinstance(borrowed, dict):
            borrowed = {}
            data["borrowed_projects"] = {}
        if isinstance(local_projects, list):
            local_list = [p for p in local_projects if isinstance(p, str) and p.lower() != "neuranel_data"]
        else:
            local_list = [name for name in list_projects(self.local_dir) if name.lower() != "neuranel_data"]
        local_set = set(local_list)
        pruned = {name: info for name, info in borrowed.items() if name in local_set}
        if pruned != borrowed:
            data["borrowed_projects"] = pruned
            self._write_local_loan_config(data)
        self.local_borrowed = pruned

    def _update_local_borrow_record(self, name: str, timestamp: str, holder: str) -> None:
        data, borrowed = self._load_local_loan_config()
        if not isinstance(borrowed, dict):
            borrowed = {}
            data["borrowed_projects"] = borrowed
        borrowed[name] = {"holder": holder, "timestamp": timestamp}
        self._write_local_loan_config(data)
        self.local_borrowed = borrowed

    def _remove_local_borrow_record(self, name: str) -> None:
        data, borrowed = self._load_local_loan_config()
        if not isinstance(borrowed, dict):
            borrowed = {}
            data["borrowed_projects"] = borrowed
        if name in borrowed:
            del borrowed[name]
            self._write_local_loan_config(data)
        self.local_borrowed = borrowed

    def _ensure_config(self) -> None:
        if "libraries" not in self.config or not isinstance(self.config.get("libraries"), list):
            self.config["libraries"] = []
            save_config(self.config)
        if "backup_dir" not in self.config:
            self.config["backup_dir"] = ""
            save_config(self.config)
        if self.config.get("shared_dir") and self.config.get("local_dir"):
            return
        default_shared = ""
        default_local = ""
        default_language = self.config.get("language", "de")
        default_theme = self.config.get("theme", "dark")
        if default_theme not in DEFAULT_PRESETS:
            default_theme = "dark"
        default_backup = self.config.get("backup_dir", "")
        default_accent = (
            self.config.get("presets", {}).get(default_theme, {}).get("accent")
            or self.config.get("accent_color", DEFAULT_PRESETS.get(default_theme, DEFAULT_PRESETS["dark"])["accent"])
        )
        if self._startup_splash:
            self._startup_splash.close()
            self._startup_splash = None
        dlg = SetupDialog(default_language, default_shared, default_local, default_backup, default_theme, default_accent, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.config["shared_dir"] = dlg.shared_input.text().strip()
            self.config["local_dir"] = dlg.local_input.text().strip()
            self.config["backup_dir"] = dlg.backup_input.text().strip()
            self.config["language"] = getattr(dlg, "language_choice", default_language)
            theme_choice = "light" if dlg.light_radio.isChecked() else "dark"
            accent_choice = dlg.accent_input.text().strip() or default_accent
            color = QtGui.QColor(accent_choice)
            if color.isValid():
                accent_choice = color.name()
            else:
                accent_choice = default_accent
            self.config["theme"] = theme_choice
            self.config.setdefault("presets", {}).setdefault(theme_choice, {})["accent"] = accent_choice
            self.config["accent_color"] = accent_choice
            save_config(self.config)
        else:
            QtWidgets.QMessageBox.warning(self, "Abbruch", "Ohne initiale Konfiguration kann Neuranel nicht starten.")
            QtWidgets.QApplication.instance().quit()
            raise SystemExit("Ersteinrichtung abgebrochen")

    def _ensure_theme_defaults(self) -> None:
        changed = False
        presets = self.config.get("presets")
        if not isinstance(presets, dict):
            presets = {}
            changed = True
        for name, defaults in DEFAULT_PRESETS.items():
            base = presets.get(name, {})
            if not isinstance(base, dict):
                base = {}
            for key, value in defaults.items():
                if key not in base:
                    base[key] = value
                    changed = True
            presets[name] = base
        if "theme" not in self.config:
            self.config["theme"] = "dark"
            changed = True
        if "accent_color" not in self.config:
            self.config["accent_color"] = presets.get(self.config["theme"], {}).get("accent", DEFAULT_PRESETS["dark"]["accent"])
            changed = True
        if "accent_color2" not in self.config:
            self.config["accent_color2"] = presets.get(self.config["theme"], {}).get("accent2", DEFAULT_PRESETS["dark"]["accent2"])
            changed = True
        self.config["presets"] = presets
        if changed:
            save_config(self.config)

    def _build_projects_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = self._build_header()
        layout.addLayout(header)

        self.shared_view = ProjectCard("Shared", with_header=False)
        self.local_view = ProjectCard("Local", with_header=False)

        self.shared_view.search_edit.textChanged.connect(self._apply_shared_filter)
        self.local_view.search_edit.textChanged.connect(self._apply_local_filter)

        lists_layout = QtWidgets.QHBoxLayout()
        lists_layout.setSpacing(12)
        shared_column = QtWidgets.QVBoxLayout()
        shared_column.setContentsMargins(0, 0, 0, 0)
        shared_column.setSpacing(6)
        shared_header = QtWidgets.QHBoxLayout()
        shared_header.setSpacing(8)
        shared_title = QtWidgets.QLabel("Shared")
        shared_title.setObjectName("cardTitle")
        shared_header.addWidget(shared_title)
        shared_header.addStretch(1)
        shared_header.addWidget(self.shared_view.search_edit)
        shared_column.addLayout(shared_header)
        shared_column.addWidget(self.shared_view)

        local_column = QtWidgets.QVBoxLayout()
        local_column.setContentsMargins(0, 0, 0, 0)
        local_column.setSpacing(6)
        local_header = QtWidgets.QHBoxLayout()
        local_header.setSpacing(8)
        local_title = QtWidgets.QLabel("Local")
        local_title.setObjectName("cardTitle")
        local_header.addWidget(local_title)
        local_header.addStretch(1)
        local_header.addWidget(self.local_view.search_edit)
        local_column.addLayout(local_header)
        local_column.addWidget(self.local_view)

        lists_layout.addLayout(shared_column)
        lists_layout.addLayout(local_column)
        layout.addLayout(lists_layout, 1)

        return tab

    def _build_title_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        title = QtWidgets.QLabel("Title")
        title.setObjectName("heroTitle")
        subtitle = QtWidgets.QLabel("Schneller Zugriff auf alle Funktionen.")
        subtitle.setObjectName("holderLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(title, 0, QtCore.Qt.AlignTop)
        layout.addWidget(subtitle, 0, QtCore.Qt.AlignTop)
        local_card = QtWidgets.QFrame()
        local_card.setObjectName("card")
        card_layout = QtWidgets.QVBoxLayout(local_card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(8)
        card_title = QtWidgets.QLabel("Local Projekte")
        card_title.setObjectName("cardTitle")
        card_layout.addWidget(card_title)
        self.title_local_list = QtWidgets.QListWidget()
        self.title_local_list.setObjectName("projectList")
        self.title_local_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.title_local_list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        card_layout.addWidget(self.title_local_list, 1)
        layout.addWidget(local_card, 1)
        layout.addStretch(2)
        return tab

    def _build_block_editor_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)
        title = QtWidgets.QLabel("Funktionsbl\u00f6cke")
        title.setObjectName("heroTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.component_name_label = QtWidgets.QLabel("Keine Komponente geladen")
        self.component_name_label.setObjectName("holderLabel")
        header.addWidget(self.component_name_label)
        self.save_component_btn = QtWidgets.QPushButton("Speichern")
        self.save_component_btn.setObjectName("actionButton")
        self.save_component_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.save_component_btn.setVisible(False)
        self.save_component_btn.clicked.connect(self._save_current_component)
        header.addWidget(self.save_component_btn)
        layout.addLayout(header)

        hint = QtWidgets.QLabel(
            "F\u00fcge Bl\u00f6cke hinzu und verbinde die IO-Kreise: zuerst Output klicken, dann Input."
        )
        hint.setObjectName("holderLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        splitter = QtWidgets.QSplitter()
        splitter.setObjectName("blockSplitter")
        splitter.setHandleWidth(6)

        library_panel = QtWidgets.QFrame()
        library_panel.setObjectName("libraryPanel")
        library_layout = QtWidgets.QVBoxLayout(library_panel)
        library_layout.setContentsMargins(8, 8, 8, 8)
        library_layout.setSpacing(6)

        library_header = QtWidgets.QHBoxLayout()
        library_header.setSpacing(6)
        library_title = QtWidgets.QLabel("Libraries")
        library_title.setObjectName("cardTitle")
        library_header.addWidget(library_title)
        library_header.addStretch(1)
        refresh_btn = QtWidgets.QToolButton()
        refresh_btn.setText("Neu laden")
        refresh_btn.setCursor(QtCore.Qt.PointingHandCursor)
        refresh_btn.setObjectName("settingsButton")
        refresh_btn.clicked.connect(self._refresh_library_tree)
        library_header.addWidget(refresh_btn)
        library_layout.addLayout(library_header)

        self.library_tree = LibraryTree()
        self.library_tree.setObjectName("libraryTree")
        self.library_tree.setHeaderHidden(True)
        self.library_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.library_tree.customContextMenuRequested.connect(self._on_library_context_menu)
        self.library_tree.setDragEnabled(True)
        self.library_tree.setDefaultDropAction(QtCore.Qt.CopyAction)
        self.library_tree.setIndentation(12)
        library_layout.addWidget(self.library_tree, 1)

        splitter.addWidget(library_panel)

        editor_container = QtWidgets.QFrame()
        editor_container.setObjectName("blockEditorContainer")
        editor_layout = QtWidgets.QVBoxLayout(editor_container)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)

        palette_bar = QtWidgets.QFrame()
        palette_bar.setObjectName("blockPaletteBar")
        palette_layout = QtWidgets.QHBoxLayout(palette_bar)
        palette_layout.setContentsMargins(12, 8, 12, 8)
        palette_layout.setSpacing(8)
        palette_label = QtWidgets.QLabel("Element einf\u00fcgen:")
        palette_label.setObjectName("itemName")
        palette_layout.addWidget(palette_label)

        def add_named_block(name: str) -> None:
            if not self.block_editor.add_connector_to_selected("input" if name == "Eingang" else "output"):
                QtWidgets.QMessageBox.information(
                    self,
                    "Kein Block ausgew\u00e4hlt",
                    "Waehle zuerst einen Block im Editor aus, um Anschluesse hinzuzufuegen.",
                )

        for block_name in ("Eingang", "Ausgang"):
            btn = PaletteDragButton(block_name, "input" if block_name == "Eingang" else "output")
            btn.setObjectName("secondaryButton")
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, n=block_name: add_named_block(n))
            palette_layout.addWidget(btn)

        self.line_btn = QtWidgets.QPushButton("Line")
        self.line_btn.setCheckable(True)
        self.line_btn.setObjectName("secondaryButton")
        self.line_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.line_btn.toggled.connect(lambda checked: self.block_editor.toggle_line_mode(checked))
        palette_layout.addWidget(self.line_btn)

        palette_layout.addStretch(1)
        editor_layout.addWidget(palette_bar)

        self.block_editor = NodeEditorWidget(self.accent_color, self.accent_color2, self)
        self.block_editor.dirty_changed.connect(self._on_editor_dirty_changed)
        self.block_editor.component_loaded.connect(self._on_component_loaded)
        self.block_editor.set_line_button(self.line_btn)
        editor_layout.addWidget(self.block_editor, 1)

        splitter.addWidget(editor_container)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 760])

        layout.addWidget(splitter, 1)

        add_btn = QtWidgets.QPushButton("Block hinzuf\u00fcgen")
        add_btn.setObjectName("primaryButton")
        add_btn.setCursor(QtCore.Qt.PointingHandCursor)
        add_btn.clicked.connect(lambda: self._add_block_if_component())
        header.addWidget(add_btn)
        self._refresh_library_tree()

        return tab

    def _build_placeholder_tab(self, text: str) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        label = QtWidgets.QLabel(text)
        label.setObjectName("cardTitle")
        layout.addWidget(label, 0, QtCore.Qt.AlignTop)
        layout.addStretch(1)
        return tab

    def _open_settings_dialog(self) -> None:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Settings")
        dlg.setMinimumSize(720, 480)
        dlg.setObjectName("background")

        root_layout = QtWidgets.QVBoxLayout(dlg)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        content_layout = QtWidgets.QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        nav_container = QtWidgets.QFrame()
        nav_container.setObjectName("navContainer")
        nav_container.setFixedWidth(200)
        nav_layout = QtWidgets.QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        nav_list = QtWidgets.QListWidget()
        nav_list.setObjectName("navList")
        nav_list.addItem("Pfade")
        nav_list.addItem("Design")
        nav_list.addItem("Libraries")
        nav_list.setCurrentRow(0)
        nav_layout.addWidget(nav_list)

        separator = QtWidgets.QFrame()
        separator.setObjectName("navSeparator")
        separator.setFixedWidth(1)

        stack = QtWidgets.QStackedWidget()

        # Pfade-Tab
        paths_page = QtWidgets.QWidget()
        paths_layout = QtWidgets.QVBoxLayout(paths_page)
        paths_layout.setContentsMargins(16, 16, 16, 16)
        paths_layout.setSpacing(12)

        info = QtWidgets.QLabel(
            "Passe die Pfade fuer shared und local an. Aenderungen werden gespeichert und direkt angewendet."
        )
        info.setWordWrap(True)
        info.setObjectName("holderLabel")
        paths_layout.addWidget(info)

        shared_input = QtWidgets.QLineEdit(str(self.shared_dir))
        shared_input.setObjectName("settingsField")
        local_input = QtWidgets.QLineEdit(str(self.local_dir))
        local_input.setObjectName("settingsField")
        backup_input = QtWidgets.QLineEdit(str(self.backup_dir) if self.backup_dir else "")
        backup_input.setObjectName("settingsField")

        def browse_shared() -> None:
            path = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Shared Ordner waehlen", shared_input.text() or str(self.shared_dir)
            )
            if path:
                shared_input.setText(path)

        def browse_local() -> None:
            path = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Local Ordner waehlen", local_input.text() or str(self.local_dir)
            )
            if path:
                local_input.setText(path)

        def browse_backup() -> None:
            start = backup_input.text() or shared_input.text() or str(BASE_DIR)
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Backup Ordner waehlen", start)
            if path:
                backup_input.setText(path)

        paths_layout.addLayout(self._path_row("Shared Pfad", shared_input, browse_shared))
        paths_layout.addLayout(self._path_row("Local Pfad", local_input, browse_local))
        paths_layout.addLayout(self._path_row("Backup Pfad", backup_input, browse_backup))
        paths_layout.addStretch(1)
        stack.addWidget(paths_page)

        # Design-Tab
        design_page = QtWidgets.QWidget()
        design_layout = QtWidgets.QVBoxLayout(design_page)
        design_layout.setContentsMargins(16, 16, 16, 16)
        design_layout.setSpacing(12)

        design_info = QtWidgets.QLabel("Passe die Design-Akzente an. Aenderungen wirken sofort nach dem Speichern.")
        design_info.setWordWrap(True)
        design_info.setObjectName("holderLabel")
        design_layout.addWidget(design_info)

        theme_row = QtWidgets.QHBoxLayout()
        theme_row.setSpacing(8)
        theme_label = QtWidgets.QLabel("Modus")
        theme_label.setObjectName("itemName")
        theme_row.addWidget(theme_label)
        theme_group = QtWidgets.QButtonGroup(design_page)
        dark_radio = QtWidgets.QRadioButton("Dark Mode")
        light_radio = QtWidgets.QRadioButton("Light Mode")
        theme_group.addButton(dark_radio)
        theme_group.addButton(light_radio)
        current_theme = self.config.get("theme", "dark")
        if current_theme == "light":
            light_radio.setChecked(True)
        else:
            dark_radio.setChecked(True)
        theme_row.addWidget(dark_radio)
        theme_row.addWidget(light_radio)
        theme_row.addStretch(1)
        design_layout.addLayout(theme_row)

        accent_row = QtWidgets.QHBoxLayout()
        accent_row.setSpacing(8)
        accent_label = QtWidgets.QLabel("Akzentfarbe")
        accent_label.setObjectName("itemName")
        accent_input = QtWidgets.QLineEdit(self.accent_color or "#007acc")
        accent_input.setObjectName("settingsField")
        accent_input.setPlaceholderText("#rrggbb")
        accent_picker = QtWidgets.QPushButton("Farbe...")
        accent_picker.setObjectName("actionButton")
        accent_picker.setCursor(QtCore.Qt.PointingHandCursor)

        def pick_accent() -> None:
            color = QtWidgets.QColorDialog.getColor(QtGui.QColor(accent_input.text() or self.accent_color), self)
            if color.isValid():
                accent_input.setText(color.name())

        accent_picker.clicked.connect(pick_accent)

        def load_preset(theme_name: str) -> None:
            preset = self.config.get("presets", {}).get(theme_name, {})
            if isinstance(preset, dict):
                accent_input.setText(preset.get("accent", accent_input.text()))

        dark_radio.toggled.connect(lambda checked: load_preset("dark") if checked else None)
        light_radio.toggled.connect(lambda checked: load_preset("light") if checked else None)
        accent_row.addWidget(accent_label)
        accent_row.addWidget(accent_input, 1)
        accent_row.addWidget(accent_picker)
        design_layout.addLayout(accent_row)
        design_layout.addStretch(1)
        stack.addWidget(design_page)

        # Libraries-Tab
        libraries_page = QtWidgets.QWidget()
        libraries_layout = QtWidgets.QVBoxLayout(libraries_page)
        libraries_layout.setContentsMargins(16, 16, 16, 16)
        libraries_layout.setSpacing(12)

        libraries_info = QtWidgets.QLabel("Verwalte die Library-Pfade, aus denen Blocks geladen werden.")
        libraries_info.setObjectName("holderLabel")
        libraries_info.setWordWrap(True)
        libraries_layout.addWidget(libraries_info)

        libraries_list = QtWidgets.QListWidget()
        libraries_list.setObjectName("libraryList")
        libraries_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        libraries_list.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.SelectedClicked
        )
        for path in self.library_paths:
            libraries_list.addItem(path)
        libraries_layout.addWidget(libraries_list, 1)

        lib_buttons = QtWidgets.QHBoxLayout()
        lib_buttons.setSpacing(8)

        def add_library_path() -> None:
            start_dir = self.library_paths[0] if self.library_paths else str(BASE_DIR)
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Library-Ordner waehlen", start_dir)
            if path:
                items = [libraries_list.item(i).text() for i in range(libraries_list.count())]
                if path not in items:
                    libraries_list.addItem(path)

        def remove_library_path() -> None:
            row = libraries_list.currentRow()
            if row >= 0:
                libraries_list.takeItem(row)

        add_lib_btn = QtWidgets.QPushButton("Pfad hinzufuegen")
        add_lib_btn.setObjectName("actionButton")
        add_lib_btn.setCursor(QtCore.Qt.PointingHandCursor)
        add_lib_btn.clicked.connect(add_library_path)

        remove_lib_btn = QtWidgets.QPushButton("Entfernen")
        remove_lib_btn.setObjectName("dangerButton")
        remove_lib_btn.setCursor(QtCore.Qt.PointingHandCursor)
        remove_lib_btn.clicked.connect(remove_library_path)

        lib_buttons.addWidget(add_lib_btn)
        lib_buttons.addWidget(remove_lib_btn)
        lib_buttons.addStretch(1)
        libraries_layout.addLayout(lib_buttons)
        stack.addWidget(libraries_page)

        nav_list.currentRowChanged.connect(stack.setCurrentIndex)

        content_layout.addWidget(nav_container)
        content_layout.addWidget(separator)
        content_layout.addWidget(stack, 1)
        root_layout.addLayout(content_layout, 1)

        divider = QtWidgets.QFrame()
        divider.setFrameShape(QtWidgets.QFrame.HLine)
        divider.setFrameShadow(QtWidgets.QFrame.Plain)
        divider.setFixedHeight(1)
        divider.setStyleSheet("border: none;")
        root_layout.addWidget(divider)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(16, 12, 16, 12)
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        cancel_btn = QtWidgets.QPushButton("Abbrechen")
        cancel_btn.setObjectName("actionButton")
        cancel_btn.setCursor(QtCore.Qt.PointingHandCursor)
        cancel_btn.clicked.connect(dlg.reject)
        save_btn = QtWidgets.QPushButton("Speichern und neu laden")
        save_btn.setObjectName("primaryButton")
        save_btn.setCursor(QtCore.Qt.PointingHandCursor)
        save_btn.clicked.connect(
            lambda: self._apply_settings(
                shared_input.text().strip(),
                local_input.text().strip(),
                backup_input.text().strip(),
                dlg,
                accent_input.text().strip(),
                "light" if light_radio.isChecked() else "dark",
                [
                    libraries_list.item(i).text().strip()
                    for i in range(libraries_list.count())
                    if libraries_list.item(i).text().strip()
                ],
            )
        )
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root_layout.addLayout(btn_row)

        def apply_dialog_theme() -> None:
            theme_name = "light" if light_radio.isChecked() else "dark"
            dialog_colors = self._current_colors(theme_override=theme_name)
            dlg.setStyleSheet(self._build_stylesheet(dialog_colors))
            divider.setStyleSheet(f"background: {dialog_colors['border']}; border: none;")

        dark_radio.toggled.connect(lambda checked: apply_dialog_theme() if checked else None)
        light_radio.toggled.connect(lambda checked: apply_dialog_theme() if checked else None)
        apply_dialog_theme()

        dlg.exec()

    def _path_row(self, label_text: str, line_edit: QtWidgets.QLineEdit, handler) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        label = QtWidgets.QLabel(label_text)
        label.setObjectName("itemName")
        browse = QtWidgets.QPushButton("...")
        browse.setObjectName("actionButton")
        browse.setFixedWidth(40)
        browse.clicked.connect(handler)
        row.addWidget(label)
        row.addWidget(line_edit, 1)
        row.addWidget(browse)
        return row

    def _show_about_dialog(self) -> None:
        qt_version = getattr(QtCore, "QT_VERSION_STR", None) or QtCore.qVersion()

        class AboutDialog(QtWidgets.QDialog):
            def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
                super().__init__(parent)
                self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.Dialog)
                self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
                self._drag_pos: QtCore.QPoint | None = None

            def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
                if event.button() == QtCore.Qt.LeftButton:
                    self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    event.accept()
                    return
                super().mousePressEvent(event)

            def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
                if event.buttons() & QtCore.Qt.LeftButton and self._drag_pos is not None:
                    self.move(event.globalPosition().toPoint() - self._drag_pos)
                    event.accept()
                    return
                super().mouseMoveEvent(event)

            def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
                self._drag_pos = None
                super().mouseReleaseEvent(event)

        dlg = AboutDialog(self)
        dlg.setObjectName("aboutDialog")
        dlg.setFixedSize(420, 240)
        dlg.setStyleSheet(self._build_stylesheet(self._current_colors()))

        outer = QtWidgets.QVBoxLayout(dlg)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)

        shell = QtWidgets.QFrame()
        shell.setObjectName("aboutShell")
        shell_layout = QtWidgets.QVBoxLayout(shell)
        shell_layout.setContentsMargins(16, 14, 16, 14)
        shell_layout.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)
        header_title = QtWidgets.QLabel("About Neuranel")
        header_title.setObjectName("cardTitle")
        header.addWidget(header_title)
        header.addStretch(1)
        close_icon = QtWidgets.QToolButton()
        close_icon.setText("×")
        close_icon.setObjectName("aboutCloseButton")
        close_icon.setCursor(QtCore.Qt.PointingHandCursor)
        close_icon.clicked.connect(dlg.reject)
        header.addWidget(close_icon)
        shell_layout.addLayout(header)

        version_label = QtWidgets.QLabel(f"Suite Version: {self._suite_version}")
        version_label.setObjectName("holderLabel")
        shell_layout.addWidget(version_label)

        info_text = QtWidgets.QLabel(
            f"Benutzer: {getuser()}\nProject Manager: {self._pm_version}\nQt: {qt_version}\nSupport: e.seidner@duschek-haustechnik.at"
        )
        info_text.setObjectName("aboutInfo")
        info_text.setWordWrap(True)
        shell_layout.addWidget(info_text, 1)

        close_btn = QtWidgets.QPushButton("Schließen")
        close_btn.setObjectName("actionButton")
        close_btn.setCursor(QtCore.Qt.PointingHandCursor)
        close_btn.clicked.connect(dlg.accept)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        shell_layout.addLayout(btn_row)

        outer.addWidget(shell, 1)

        dlg.exec()

    def _show_timed_info(self, title: str, message: str, *, timeout_ms: int = 2000) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.setWindowTitle(title)
        box.setText(message)
        box.setStandardButtons(QtWidgets.QMessageBox.NoButton)
        box.setWindowModality(QtCore.Qt.NonModal)
        box.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        box.setStyleSheet(self._build_stylesheet(self._current_colors()))
        box.open()
        QtCore.QTimer.singleShot(timeout_ms, box.accept)

    def _apply_settings(
        self,
        shared_value: str,
        local_value: str,
        backup_value: str,
        dialog: QtWidgets.QDialog | None = None,
        accent_value: str | None = None,
        theme_value: str | None = None,
        library_paths: list[str] | None = None,
    ) -> None:
        new_common = self._normalize_path(shared_value, self.shared_dir)
        new_local = self._normalize_path(local_value, self.local_dir)
        new_backup = self._normalize_path(backup_value, self.backup_dir or BASE_DIR / "backups")
        self.shared_dir = new_common
        self.local_dir = new_local
        self.backup_dir = new_backup
        self.loans_file = self.shared_dir / "neuranel_data" / "loans.json"
        self.local_loans_file = self.local_dir / "neuranel_data" / "loans_local.json"
        self.config["shared_dir"] = str(self.shared_dir)
        self.config["local_dir"] = str(self.local_dir)
        self.config["backup_dir"] = str(self.backup_dir) if self.backup_dir else ""
        if library_paths is not None:
            self._set_library_paths(library_paths)
        else:
            self.config["libraries"] = self.library_paths
        if theme_value:
            self.config["theme"] = theme_value
            self.theme = theme_value
            self.accent_color = self._current_colors().get("accent", self.accent_color)
            self.accent_color2 = self._current_colors().get("accent2", self.accent_color2)
        if accent_value:
            color = QtGui.QColor(accent_value)
            if color.isValid():
                self.accent_color = color.name()
                self.config.setdefault("presets", {}).setdefault(self.theme, {})["accent"] = self.accent_color
                self.config["accent_color"] = self.accent_color
        else:
            self.config["accent_color"] = self.accent_color
        self._apply_styles()
        save_config(self.config)
        self.refresh_lists()
        if dialog:
            dialog.accept()
        self._nav_ignore_enter = True
        self._collapse_nav()
        self._show_timed_info("Gespeichert", "Einstellungen gespeichert.", timeout_ms=2000)

    def _set_library_paths(self, paths: list[str]) -> None:
        cleaned: list[str] = []
        for entry in paths:
            if not isinstance(entry, str):
                continue
            value = entry.strip()
            if value and value not in cleaned:
                cleaned.append(value)
        self.library_paths = cleaned
        self.config["libraries"] = cleaned
        if hasattr(self, "library_tree"):
            self._refresh_library_tree()

    def _setup_palette(self) -> None:
        palette = self.palette()
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#d4d4d4"))
        palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#d4d4d4"))
        self.setPalette(palette)

    @staticmethod
    def _shade(hex_color: str, factor: int) -> str:
        color = QtGui.QColor(hex_color)
        if not color.isValid():
            return hex_color
        if factor >= 100:
            return color.lighter(factor).name()
        return color.darker(factor).name()

    def _build_header(self) -> QtWidgets.QHBoxLayout:
        layout = QtWidgets.QHBoxLayout()
        layout.setSpacing(12)

        layout.addStretch(1)

        return layout

    def _current_colors(self, theme_override: str | None = None) -> dict[str, str]:
        presets = self.config.get("presets", {})
        theme = theme_override or self.config.get("theme", "dark")
        base = presets.get(theme) or presets.get("dark") or DEFAULT_PRESETS["dark"]
        colors = {
            "bg1": base.get("bg1", DEFAULT_PRESETS["dark"]["bg1"]),
            "bg2": base.get("bg2", DEFAULT_PRESETS["dark"]["bg2"]),
            "bg3": base.get("bg3", DEFAULT_PRESETS["dark"]["bg3"]),
            "accent": base.get("accent", DEFAULT_PRESETS["dark"]["accent"]),
            "accent2": base.get("accent2", DEFAULT_PRESETS["dark"]["accent2"]),
            "theme": theme,
        }
        colors["hover"] = self._shade(colors["bg1"], 130)
        colors["border"] = self._shade(colors["bg3"], 115)
        colors["border_alt"] = self._shade(colors["bg3"], 125)
        colors["text_primary"] = "#e6e6e6" if theme == "dark" else "#1f1f1f"
        colors["text_muted"] = "#9fa6ad" if theme == "dark" else "#4a4a4a"
        colors["accent_hover"] = self._shade(colors["accent"], 120)
        colors["accent_pressed"] = self._shade(colors["accent"], 90)

        if theme == "light":
            # Stronger separators/borders for readability in light mode.
            colors["border"] = "#8f98a3"
            colors["border_alt"] = "#7f8894"
            # Project Manager tab: light grey background with white cards/lists.
            colors["bg2"] = "#f1f3f5"
            colors["bg3"] = "#ffffff"
            colors["project_item_bg"] = "#f6f7f9"
            colors["project_item_hover"] = "#ffffff"
            colors["titlebar_bg"] = "#e5e9ef"
            colors["titlebar_text"] = "#111111"
            colors["titlebar_hover"] = "#dbe2eb"
            colors["nav_bg"] = "#e9edf2"
            colors["nav_text"] = "#111111"
            colors["nav_hover"] = "#dde3ea"
        else:
            colors["titlebar_bg"] = colors["bg1"]
            colors["titlebar_text"] = colors["text_primary"]
            colors["titlebar_hover"] = colors["hover"]
            colors["nav_bg"] = colors["bg1"]
            colors["nav_text"] = colors["text_primary"]
            colors["nav_hover"] = colors["hover"]
            colors["project_item_bg"] = colors["bg3"]
            colors["project_item_hover"] = self._shade(colors["bg3"], 125)
        return colors

    def _build_stylesheet(self, colors: dict[str, str]) -> str:
        accent = colors["accent"]
        replacements = {
            "{bg1}": colors["bg1"],
            "{bg2}": colors["bg2"],
            "{bg3}": colors["bg3"],
            "{hover}": colors["hover"],
            "{border}": colors["border"],
            "{border_alt}": colors["border_alt"],
            "{accent}": accent,
            "{accent2}": colors["accent2"],
            "{accent_hover}": colors["accent_hover"],
            "{accent_pressed}": colors["accent_pressed"],
            "{text_primary}": colors["text_primary"],
            "{text_muted}": colors["text_muted"],
            "{titlebar_bg}": colors["titlebar_bg"],
            "{titlebar_text}": colors["titlebar_text"],
            "{titlebar_hover}": colors["titlebar_hover"],
            "{nav_bg}": colors["nav_bg"],
            "{nav_text}": colors["nav_text"],
            "{nav_hover}": colors["nav_hover"],
            "{project_item_bg}": colors["project_item_bg"],
            "{project_item_hover}": colors["project_item_hover"],
        }
        stylesheet = """
            #background {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {bg2}, stop:1 {bg2});
            }
            #titleBar {
                background: {titlebar_bg};
                border: none;
                border-bottom: 1px solid {border};
            }
            #titleBarLogo { margin: 0; padding: 0; }
            QToolButton#titleBarButton,
            QToolButton#closeButton {
                background: transparent;
                color: {titlebar_text};
                border: none;
                border-radius: 0;
                padding: 0;
                margin: 0;
                min-width: 37px;
                max-width: 37px;
                min-height: 31px;
                max-height: 31px;
            }
            #settingsButton {
                background: transparent;
                color: {titlebar_text};
                border: none;
                padding: 0 4px;
                font: 12px "Segoe UI";
            }
            #settingsButton:hover { background: {titlebar_hover}; color: #ffffff; }
            #settingsButton:pressed { background: {titlebar_bg}; }
            QToolButton#titleBarButton:hover { background: {titlebar_hover}; }
            QToolButton#titleBarButton:pressed { background: {titlebar_bg}; }
            QToolButton#closeButton { background: transparent; border: none; }
            QToolButton#closeButton:hover { background: #b31b1b; color: #ffffff; }
            QToolButton#closeButton:pressed { background: #8a1111; }
            #navContainer {
                background: {nav_bg};
                border-right: 1px solid {border};
            }
            #navOverlay {
                background: {nav_bg};
                border-right: 1px solid {border};
            }
            #navSeparator {
                background: {border};
            }
            #navList {
                background: {nav_bg};
                border: none;
                color: {nav_text};
                font: 12px "Segoe UI";
                outline: none;
            }
            #navList::item {
                padding: 8px 6px;
                margin: 1px 0;
            }
            #navList::item:selected {
                background: transparent;
                color: {nav_text};
                border-left: 3px solid {accent};
                padding-left: 9px;
            }
            #navList::item:hover {
                background: {nav_hover};
            }
            QMenu {
                background: {bg3};
                color: {text_primary};
                border: 1px solid {border};
                border-radius: 10px;
                padding: 4px;
            }
            QMenu[menuRole="top"]::right-arrow {
                image: none;
                width: 0px;
                height: 0px;
            }
            QMenu::item {
                padding: 8px 12px;
                border-radius: 8px;
            }
            QMenu::item:selected {
                background: {nav_hover};
                color: {text_primary};
            }
            QToolButton#settingsButton::menu-indicator { image: none; width: 0px; height: 0px; }
            QRadioButton { color: {text_primary}; }
            QCheckBox { color: {text_primary}; }
            QLineEdit#settingsField {
                background: {bg3};
                border: 1px solid {border_alt};
                color: {text_primary};
                border-radius: 8px;
                padding: 6px 10px;
                min-height: 26px;
            }
            QLineEdit#settingsField:focus { border: 1px solid {accent}; }
            #bottomBar {
                background: {bg1};
                border-top: 1px solid {border};
            }
            QTabWidget::tab-bar {
                background: {bg1};
                padding: 6px 10px;
                border: 1px solid {border};
                border-radius: 8px;
            }
            QTabWidget::pane { border: none; top: 0px; }
            QTabBar::tab {
                background: transparent;
                padding: 10px 14px;
                font: 600 13px "Segoe UI";
                color: {text_muted};
                margin-right: 4px;
                border-radius: 6px 6px 0 0;
                border-top: 2px solid transparent;
                border-bottom: 0;
            }
            QTabBar::tab:selected {
                color: {text_primary};
                background: {bg1};
                border: none;
                border-top: 4px solid {accent};
                margin-bottom: 0;
                border-radius: 0;
            }
            QTabBar::tab:hover { color: {text_primary}; }
            #heroTitle {
                color: {text_primary};
                font: 600 24px "Segoe UI";
                letter-spacing: 0.4px;
            }
            #footer {
                color: {text_muted};
                font: 11px "Segoe UI";
            }
            #card {
                background: {bg3};
                border: 1px solid {border_alt};
                border-radius: 14px;
            }
            #libraryPanel {
                background: {bg3};
                border: 1px solid {border_alt};
                border-radius: 12px;
            }
            #libraryTree {
                background: transparent;
                border: none;
                color: {text_primary};
                font: 12px "Consolas";
            }
            #libraryTree::item { padding: 4px 6px; margin: 1px 0; }
            #libraryTree::item:selected { background: {hover}; color: {text_primary}; }
            QSplitter#blockSplitter::handle { background: {border}; }
            #blockPaletteBar {
                background: {bg1};
                border-bottom: 1px solid {border};
            }
            #cardTitle {
                color: {text_primary};
                font: 600 16px "Segoe UI";
            }
            #projectList {
                background: transparent;
                border: none;
                color: {text_primary};
                font: 13px "Consolas";
                outline: none;
            }
            #projectList::item { margin: 6px 4px; }
            #projectList::item:selected { background: transparent; }
            #projectList::item:hover { background: transparent; }
            QWidget#projectItem {
                background: {project_item_bg};
                border: 1px solid {border_alt};
                border-radius: 12px;
            }
            QWidget#projectItem:hover { background: {project_item_hover}; }
            #libraryList {
                background: {bg3};
                border: 1px solid {border_alt};
                color: {text_primary};
                font: 12px "Consolas";
            }
            #libraryList::item { padding: 6px 6px; }
            #libraryList::item:selected { background: {hover}; }
            #aboutShell {
                background: {bg3};
                border: 1px solid {border};
                border-radius: 14px;
            }
            #aboutShell QLabel {
                color: {text_primary};
            }
            #aboutShell QLabel#holderLabel {
                color: {text_muted};
            }
            #aboutInfo {
                font: 500 12px "Segoe UI";
            }
            #aboutCloseButton {
                background: transparent;
                color: {text_primary};
                border: none;
                font: 600 16px "Segoe UI";
                padding: 0 6px;
                min-width: 28px;
                min-height: 28px;
            }
            #aboutCloseButton:hover { background: {hover}; border-radius: 8px; }
            #coachOverlay { background: transparent; }
            #coachCard {
                background: {bg3};
                border: 1px solid {border};
                border-radius: 14px;
            }
            #coachTitle { color: {text_primary}; font: 650 14px "Segoe UI"; }
            #coachBody { color: {text_primary}; font: 12px "Segoe UI"; }
            #primaryButton {
                background: {accent};
                color: #ffffff;
                border: none;
                border-radius: 12px;
                padding: 10px 18px;
                font: 600 13px "Segoe UI";
            }
            #primaryButton:hover { background: {accent_hover}; }
            #primaryButton:pressed { background: {accent_pressed}; }
            #actionButton {
                background: #0dbc79;
                color: #ffffff;
                border: none;
                border-radius: 10px;
                padding: 8px 12px;
                font: 600 12px "Segoe UI";
            }
            #actionButton:hover { background: #10a36f; }
            #actionButton:pressed { background: #0b7d59; }
            #secondaryButton {
                background: {bg2};
                color: {text_primary};
                border: 1px solid {border_alt};
                border-radius: 10px;
                padding: 8px 12px;
                font: 600 12px "Segoe UI";
            }
            #secondaryButton:hover { background: {hover}; }
            #secondaryButton:pressed { background: {bg1}; }
            #dangerButton {
                background: #f14c4c;
                color: #ffffff;
                border: none;
                border-radius: 10px;
                padding: 8px 12px;
                font: 600 12px "Segoe UI";
            }
            #dangerButton:hover { background: #f0626c; }
            #dangerButton:pressed { background: #b31b1b; }
            #itemName { font: 600 13px "Segoe UI"; color: {text_primary}; }
            #holderLabel { font: 11px "Segoe UI"; color: {text_muted}; }
            #searchField {
                background: {bg3};
                border: 1px solid {border_alt};
                color: {text_primary};
                border-radius: 6px;
                padding: 6px 10px;
                font: 12px "Segoe UI";
            }
            #searchField:focus { border: 1px solid {accent}; }
            """
        for key, value in replacements.items():
            stylesheet = stylesheet.replace(key, value)
        return stylesheet

    def _apply_styles(self) -> None:
        colors = self._current_colors()
        accent = colors["accent"]
        self.accent_color = accent
        self.accent_color2 = colors["accent2"]
        self.setStyleSheet(self._build_stylesheet(colors))
        self._refresh_nav_icons()
        if hasattr(self, "block_editor"):
            self.block_editor.set_accent(accent, self.accent_color2)
        if hasattr(self, "library_tree"):
            self.library_tree.update_theme(self._current_colors())

    def _refresh_library_tree(self) -> None:
        if not hasattr(self, "library_tree"):
            return
        self.library_tree.clear()
        if not self.library_paths:
            placeholder = QtWidgets.QTreeWidgetItem(["Keine Library eingetragen"])
            placeholder.setFlags(QtCore.Qt.ItemIsEnabled)
            self.library_tree.addTopLevelItem(placeholder)
            return
        for lib_path in self.library_paths:
            path_obj = Path(lib_path).expanduser()
            root = QtWidgets.QTreeWidgetItem([path_obj.name or str(path_obj)])
            root.setToolTip(0, str(path_obj))
            root.setData(0, QtCore.Qt.UserRole, str(path_obj))
            if not path_obj.exists():
                root.setForeground(0, QtGui.QBrush(QtGui.QColor("#f14c4c")))
            self._populate_library_dir(root, path_obj, 0)
            self.library_tree.addTopLevelItem(root)
        self.library_tree.expandToDepth(1)

    def _is_basic_item(self, item: QtWidgets.QTreeWidgetItem, path_obj: Path) -> bool:
        return self._is_basic_path(path_obj) or str(item.data(0, QtCore.Qt.UserRole + 1) or "").lower() == "basic"

    @staticmethod
    def _is_basic_path(path_obj: Path) -> bool:
        return "basic" in [p.lower() for p in path_obj.parts]

    def _populate_library_dir(self, parent_item: QtWidgets.QTreeWidgetItem, path: Path, depth: int) -> None:
        if depth > 4:
            return
        if not path.exists() or not path.is_dir():
            return
        try:
            children = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return
        for child in children:
            item = QtWidgets.QTreeWidgetItem([child.name])
            item.setToolTip(0, str(child))
            item.setData(0, QtCore.Qt.UserRole, str(child))
            is_basic_path = self._is_basic_path(child)
            if is_basic_path:
                item.setData(0, QtCore.Qt.UserRole + 1, "basic")
            flags = item.flags()
            if child.is_file() and not is_basic_path:
                item.setFlags(flags & ~QtCore.Qt.ItemIsDragEnabled)
            parent_item.addChild(item)
            if child.is_dir():
                if child.name.lower() == "basic":
                    item.setData(0, QtCore.Qt.UserRole + 1, "basic_folder")
                self._populate_library_dir(item, child, depth + 1)

    def _on_library_context_menu(self, pos: QtCore.QPoint) -> None:
        item = self.library_tree.itemAt(pos)
        if item is None:
            return
        path_data = item.data(0, QtCore.Qt.UserRole)
        if not path_data:
            return
        path_obj = Path(str(path_data))
        if not path_obj.exists() or path_obj.is_dir():
            return
        is_basic = self._is_basic_item(item, path_obj)

        menu = QtWidgets.QMenu(self)
        if is_basic:
            add_basic = menu.addAction("Basic-Block hinzuf\u00fcgen")
            add_basic.triggered.connect(lambda: self._add_basic_block_from_item(item))
        elif path_obj.suffix.lower() == ".json":
            load_comp = menu.addAction("Komponente laden")
            load_comp.triggered.connect(lambda: self._load_component_from_item(item))
        if not menu.isEmpty():
            menu.exec(self.library_tree.viewport().mapToGlobal(pos))

    def _set_status(self, text: str) -> None:
        if hasattr(self, "status_label") and self.status_label:
            self.status_label.setText(text)

    def refresh_lists(self, *, show_loading: bool = False, force: bool = False) -> None:
        if show_loading:
            self._set_status("Laden ...")
            QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        try:
            try:
                new_loans = load_loans(self.loans_file)
            except Exception:
                new_loans = self._last_loans or {}
            new_shared = [
                name for name in list_projects(self.shared_dir) if name.lower() != "neuranel_data"
            ]
            new_local = [name for name in list_projects(self.local_dir) if name.lower() != "neuranel_data"]
            self._refresh_local_borrowed(new_local)

            if (
                not force
                and new_loans == self._last_loans
                and new_shared == self._last_shared
                and new_local == self._last_local
            ):
                return

            self.loans = new_loans
            self._shared_all = new_shared
            self._local_all = new_local
            self._apply_shared_filter()
            self._apply_local_filter()
            self._update_title_local_list()
            self._last_loans = new_loans
            self._last_shared = new_shared
            self._last_local = new_local

            missing = []
            if not self.shared_dir.exists():
                missing.append(f"Ordner fehlt: {self.shared_dir}")
            if not self.local_dir.exists():
                missing.append(f"Ordner fehlt: {self.local_dir}")
            if missing:
                QtWidgets.QMessageBox.warning(self, "Ordner fehlt", "\n".join(missing))
        finally:
            if show_loading:
                self._set_status("")

    def _update_title_local_list(self) -> None:
        lw = getattr(self, "title_local_list", None)
        if not lw:
            return
        lw.clear()
        lw.addItems(self._local_all)

    def _fill_shared(self, items: list[str]) -> None:
        lw = self.shared_view.list_widget
        lw.clear()
        for name in items:
            loan_info = self.loans.get(name, {}) if isinstance(self.loans, dict) else {}
            holder = loan_info.get("holder") if isinstance(loan_info, dict) else None
            timestamp = loan_info.get("timestamp") if isinstance(loan_info, dict) else None
            is_borrowed = bool(holder)
            btn_text = "n.A." if is_borrowed else "Ausleihen"
            variant = "danger" if is_borrowed else "action"
            enabled = not is_borrowed
            widget = ProjectItem(name, holder, timestamp, btn_text, None, enabled=enabled, variant=variant)
            item = QtWidgets.QListWidgetItem(lw)
            item.setSizeHint(widget.sizeHint())
            lw.addItem(item)
            lw.setItemWidget(item, widget)
            if not is_borrowed:
                widget.button.clicked.connect(lambda checked=False, n=name, w=widget: self.borrow_project(n, w))

    def _fill_local(self, items: list[str]) -> None:
        lw = self.local_view.list_widget
        lw.clear()
        for name in items:
            loan_info = self.loans.get(name, {}) if isinstance(self.loans, dict) else {}
            holder = loan_info.get("holder") if isinstance(loan_info, dict) else None
            timestamp = loan_info.get("timestamp") if isinstance(loan_info, dict) else None
            widget = ProjectItem(name, holder, timestamp, "Zurueckgeben", None)
            item = QtWidgets.QListWidgetItem(lw)
            item.setSizeHint(widget.sizeHint())
            lw.addItem(item)
            lw.setItemWidget(item, widget)
            widget.button.clicked.connect(lambda checked=False, n=name, w=widget: self.return_project(n, w))

    def _apply_shared_filter(self) -> None:
        term = self.shared_view.search_edit.text().strip().lower()
        items = [n for n in self._shared_all if term in n.lower()]
        scroll = self.shared_view.list_widget.verticalScrollBar()
        prev = scroll.value()
        self._fill_shared(items)
        scroll.setValue(min(prev, scroll.maximum()))

    def _apply_local_filter(self) -> None:
        term = self.local_view.search_edit.text().strip().lower()
        items = [n for n in self._local_all if term in n.lower()]
        scroll = self.local_view.list_widget.verticalScrollBar()
        prev = scroll.value()
        self._fill_local(items)
        scroll.setValue(min(prev, scroll.maximum()))

    def _run_move_task(
        self,
        widget: ProjectItem | None,
        message: str,
        work_fn,
        on_success,
        error_title: str,
        error_prefix: str,
    ) -> None:
        thread = QtCore.QThread(self)
        worker = MoveWorker(work_fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        self._worker_context[worker] = {
            "widget": widget,
            "thread": thread,
            "on_success": on_success,
            "error_title": error_title,
            "error_prefix": error_prefix,
        }
        self._busy = True
        self._set_buttons_enabled(False)
        if widget:
            widget.show_loading(message)
        worker.progress.connect(self._on_worker_progress, QtCore.Qt.QueuedConnection)
        worker.finished.connect(self._on_worker_finished, QtCore.Qt.QueuedConnection)
        self._threads.append(thread)
        self._workers.append(worker)
        thread.start()

    @QtCore.Slot(int, int, str)
    def _on_worker_progress(self, done_bytes: int, total_bytes: int, stage: str = "") -> None:
        worker = self.sender()
        if not isinstance(worker, MoveWorker):
            return
        ctx = self._worker_context.get(worker)
        widget = ctx.get("widget") if ctx else None
        if widget:
            if stage:
                widget.set_status_prefix(stage)
            widget.update_progress(done_bytes, total_bytes)

    @QtCore.Slot(bool, str)
    def _on_worker_finished(self, success: bool, error: str) -> None:
        worker = self.sender()
        if not isinstance(worker, MoveWorker):
            return
        ctx = self._worker_context.pop(worker, {})
        widget: ProjectItem | None = ctx.get("widget")
        thread: QtCore.QThread | None = ctx.get("thread")
        on_success = ctx.get("on_success")
        error_title = ctx.get("error_title", "Fehler")
        error_prefix = ctx.get("error_prefix", "Fehler")

        if widget:
            widget.hide_loading()
        self._busy = False
        self._set_buttons_enabled(True)
        if thread in self._threads:
            self._threads.remove(thread)
        if worker in self._workers:
            self._workers.remove(worker)

        if thread:
            thread.quit()
            thread.wait()
            thread.deleteLater()
        worker.deleteLater()

        if success and callable(on_success):
            on_success()
        elif not success:
            QtWidgets.QMessageBox.critical(self, error_title, f"{error_prefix}: {error or 'Unbekannter Fehler'}")

    def _check_shared_connection(self, *, require_write: bool = False) -> bool:
        if not self.shared_dir or not self.shared_dir.exists() or not self.shared_dir.is_dir():
            QtWidgets.QMessageBox.critical(
                self,
                "Shared-Ordner nicht erreichbar",
                f"Der Shared-Ordner fehlt oder ist nicht erreichbar:\n{self.shared_dir}",
            )
            return False
        try:
            # Attempt a simple read to verify accessibility.
            next(self.shared_dir.iterdir(), None)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(
                self,
                "Shared-Ordner nicht lesbar",
                f"Der Shared-Ordner kann nicht gelesen werden:\n{exc}",
            )
            return False
        if require_write:
            test_file = self.shared_dir / ".neuranel_check"
            try:
                test_file.write_text("", encoding="utf-8")
                try:
                    test_file.unlink()
                except OSError:
                    pass
            except OSError as exc:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Shared-Ordner nicht schreibbar",
                    f"Der Shared-Ordner kann nicht beschrieben werden:\n{exc}",
                )
                return False
        return True

    def borrow_project(self, name: str, widget: ProjectItem | None = None) -> None:
        if self._busy:
            return
        if not self._check_shared_connection(require_write=True):
            return
        current_user = getuser()
        existing_loan = self.loans.get(name) if isinstance(self.loans, dict) else None
        if isinstance(existing_loan, dict):
            holder = existing_loan.get("holder")
            if holder and holder != current_user:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Bereits ausgeliehen",
                    f"{name} wird bereits von {holder} gehalten.",
                )
                return

        src = self.shared_dir / name
        dst = self.local_dir / name
        if not src.exists():
            QtWidgets.QMessageBox.warning(self, "Fehlt", f"Projekt nicht gefunden: {src}")
            return
        if dst.exists():
            QtWidgets.QMessageBox.warning(
                self,
                "Bereits vorhanden",
                f"Im local-Ordner existiert bereits {name}. Bitte zuerst entfernen oder zurueckgeben.",
            )
            return

        def work(progress_emit):
            self.local_dir.mkdir(parents=True, exist_ok=True)
            self._copy_directory_with_progress(src, dst, progress_emit)
            try:
                ts = datetime.now().isoformat(timespec="seconds")
                self.loans[name] = {
                    "holder": current_user,
                    "timestamp": ts,
                }
                save_loans(self.loans_file, self.loans)
                self._update_local_borrow_record(name, ts, current_user)
            except Exception:
                try:
                    shutil.rmtree(dst, onerror=_handle_remove_readonly)
                except Exception:
                    pass
                raise

        self._run_move_task(
            widget,
            "Verschiebe",
            work,
            self.refresh_lists,
            "Fehler",
            "Kopieren fehlgeschlagen",
        )

    def return_project(self, name: str, widget: ProjectItem | None = None) -> None:
        if self._busy:
            return
        if not self._check_shared_connection(require_write=True):
            return
        src = self.local_dir / name
        dst = self.shared_dir / name
        if not src.exists():
            QtWidgets.QMessageBox.warning(self, "Fehlt", f"Projekt nicht gefunden: {src}")
            return

        def work(progress_emit):
            if dst.exists():
                self._backup_shared_project(name, progress_emit)
                shutil.rmtree(dst, onerror=_handle_remove_readonly)
            self.shared_dir.mkdir(parents=True, exist_ok=True)
            self._copy_directory_with_progress(src, dst, progress_emit, "Rueckgabe")
            if isinstance(self.loans, dict) and name in self.loans:
                del self.loans[name]
            save_loans(self.loans_file, self.loans)
            self._remove_local_borrow_record(name)
            shutil.rmtree(src, onerror=_handle_remove_readonly)

        self._run_move_task(
            widget,
            "Rueckgabe",
            work,
            self.refresh_lists,
            "Fehler",
            "Zurueckgeben fehlgeschlagen",
        )

    def _backup_shared_project(self, name: str, progress_emit=None) -> None:
        """Create a timestamped backup of an existing shared project before it is overwritten."""
        if not self.backup_dir:
            return
        src = self.shared_dir / name
        if not src.exists():
            return
        backup_root = Path(self.backup_dir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = backup_root / name / timestamp
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            existing = sorted([p for p in target.parent.iterdir() if p.is_dir()])
            if len(existing) >= 5:
                oldest = existing[0]
                shutil.rmtree(oldest, onerror=_handle_remove_readonly)
            emit = progress_emit or (lambda d, t, stage="": None)
            self._copy_directory_with_progress(src, target, emit, "Backup")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Backup fehlgeschlagen: {target} ({exc})") from exc

    def _copy_directory_with_progress(self, src: Path, dst: Path, progress_emit, stage_prefix: str | None = None) -> None:
        total_bytes = 0
        for root, _, files in os.walk(src):
            for fname in files:
                try:
                    total_bytes += (Path(root) / fname).stat().st_size
                except OSError:
                    continue
        done_bytes = 0
        progress_emit(done_bytes, total_bytes, stage_prefix or "")
        for root, dirs, files in os.walk(src):
            rel_root = Path(root).relative_to(src)
            target_root = dst / rel_root
            target_root.mkdir(parents=True, exist_ok=True)
            for d in dirs:
                (target_root / d).mkdir(parents=True, exist_ok=True)
            for fname in files:
                s = Path(root) / fname
                d = target_root / fname
                shutil.copy2(s, d)
                try:
                    done_bytes += s.stat().st_size
                except OSError:
                    pass
                progress_emit(done_bytes, total_bytes, stage_prefix or "")
        progress_emit(total_bytes, total_bytes, stage_prefix or "")

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for lw in (self.shared_view.list_widget, self.local_view.list_widget):
            for i in range(lw.count()):
                widget = lw.itemWidget(lw.item(i))
                if not isinstance(widget, ProjectItem):
                    continue
                if not enabled:
                    widget.button.setEnabled(False)
                else:
                    widget.button.setEnabled(
                        (not widget._static_disabled) and widget.status_label.text().strip() == ""
                    )


class NodeEditorWidget(QtWidgets.QWidget):
    dirty_changed = QtCore.Signal(bool)
    component_loaded = QtCore.Signal(str)
    def __init__(
        self, accent_color: str = "#3f8efc", accent_color_secondary: str = "#13a8cd", parent: QtWidgets.QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.accent_color = accent_color or "#3f8efc"
        self.accent_color_secondary = accent_color_secondary or "#13a8cd"
        self.grid_size = 20
        self.scene = QtWidgets.QGraphicsScene(self)
        self.scene.setSceneRect(0, 0, 1600, 900)
        self.view = NodeGraphicsView(self.scene, self)
        self.view.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing)
        self.view.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)
        self.view.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)
        self.view.setAcceptDrops(True)
        self.setAcceptDrops(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view)

        self._blocks: list[NodeBlock] = []
        self._pending_connector: ConnectorItem | None = None
        self.current_component_path: Path | None = None
        self.current_component_name: str = ""
        self._dirty: bool = False
        self._block_id_counter: int = 0
        self._suspend_dirty: bool = False
        self._line_active: bool = False
        self._line_points: list[QtCore.QPointF] = []
        self._line_direction: str | None = None
        self._line_item: LineDraftItem | None = None
        self._line_button: QtWidgets.QPushButton | None = None
        self._line_preview: QtCore.QPointF | None = None
        self._line_start_connector: ConnectorItem | None = None

    def set_accent(self, accent: str, accent2: str | None = None) -> None:
        if accent:
            self.accent_color = accent
        if accent2:
            self.accent_color_secondary = accent2
        for item in self.scene.items():
            if isinstance(item, ConnectionItem):
                pen = item.pen()
                pen.setColor(QtGui.QColor(accent))
                item.setPen(pen)
        for block in self._blocks:
            for connector in block.connectors:
                connector.refresh_brush(self.accent_color, self.accent_color_secondary)

    def set_line_button(self, btn: QtWidgets.QPushButton) -> None:
        self._line_button = btn

    def toggle_line_mode(self, enabled: bool) -> None:
        if not enabled:
            self._cancel_line()
            return
        self._line_active = False
        self._line_points = []
        self._line_direction = None
        self._line_item = None
        self._line_preview = None

    def clear_scene(self) -> None:
        for item in list(self.scene.items()):
            self.scene.removeItem(item)
        self._blocks.clear()
        self._pending_connector = None
        self._block_id_counter = 0
        self._dirty = False
        self._emit_dirty()

    def add_block(self, title: str | None = None, block_config: dict | None = None, *, mark_dirty: bool = True) -> "NodeBlock":
        idx = len(self._blocks) + 1
        cfg = block_config or {}
        block_id = str(cfg.get("id") or cfg.get("block_id") or f"b{self._block_id_counter + 1}")
        self._block_id_counter += 1
        block = NodeBlock(
            title or cfg.get("title") or f"Block {idx}",
            self,
            inputs=cfg.get("inputs"),
            outputs=cfg.get("outputs"),
            allow_inputs=cfg.get("allow_inputs", True),
            allow_outputs=cfg.get("allow_outputs", True),
            input_labels=cfg.get("input_labels"),
            output_labels=cfg.get("output_labels"),
            block_type=cfg.get("block_type") or cfg.get("type"),
            block_id=block_id,
        )
        self.scene.addItem(block)
        pos = cfg.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            try:
                block.setPos(float(pos[0]), float(pos[1]))
            except (TypeError, ValueError):
                block.setPos(80 + idx * 50, 80 + idx * 30)
        else:
            block.setPos(80 + idx * 50, 80 + idx * 30)
        self._blocks.append(block)
        block.setSelected(True)
        if mark_dirty:
            self.mark_dirty()
        return block

    def _selected_block(self) -> "NodeBlock | None":
        for item in self.scene.selectedItems():
            if isinstance(item, NodeBlock):
                return item
        return None

    def add_connector_to_selected(self, kind: str) -> bool:
        block = self._selected_block()
        if not block:
            return False
        if kind == "input":
            return bool(block.add_input())
        elif kind == "output":
            return bool(block.add_output())
        else:
            return False

    def create_connection(self, start: "ConnectorItem", end: "ConnectorItem") -> None:
        connection = ConnectionItem(start, end, self.accent_color)
        self.scene.addItem(connection)
        start.add_connection(connection)
        end.add_connection(connection)
        connection.update_path()
        self.mark_dirty()
        self._cancel_line()

    def mark_dirty(self, dirty: bool = True) -> None:
        if self._suspend_dirty:
            return
        if self._dirty == dirty:
            return
        self._dirty = dirty
        self._emit_dirty()

    def snap_point(self, point: QtCore.QPointF) -> QtCore.QPointF:
        g = float(self.grid_size or 20)
        x = round(point.x() / g) * g
        y = round(point.y() / g) * g
        return QtCore.QPointF(x, y)

    def _emit_dirty(self) -> None:
        self.dirty_changed.emit(bool(self._dirty))

    @staticmethod
    def _aligned_point(origin: QtCore.QPointF, snapped: QtCore.QPointF, direction: str) -> QtCore.QPointF:
        if direction == "v":
            return QtCore.QPointF(origin.x(), snapped.y())
        return QtCore.QPointF(snapped.x(), origin.y())

    def is_line_mode_active(self) -> bool:
        return bool(self._line_button and self._line_button.isChecked())

    def _cancel_line(self) -> None:
        self._line_active = False
        self._line_points = []
        self._line_direction = None
        self._line_preview = None
        self._line_start_connector = None
        if self._line_item and self._line_item.scene():
            self._line_item.scene().removeItem(self._line_item)
        self._line_item = None
        if self._line_button:
            self._line_button.setChecked(False)

    def handle_line_mouse_press(self, event: QtGui.QMouseEvent, scene_pos: QtCore.QPointF) -> bool:
        if not self.is_line_mode_active():
            return False
        if event.button() != QtCore.Qt.LeftButton:
            return False
        conn = self._find_connector(scene_pos)
        snapped = self.snap_point(scene_pos)
        if not self._line_active:
            if conn:
                self._line_start_connector = conn
                start_pt = self.snap_point(conn.scene_center())
            else:
                start_pt = snapped
            self._line_active = True
            self._line_points = [start_pt]
            self._line_direction = None
            self._line_item = LineDraftItem(self.accent_color_secondary)
            self.scene.addItem(self._line_item)
            self._line_item.update_points(self._line_points)
            return True
        # already drawing: check connector finish
        if conn and self._line_start_connector:
            start = self._line_start_connector
            end = conn
            # enforce opposite kinds
            if start.kind == "output" and end.kind == "input":
                self.create_connection(start, end)
                self._cancel_line()
                return True
            if start.kind == "input" and end.kind == "output":
                self.create_connection(end, start)
                self._cancel_line()
                return True
        # fix current preview point and toggle direction
        origin = self._line_points[-1]
        target = self._aligned_point(origin, snapped, self._line_direction or "h")
        if self._line_preview is not None:
            target = self._line_preview
        self._line_points.append(target)
        self._line_preview = None
        self._line_direction = "v" if (self._line_direction == "h") else "h"
        if self._line_item:
            self._line_item.update_points(self._line_points)
        return True

    def handle_line_mouse_move(self, scene_pos: QtCore.QPointF) -> bool:
        if not self.is_line_mode_active() or not self._line_active or not self._line_points:
            return False
        snapped = self.snap_point(scene_pos)
        origin = self._line_points[-1]
        if self._line_direction is None:
            # choose initial direction
            dx = abs(snapped.x() - self._line_points[0].x())
            dy = abs(snapped.y() - self._line_points[0].y())
            self._line_direction = "h" if dx >= dy else "v"
            origin = self._line_points[0]
            self._line_points = [origin]
        target = self._aligned_point(origin, snapped, self._line_direction)
        self._line_preview = target
        pts = list(self._line_points)
        pts.append(target)
        if self._line_item:
            self._line_item.update_points(pts)
        return True

    def handle_line_mouse_double(self, event: QtGui.QMouseEvent, scene_pos: QtCore.QPointF) -> bool:
        if not self.is_line_mode_active() or not self._line_active:
            return False
        if event.button() != QtCore.Qt.LeftButton:
            return False
        snapped = self.snap_point(scene_pos)
        origin = self._line_points[-1] if self._line_points else snapped
        end_pt = self._aligned_point(origin, snapped, self._line_direction or "h")
        if self._line_preview is not None:
            end_pt = self._line_preview
        if not self._line_points:
            self._line_points = [origin]
        self._line_points.append(end_pt)
        if self._line_item:
            self._line_item.update_points(self._line_points)
        self.mark_dirty()
        self._cancel_line()
        return True

    def _find_connector(self, scene_pos: QtCore.QPointF) -> ConnectorItem | None:
        for itm in self.scene.items(scene_pos):
            if isinstance(itm, ConnectorItem):
                return itm
        return None

    def load_component(self, path: Path) -> bool:
        self._suspend_dirty = True
        try:
            with Path(path).open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        if data.get("kind") == "basic" or data.get("basic") is True or ("basic" in [p.lower() for p in path.parts]):
            self._suspend_dirty = False
            return False
        self._cancel_line()
        nodes = data.get("nodes")
        if not isinstance(nodes, list):
            nodes = []
        self.clear_scene()
        id_to_block: dict[str, NodeBlock] = {}
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id", idx))
            ntype = (node.get("type") or "").lower()
            allow_inputs = node.get("allow_inputs", True)
            allow_outputs = node.get("allow_outputs", True)
            inputs_cfg = node.get("inputs")
            outputs_cfg = node.get("outputs")
            if ntype == "eingang":
                allow_inputs = False
                if outputs_cfg is None:
                    outputs_cfg = 1
            if ntype == "ausgang":
                allow_outputs = False
                if inputs_cfg is None:
                    inputs_cfg = 1
            block = self.add_block(
                node.get("title") or node.get("name"),
                {
                    "inputs": inputs_cfg,
                    "outputs": outputs_cfg,
                    "allow_inputs": allow_inputs,
                    "allow_outputs": allow_outputs,
                    "pos": node.get("pos"),
                    "input_labels": node.get("input_labels"),
                    "output_labels": node.get("output_labels"),
                    "type": node.get("type"),
                    "id": node.get("id"),
                },
            )
            id_to_block[node_id] = block

        connections = data.get("connections", [])
        if isinstance(connections, list):
            for conn in connections:
                if not isinstance(conn, dict):
                    continue
                src = conn.get("from") or conn.get("source")
                dst = conn.get("to") or conn.get("target")
                if not isinstance(src, dict) or not isinstance(dst, dict):
                    continue
                src_block = id_to_block.get(str(src.get("node")))
                dst_block = id_to_block.get(str(dst.get("node")))
                if not src_block or not dst_block:
                    continue
                try:
                    out_idx = int(src.get("output", 0))
                    in_idx = int(dst.get("input", 0))
                except (TypeError, ValueError):
                    continue
                if out_idx < 0 or in_idx < 0:
                    continue
                if out_idx >= len(src_block.outputs) or in_idx >= len(dst_block.inputs):
                    continue
                self.create_connection(src_block.outputs[out_idx], dst_block.inputs[in_idx])
        self.current_component_path = path
        self.current_component_name = path.stem
        self.component_loaded.emit(self.current_component_name)
        self._dirty = False
        self._emit_dirty()
        self._suspend_dirty = False
        return True

    def add_basic_block(self, data: dict, fallback_name: str) -> NodeBlock | None:
        allow_inputs = data.get("allow_inputs", True)
        allow_outputs = data.get("allow_outputs", True)
        ntype = (data.get("type") or data.get("name") or "").lower()
        inputs_cfg = data.get("inputs")
        outputs_cfg = data.get("outputs")
        if ntype == "eingang":
            allow_inputs = False
            if outputs_cfg is None:
                outputs_cfg = 1
        if ntype == "ausgang":
            allow_outputs = False
            if inputs_cfg is None:
                inputs_cfg = 1
        block = self.add_block(
            data.get("title") or data.get("name") or fallback_name,
            {
                "inputs": inputs_cfg,
                "outputs": outputs_cfg,
                "allow_inputs": allow_inputs,
                "allow_outputs": allow_outputs,
                "input_labels": data.get("input_labels"),
                "output_labels": data.get("output_labels"),
                "type": data.get("type"),
                "block_type": "basic",
            },
            mark_dirty=True,
        )
        return block

    def serialize_component(self) -> dict:
        nodes = []
        for block in self._blocks:
            nodes.append(block.to_dict())
        connections = []
        for item in self.scene.items():
            if not isinstance(item, ConnectionItem):
                continue
            start = item.start_connector
            end = item.end_connector
            s_block = start.parentItem()
            e_block = end.parentItem()
            if not isinstance(s_block, NodeBlock) or not isinstance(e_block, NodeBlock):
                continue
            try:
                s_out_idx = s_block.outputs.index(start)
                e_in_idx = e_block.inputs.index(end)
            except ValueError:
                continue
            connections.append(
                {
                    "from": {"node": s_block.block_id, "output": s_out_idx},
                    "to": {"node": e_block.block_id, "input": e_in_idx},
                }
            )
        return {"name": self.current_component_name or "Komponente", "nodes": nodes, "connections": connections}

    def save_current_component(self) -> tuple[bool, str | None]:
        if not self.current_component_path:
            return False, "Kein Zielpfad gesetzt."
        data = self.serialize_component()
        try:
            self.current_component_path.parent.mkdir(parents=True, exist_ok=True)
            with self.current_component_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._dirty = False
            self._emit_dirty()
            return True, None
        except Exception as exc:
            return False, str(exc)

    def handle_library_drop(self, mime: QtCore.QMimeData, scene_pos: QtCore.QPointF) -> None:
        if not mime.hasFormat("application/x-library-path"):
            return
        raw = mime.data("application/x-library-path")
        try:
            path_str = bytes(raw).decode("utf-8")
        except Exception:
            return
        path = Path(path_str)
        if not path.exists() or not path.is_file():
            return
        kind = None
        if mime.hasFormat("application/x-library-kind"):
            try:
                kind = bytes(mime.data("application/x-library-kind")).decode("utf-8")
            except Exception:
                kind = None
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        is_basic = (
            data.get("kind") == "basic"
            or data.get("basic") is True
            or (kind and "basic" in kind)
            or ("basic" in [p.lower() for p in path.parts])
        )
        if not is_basic:
            # drag/drop nur für Basic-Blocks erlaubt
            return
        if not self.current_component_path:
            # kein Component-Kontext offen -> abbrechen
            return
        block = self.add_basic_block(data, path.stem)
        if block:
            block.setPos(self.snap_point(scene_pos))
        return True

    def handle_connector_click(self, connector: "ConnectorItem") -> None:
        if self._pending_connector is None:
            self._pending_connector = connector
            connector.setHighlighted(True)
            return
        if connector is self._pending_connector:
            connector.setHighlighted(False)
            self._pending_connector = None
            return

        start = self._pending_connector
        end = connector
        if start.kind == end.kind:
            start.setHighlighted(False)
            self._pending_connector = connector
            connector.setHighlighted(True)
            return

        if start.kind == "input" and end.kind == "output":
            start, end = end, start

        if start.kind != "output" or end.kind != "input":
            start.setHighlighted(False)
            self._pending_connector = None
            return

        self.create_connection(start, end)
        start.setHighlighted(False)
        end.setHighlighted(False)
        self._pending_connector = None


class NodeBlock(QtWidgets.QGraphicsRectItem):
    def __init__(
        self,
        title: str,
        editor: NodeEditorWidget,
        inputs: int | list[str] | None = None,
        outputs: int | list[str] | None = None,
        allow_inputs: bool = True,
        allow_outputs: bool = True,
        input_labels: list[str] | None = None,
        output_labels: list[str] | None = None,
        block_type: str | None = None,
        block_id: str | None = None,
    ) -> None:
        super().__init__(0, 0, 220, 120)
        self.editor = editor
        self.allow_inputs = allow_inputs
        self.allow_outputs = allow_outputs
        self.block_type = block_type
        self.block_id = block_id or title
        self.setAcceptDrops(True)
        self.setBrush(QtGui.QColor("#1f1f1f"))
        self.setPen(QtGui.QPen(QtGui.QColor("#3c3c3c"), 1.2))
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QtWidgets.QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

        self.title_item = QtWidgets.QGraphicsSimpleTextItem(title, self)
        self.title_item.setBrush(QtGui.QBrush(QtGui.QColor("#e6e6e6")))
        self.title_item.setPos(12, 10)

        self.inputs: list[ConnectorItem] = []
        self.outputs: list[ConnectorItem] = []
        self.connectors: list[ConnectorItem] = []

        def init_side(target_list: list[ConnectorItem], cfg, labels, is_input: bool) -> None:
            if cfg is None:
                count = 1
            elif isinstance(cfg, int):
                count = max(0, cfg)
            elif isinstance(cfg, list):
                count = len(cfg)
            else:
                count = 1
            for idx in range(count):
                label = None
                if isinstance(labels, list) and idx < len(labels):
                    label = labels[idx]
                elif isinstance(cfg, list) and idx < len(cfg) and isinstance(cfg[idx], str):
                    label = cfg[idx]
                if is_input:
                    self.add_input(label or f"Input {idx + 1}")
                else:
                    self.add_output(label or f"Output {idx + 1}")

        init_side(self.inputs, inputs, input_labels, True)
        init_side(self.outputs, outputs, output_labels, False)
        if not self.inputs and self.allow_inputs:
            self.add_input("Input 1")
        if not self.outputs and self.allow_outputs:
            self.add_output("Output 1")

    def _layout_connectors(self) -> None:
        top_offset = 32
        spacing = 24
        count = max(len(self.inputs), len(self.outputs), 1)
        new_height = max(120, top_offset + count * spacing)
        rect = self.rect()
        if rect.height() != new_height:
            self.setRect(0, 0, rect.width(), new_height)
        for idx, conn in enumerate(self.inputs):
            y = top_offset + idx * spacing - conn.radius()
            conn.setPos(-conn.radius(), y)
        for idx, conn in enumerate(self.outputs):
            y = top_offset + idx * spacing - conn.radius()
            conn.setPos(self.rect().width() - conn.radius(), y)
            conn.align_label_left()
        for conn in self.connectors:
            conn.update_connections()
        self.editor.mark_dirty()

    def add_input(self, label: str | None = None) -> ConnectorItem | None:
        if not self.allow_inputs:
            return None
        idx = len(self.inputs) + 1
        name = label or f"Input {idx}"
        input_conn = ConnectorItem("input", name, self.editor)
        input_conn.setParentItem(self)
        self.inputs.append(input_conn)
        self.connectors.append(input_conn)
        self._layout_connectors()
        self.editor.mark_dirty()
        return input_conn

    def add_output(self, label: str | None = None) -> ConnectorItem | None:
        if not self.allow_outputs:
            return None
        idx = len(self.outputs) + 1
        name = label or f"Output {idx}"
        output_conn = ConnectorItem("output", name, self.editor)
        output_conn.setParentItem(self)
        self.outputs.append(output_conn)
        self.connectors.append(output_conn)
        self._layout_connectors()
        self.editor.mark_dirty()
        return output_conn

    def remove_connector(self, connector: "ConnectorItem") -> None:
        if connector in self.inputs:
            self.inputs.remove(connector)
        if connector in self.outputs:
            self.outputs.remove(connector)
        if connector in self.connectors:
            self.connectors.remove(connector)
        # remove connections
        for connection in list(connector.connections):
            other = None
            if connection.start_connector is connector:
                other = connection.end_connector
            elif connection.end_connector is connector:
                other = connection.start_connector
            if other and connection in other.connections:
                other.connections.remove(connection)
            if connection.scene():
                connection.scene().removeItem(connection)
        if connector.scene():
            connector.scene().removeItem(connector)
        self._layout_connectors()
        self.editor.mark_dirty()

    def is_basic(self) -> bool:
        t = str(self.block_type or "").lower()
        return t in ("basic", "eingang", "ausgang")

    def contextMenuEvent(self, event: QtWidgets.QGraphicsSceneContextMenuEvent) -> None:
        if self.is_basic():
            menu = QtWidgets.QMenu()
            delete_action = menu.addAction("Block löschen")
            action = menu.exec(event.screenPos())
            if action == delete_action:
                self._delete_block()
            return
        super().contextMenuEvent(event)

    def _delete_block(self) -> None:
        # remove connections
        for conn in list(self.connectors):
            self.remove_connector(conn)
        if self.scene():
            self.scene().removeItem(self)
        if self in self.editor._blocks:
            self.editor._blocks.remove(self)
        self.editor.mark_dirty()

    def itemChange(self, change: QtWidgets.QGraphicsItem.GraphicsItemChange, value):
        if change == QtWidgets.QGraphicsItem.ItemPositionChange:
            return self.editor.snap_point(value)
        if change == QtWidgets.QGraphicsItem.ItemPositionHasChanged:
            for connector in self.connectors:
                connector.update_connections()
            self.editor.mark_dirty()
        return super().itemChange(change, value)

    def dragEnterEvent(self, event: QtWidgets.QGraphicsSceneDragDropEvent) -> None:
        if event.mimeData().hasFormat("application/x-block-connector"):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtWidgets.QGraphicsSceneDragDropEvent) -> None:
        if event.mimeData().hasFormat("application/x-block-connector"):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QtWidgets.QGraphicsSceneDragDropEvent) -> None:
        md = event.mimeData()
        if md.hasFormat("application/x-block-connector"):
            try:
                kind = bytes(md.data("application/x-block-connector")).decode("utf-8")
            except Exception:
                kind = ""
            if kind == "input":
                self.add_input()
                event.acceptProposedAction()
                return
            if kind == "output":
                self.add_output()
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def to_dict(self) -> dict:
        return {
            "id": self.block_id,
            "title": self.title_item.text(),
            "type": self.block_type,
            "allow_inputs": self.allow_inputs,
            "allow_outputs": self.allow_outputs,
            "inputs": len(self.inputs),
            "outputs": len(self.outputs),
            "input_labels": [conn.label_item.text() for conn in self.inputs],
            "output_labels": [conn.label_item.text() for conn in self.outputs],
            "pos": [self.pos().x(), self.pos().y()],
        }


class ConnectorItem(QtWidgets.QGraphicsEllipseItem):
    def __init__(self, kind: str, label: str, editor: NodeEditorWidget) -> None:
        super().__init__(0, 0, 14, 14)
        self.kind = kind
        self.editor = editor
        self.connections: list[ConnectionItem] = []

        self.label_item = QtWidgets.QGraphicsSimpleTextItem(label, self)
        self.label_item.setBrush(QtGui.QBrush(QtGui.QColor("#dcdcdc")))
        self.label_item.setPos(18, -2)

        self.delete_btn = RemoveButtonItem(self, self._request_delete)
        self.refresh_brush(editor.accent_color, editor.accent_color_secondary)
        self.setAcceptHoverEvents(True)
        self.update_delete_btn_position()

    def radius(self) -> float:
        return self.boundingRect().width() / 2

    def refresh_brush(self, accent: str, accent2: str | None = None) -> None:
        accent_color = QtGui.QColor(accent or "#3f8efc")
        base = QtGui.QColor("#555555")
        brush_color = accent_color if self.kind == "output" else base
        self.setBrush(QtGui.QBrush(brush_color))
        self.setPen(QtGui.QPen(accent_color if self.kind == "output" else base.darker(120), 1.6))
        if self.delete_btn:
            self.delete_btn.set_accent(accent2 or "#13a8cd")

    def setHighlighted(self, enabled: bool) -> None:
        if enabled:
            pen = QtGui.QPen(QtGui.QColor(self.editor.accent_color_secondary), 2.4)
            self.setPen(pen)
            if self.delete_btn:
                self.delete_btn.show()
        else:
            self.refresh_brush(self.editor.accent_color, self.editor.accent_color_secondary)
            if self.delete_btn:
                self.delete_btn.hide()

    def align_label_left(self) -> None:
        offset = self.label_item.boundingRect().width() + 6
        self.label_item.setPos(-offset, -2)

    def add_connection(self, connection: "ConnectionItem") -> None:
        self.connections.append(connection)

    def update_connections(self) -> None:
        for connection in self.connections:
            connection.update_path()
        self.update_delete_btn_position()

    def scene_center(self) -> QtCore.QPointF:
        return self.mapToScene(self.boundingRect().center())

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.editor.handle_connector_click(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def hoverEnterEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        self.setCursor(QtCore.Qt.CrossCursor)
        super().hoverEnterEvent(event)

    def update_delete_btn_position(self) -> None:
        if not self.delete_btn:
            return
        radius = self.radius()
        btn_radius = self.delete_btn.radius()
        center_y = self.boundingRect().center().y()
        gap = 4
        if self.kind == "input":
            x = -btn_radius * 2 - gap
        else:
            x = self.boundingRect().width() + gap
        self.delete_btn.setPos(x, center_y - btn_radius)

    def _request_delete(self) -> None:
        block = self.parentItem()
        if isinstance(block, NodeBlock):
            block.remove_connector(self)


class ConnectionItem(QtWidgets.QGraphicsPathItem):
    def __init__(self, start: ConnectorItem, end: ConnectorItem, color: str) -> None:
        super().__init__()
        self.start_connector = start
        self.end_connector = end
        pen = QtGui.QPen(QtGui.QColor(color or "#3f8efc"), 2)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        self.setPen(pen)
        self.setZValue(-1)

    def update_path(self) -> None:
        start = self.start_connector.scene_center()
        end = self.end_connector.scene_center()
        editor = self.start_connector.editor
        s = editor.snap_point(start)
        e = editor.snap_point(end)
        mid_x = (s.x() + e.x()) / 2
        p1 = QtCore.QPointF(mid_x, s.y())
        p2 = QtCore.QPointF(mid_x, e.y())
        path = QtGui.QPainterPath(s)
        path.lineTo(p1)
        path.lineTo(p2)
        path.lineTo(e)
        self.setPath(path)


class NodeGraphicsView(QtWidgets.QGraphicsView):
    def __init__(self, scene: QtWidgets.QGraphicsScene, editor: NodeEditorWidget) -> None:
        super().__init__(scene)
        self.editor = editor
        self.setAcceptDrops(True)

    def drawBackground(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        super().drawBackground(painter, rect)
        grid = float(self.editor.grid_size or 20)
        left = int(rect.left()) - (int(rect.left()) % grid)
        top = int(rect.top()) - (int(rect.top()) % grid)
        lines = []
        for x in range(int(left), int(rect.right()), int(grid)):
            lines.append(QtCore.QLineF(x, rect.top(), x, rect.bottom()))
        for y in range(int(top), int(rect.bottom()), int(grid)):
            lines.append(QtCore.QLineF(rect.left(), y, rect.right(), y))
        painter.setPen(QtGui.QPen(QtGui.QColor("#3e3e3e"), 0.5))
        painter.drawLines(lines)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.mimeData().hasFormat("application/x-library-path"):
            event.acceptProposedAction()
            return
        if self.editor.is_line_mode_active():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if event.mimeData().hasFormat("application/x-library-path"):
            event.acceptProposedAction()
            return
        if self.editor.is_line_mode_active():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        if event.mimeData().hasFormat("application/x-library-path"):
            scene_pos = self.mapToScene(event.position().toPoint())
            self.editor.handle_library_drop(event.mimeData(), scene_pos)
            event.acceptProposedAction()
            return
        if self.editor.is_line_mode_active():
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if self.editor.handle_line_mouse_press(event, self.mapToScene(event.position().toPoint())):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self.editor.handle_line_mouse_move(self.mapToScene(event.position().toPoint())):
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if self.editor.handle_line_mouse_double(event, self.mapToScene(event.position().toPoint())):
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        scene_pos = self.mapToScene(event.pos())
        items = self.scene().items(scene_pos)
        target_block = None
        for itm in items:
            blk = itm
            while blk and not isinstance(blk, NodeBlock):
                blk = blk.parentItem()
            if isinstance(blk, NodeBlock):
                target_block = blk
                break
        if target_block and target_block.is_basic():
            menu = QtWidgets.QMenu(self)
            delete_action = menu.addAction("Block löschen")
            action = menu.exec(self.mapToGlobal(event.pos()))
            if action == delete_action:
                target_block._delete_block()
            event.accept()
            return
        super().contextMenuEvent(event)


class RemoveButtonItem(QtWidgets.QGraphicsEllipseItem):
    def __init__(self, parent: ConnectorItem, callback) -> None:
        super().__init__(0, 0, 12, 12, parent)
        self.callback = callback
        self.setBrush(QtGui.QBrush(QtGui.QColor("#f14c4c")))
        self.setPen(QtGui.QPen(QtGui.QColor("#8a1111"), 1.2))
        self.setZValue(2)
        self.setVisible(False)
        self._accent = "#13a8cd"

        self.x_item = QtWidgets.QGraphicsSimpleTextItem("x", self)
        self.x_item.setBrush(QtGui.QBrush(QtGui.QColor("#ffffff")))
        self.x_item.setPos(3, -1)
        self.setAcceptHoverEvents(True)

    def radius(self) -> float:
        return self.boundingRect().width() / 2

    def set_accent(self, accent: str) -> None:
        self._accent = accent or self._accent

    def hoverEnterEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        self.setCursor(QtCore.Qt.PointingHandCursor)
        super().hoverEnterEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            if callable(self.callback):
                self.callback()
            event.accept()
            return
        super().mousePressEvent(event)


class LibraryTree(QtWidgets.QTreeWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDefaultDropAction(QtCore.Qt.CopyAction)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)

    def mimeData(self, items: list[QtWidgets.QTreeWidgetItem]) -> QtCore.QMimeData:
        mime = super().mimeData(items)
        if not items:
            return mime
        item = items[0]
        path = item.data(0, QtCore.Qt.UserRole)
        if path:
            mime.setData("application/x-library-path", str(path).encode("utf-8"))
            mime.setText(str(path))
        kind = item.data(0, QtCore.Qt.UserRole + 1)
        if kind:
            mime.setData("application/x-library-kind", str(kind).encode("utf-8"))
        else:
            from pathlib import Path as _Path
            if path and "basic" in [p.lower() for p in _Path(str(path)).parts]:
                mime.setData("application/x-library-kind", b"basic")
        return mime

    def update_theme(self, colors: dict) -> None:
        # no-op placeholder for future per-theme tweaks
        _ = colors


class PaletteDragButton(QtWidgets.QPushButton):
    def __init__(self, text: str, kind: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.kind = kind
        self._drag_start_pos: QtCore.QPoint | None = None

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.buttons() & QtCore.Qt.LeftButton:
            if self._drag_start_pos is None:
                return
            distance = (event.pos() - self._drag_start_pos).manhattanLength()
            if distance < QtWidgets.QApplication.startDragDistance():
                return
            self._start_drag()
            return
        super().mouseMoveEvent(event)

    def _start_drag(self) -> None:
        mime = QtCore.QMimeData()
        mime.setData("application/x-block-connector", self.kind.encode("utf-8"))
        drag = QtGui.QDrag(self)
        drag.setMimeData(mime)
        pixmap = self.grab()
        drag.setPixmap(pixmap)
        drag.setHotSpot(pixmap.rect().center())
        drag.exec(QtCore.Qt.CopyAction)


class LineDraftItem(QtWidgets.QGraphicsPathItem):
    def __init__(self, color: str) -> None:
        super().__init__()
        pen = QtGui.QPen(QtGui.QColor(color or "#13a8cd"), 2)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        self.setPen(pen)
        self.setZValue(-0.5)

    def update_points(self, pts: list[QtCore.QPointF]) -> None:
        if not pts:
            self.setPath(QtGui.QPainterPath())
            return
        path = QtGui.QPainterPath(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        self.setPath(path)


class UpdateCheckWorker(QtCore.QObject):
    finished = QtCore.Signal(object, str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    def run(self) -> None:
        try:
            req = urllib.request.Request(
                self._url,
                headers={"User-Agent": "Neuranel-Updater"},
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                payload = response.read().decode("utf-8-sig", errors="replace")
            data = json.loads(payload)
            self.finished.emit(data, "")
        except Exception as exc:
            self.finished.emit(None, str(exc))


class NavListWidget(QtWidgets.QListWidget):
    hoverEntered = QtCore.Signal()
    hoverLeft = QtCore.Signal()

    def enterEvent(self, event: QtCore.QEvent) -> None:
        super().enterEvent(event)
        self.hoverEntered.emit()

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        super().leaveEvent(event)
        self.hoverLeft.emit()


class WidthAnimator(QtCore.QObject):
    def __init__(self, target: QtWidgets.QWidget, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._target = target

    def _get_width(self) -> int:
        return self._target.width()

    def _set_width(self, value: int) -> None:
        self._target.setFixedWidth(int(value))

    width = QtCore.Property(int, _get_width, _set_width)


class CoachMarkStep:
    def __init__(self, *, target: QtWidgets.QWidget, title: str, body: str) -> None:
        self.target = target
        self.title = title
        self.body = body


class CoachMarkOverlay(QtWidgets.QWidget):
    finished = QtCore.Signal()

    def __init__(self, window: MainWindow, steps: list[CoachMarkStep]) -> None:
        super().__init__(window)
        self._window = window
        self._steps = steps
        self._index = 0
        self._highlight_rect = QtCore.QRect()
        self._recalc_timer: QtCore.QTimer | None = None
        self._closing = False
        self._is_animating = False
        self._step_anim: QtCore.QAbstractAnimation | None = None

        self.setObjectName("coachOverlay")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        self._opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._card = QtWidgets.QFrame(self)
        self._card.setObjectName("coachCard")
        card_layout = QtWidgets.QVBoxLayout(self._card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)

        self._title = QtWidgets.QLabel("")
        self._title.setObjectName("coachTitle")
        card_layout.addWidget(self._title)

        self._body = QtWidgets.QLabel("")
        self._body.setObjectName("coachBody")
        self._body.setWordWrap(True)
        card_layout.addWidget(self._body)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(8)
        self._back = QtWidgets.QPushButton("Zurueck")
        self._back.setObjectName("secondaryButton")
        self._back.setCursor(QtCore.Qt.PointingHandCursor)
        self._back.clicked.connect(self._go_back)
        self._skip = QtWidgets.QPushButton("Ueberspringen")
        self._skip.setObjectName("secondaryButton")
        self._skip.setCursor(QtCore.Qt.PointingHandCursor)
        self._skip.clicked.connect(self._finish)
        self._next = QtWidgets.QPushButton("Weiter")
        self._next.setObjectName("primaryButton")
        self._next.setCursor(QtCore.Qt.PointingHandCursor)
        self._next.clicked.connect(self._go_next)
        btn_row.addWidget(self._back)
        btn_row.addWidget(self._skip)
        btn_row.addStretch(1)
        btn_row.addWidget(self._next)
        card_layout.addLayout(btn_row)

        window.installEventFilter(self)
        if window.centralWidget():
            window.centralWidget().installEventFilter(self)

        self.setStyleSheet(window._build_stylesheet(window._current_colors()))
        self.hide()

    def start(self) -> None:
        if not self._steps:
            self._finish()
            return
        self.setGeometry(self._window.rect())
        self.show()
        self.raise_()
        self.setFocus(QtCore.Qt.OtherFocusReason)
        self._apply_step()

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Move, QtCore.QEvent.LayoutRequest):
            self._schedule_recalculate()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._schedule_recalculate()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key_Escape:
            self._finish()
            return
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Space, QtCore.Qt.Key_Right):
            self._go_next()
            return
        if event.key() == QtCore.Qt.Key_Left:
            self._go_back()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # type: ignore[override]
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        colors = self._window._current_colors()
        overlay = QtGui.QColor(0, 0, 0, 150 if colors.get("theme") == "dark" else 130)

        path = QtGui.QPainterPath()
        path.addRect(QtCore.QRectF(self.rect()))
        if not self._highlight_rect.isNull():
            hole = QtCore.QRectF(self._highlight_rect)
            path.addRoundedRect(hole, 12, 12)
            path.setFillRule(QtCore.Qt.OddEvenFill)
        painter.fillPath(path, overlay)

        if not self._highlight_rect.isNull():
            pen = QtGui.QPen(QtGui.QColor(colors.get("accent", "#007acc")))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(self._highlight_rect, 12, 12)

    def _apply_step(self) -> None:
        self._index = max(0, min(self._index, len(self._steps) - 1))
        step = self._steps[self._index]
        self._title.setText(step.title)
        self._body.setText(step.body)
        self._back.setEnabled(self._index > 0)
        self._next.setText("Fertig" if self._index == len(self._steps) - 1 else "Weiter")
        self._schedule_recalculate()

    def _schedule_recalculate(self) -> None:
        if self._recalc_timer is None:
            self._recalc_timer = QtCore.QTimer(self)
            self._recalc_timer.setSingleShot(True)
            self._recalc_timer.timeout.connect(self._recalculate)
        self._recalc_timer.start(0)

    def _recalculate(self) -> None:
        if self._closing or not self.isVisible():
            return
        self.setGeometry(self._window.rect())
        step = self._steps[self._index]
        self._highlight_rect = self._target_rect(step.target).adjusted(-8, -6, 8, 6)
        self._position_card()
        self.update()

    def _target_rect(self, widget: QtWidgets.QWidget) -> QtCore.QRect:
        if not widget:
            return QtCore.QRect()
        top_left = widget.mapToGlobal(QtCore.QPoint(0, 0))
        bottom_right = widget.mapToGlobal(QtCore.QPoint(widget.width(), widget.height()))
        return QtCore.QRect(self.mapFromGlobal(top_left), self.mapFromGlobal(bottom_right))

    def _position_card(self) -> None:
        margin = 16
        card_width = 360
        max_card_height = max(120, self.height() - margin * 2)
        self._card.setFixedWidth(card_width)
        self._card.setMaximumHeight(max_card_height)
        self._card.adjustSize()
        card_height = min(self._card.height(), max_card_height)

        r = self._highlight_rect if not self._highlight_rect.isNull() else QtCore.QRect(margin, margin, 200, 80)
        right_space = self.width() - (r.right() + margin)
        left_space = r.left() - margin

        if right_space >= card_width:
            x = r.right() + margin
            y = max(margin, min(self.height() - margin - card_height, r.top()))
        elif left_space >= card_width:
            x = r.left() - margin - card_width
            y = max(margin, min(self.height() - margin - card_height, r.top()))
        else:
            x = max(margin, min(self.width() - margin - card_width, r.center().x() - card_width // 2))
            y = r.bottom() + margin
            if y + card_height > self.height() - margin:
                y = max(margin, r.top() - margin - card_height)

        self._card.setGeometry(x, y, card_width, card_height)

    def _go_next(self) -> None:
        if self._is_animating:
            return
        if self._index >= len(self._steps) - 1:
            self._finish()
            return
        self._animate_to_index(self._index + 1)

    def _go_back(self) -> None:
        if self._is_animating:
            return
        if self._index <= 0:
            return
        self._animate_to_index(self._index - 1)

    def _finish(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._step_anim:
            self._step_anim.stop()
        self.hide()
        self.deleteLater()
        self.finished.emit()

    def _animate_to_index(self, new_index: int) -> None:
        if self._closing:
            return
        new_index = max(0, min(new_index, len(self._steps) - 1))
        if new_index == self._index:
            return

        if self._step_anim:
            self._step_anim.stop()

        self._is_animating = True
        fade_out = QtCore.QPropertyAnimation(self._opacity_effect, b"opacity", self)
        fade_out.setDuration(260)
        fade_out.setStartValue(float(self._opacity_effect.opacity()))
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        fade_in = QtCore.QPropertyAnimation(self._opacity_effect, b"opacity", self)
        fade_in.setDuration(320)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        def swap_step() -> None:
            if self._closing:
                return
            self._index = new_index
            self._apply_step()
            self._recalculate()

        fade_out.finished.connect(swap_step)

        group = QtCore.QSequentialAnimationGroup(self)
        group.addAnimation(fade_out)
        group.addAnimation(fade_in)

        def done() -> None:
            self._is_animating = False

        group.finished.connect(done)
        self._step_anim = group
        group.start()
