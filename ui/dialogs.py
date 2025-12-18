from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from config import BASE_DIR


class SetupDialog(QtWidgets.QDialog):
    def __init__(
        self,
        default_language: str,
        default_shared: str,
        default_local: str,
        default_backup: str,
        default_theme: str,
        default_accent: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neuranel Ersteinrichtung")
        self.setWindowFlag(QtCore.Qt.FramelessWindowHint, True)
        self.setWindowFlag(QtCore.Qt.WindowSystemMenuHint, False)
        self.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, False)
        self.setWindowFlag(QtCore.Qt.WindowMinimizeButtonHint, False)
        self.setWindowFlag(QtCore.Qt.WindowMaximizeButtonHint, False)
        self.resize(820, 520)

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        intro = QtWidgets.QFrame()
        intro.setObjectName("setupIntro")
        intro_layout = QtWidgets.QVBoxLayout(intro)
        intro_layout.setContentsMargins(22, 22, 22, 22)
        intro_layout.setSpacing(12)
        self._intro_container = QtWidgets.QWidget()
        self._intro_stack = QtWidgets.QStackedLayout(self._intro_container)
        self._intro_stack.setStackingMode(QtWidgets.QStackedLayout.StackOne)

        self._intro_pages = [
            (
                "Welcome to Neuranel",
                "",
                "",
            ),
            (
                "Schritt 1: Sprache wählen",
                "Waehle die Sprache für die Oberfläche.",
                "Du kannst die Sprache später in den Einstellungen anpassen.",
            ),
            (
                "Schritt 2: Design wählen",
                "Stelle Dark oder Light ein und passe die Akzentfarbe an.",
                "Du kannst das Design später in den Einstellungen anpassen.",
            ),
            (
                "Schritt 3: Pfade verstehen",
                "Shared: zentraler Projektordner im Netzwerk.\nLocal: dein persönlicher Arbeitsordner.\nBackup: automatische Sicherungen bei Rückgabe (max. 5 Backups).",
                "Alle drei Pfade müssen gesetzt sein, koennen aber später geändert werden.",
            ),
        ]

        self._intro_frames: list[QtWidgets.QFrame] = []
        for idx, page in enumerate(self._intro_pages):
            frame = self._build_intro_frame(*page)
            if idx == 0:
                title_lbl = frame.findChild(QtWidgets.QLabel, "heroTitle")
                if title_lbl:
                    title_lbl.setAlignment(QtCore.Qt.AlignHCenter)
                    font = QtGui.QFont("Segoe UI", 40)
                    font.setWeight(QtGui.QFont.Weight.Light)
                    title_lbl.setFont(font)
                lay = frame.layout()
                if lay:
                    lay.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter)
            self._intro_frames.append(frame)
            self._intro_stack.addWidget(frame)
        self._intro_stack.setCurrentIndex(0)
        # Center welcome content with symmetric spacers; these are removed once Setup startet.
        self._welcome_top_spacer = QtWidgets.QSpacerItem(20, 180, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self._welcome_mid_spacer = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        intro_layout.addItem(self._welcome_top_spacer)
        intro_layout.addWidget(self._intro_container, 0, QtCore.Qt.AlignHCenter)
        intro_layout.addItem(self._welcome_mid_spacer)
        intro_layout.addSpacing(16)
        self._start_btn = QtWidgets.QPushButton("Start")
        self._start_btn.setObjectName("startButton")
        self._start_btn.clicked.connect(self._start_setup)
        self._start_btn.setMinimumWidth(160)
        intro_layout.addWidget(self._start_btn, 0, QtCore.Qt.AlignHCenter)
        self._welcome_bottom_spacer = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        intro_layout.addItem(self._welcome_bottom_spacer)
        root.addWidget(intro, 0)

        form_container = QtWidgets.QFrame()
        form_container.setObjectName("setupForm")
        form_layout = QtWidgets.QVBoxLayout(form_container)
        form_layout.setContentsMargins(24, 24, 24, 24)
        form_layout.setSpacing(14)

        self.step_label = QtWidgets.QLabel("Schritt 1 von 3: Sprache")
        self.step_label.setObjectName("holderLabel")
        form_layout.addWidget(self.step_label)

        self._stack_container = QtWidgets.QWidget()
        self._stack = QtWidgets.QStackedLayout(self._stack_container)
        self._stack.setStackingMode(QtWidgets.QStackedLayout.StackOne)
        self._form_pages: list[QtWidgets.QWidget] = []

        # Page 0: Language
        language_page = QtWidgets.QWidget()
        language_layout = QtWidgets.QVBoxLayout(language_page)
        language_layout.setContentsMargins(0, 0, 0, 0)
        language_group = QtWidgets.QGroupBox("Sprache")
        language_group_layout = QtWidgets.QVBoxLayout(language_group)
        language_group_layout.setSpacing(10)
        language_help = QtWidgets.QLabel("Waehle die Sprache der Benutzeroberflaeche.")
        language_help.setWordWrap(True)
        language_help.setObjectName("holderLabel")
        language_group_layout.addWidget(language_help)
        lang_row = QtWidgets.QHBoxLayout()
        lang_row.setSpacing(8)
        lang_label = QtWidgets.QLabel("Sprache")
        lang_label.setObjectName("itemName")
        self.language_select = QtWidgets.QComboBox()
        self.language_select.addItem("Deutsch", "de")
        self.language_select.addItem("English", "en")
        default_lang_idx = self.language_select.findData(default_language or "de")
        if default_lang_idx >= 0:
            self.language_select.setCurrentIndex(default_lang_idx)
        lang_row.addWidget(lang_label)
        lang_row.addWidget(self.language_select, 1)
        language_group_layout.addLayout(lang_row)
        language_layout.addWidget(language_group)
        language_layout.addStretch(1)
        self._stack.addWidget(language_page)
        self._form_pages.append(language_page)

        # Page 1: Paths
        paths_page = QtWidgets.QWidget()
        paths_page_layout = QtWidgets.QVBoxLayout(paths_page)
        paths_page_layout.setContentsMargins(0, 0, 0, 0)
        paths_group = QtWidgets.QGroupBox("Projekte einrichten")
        paths_layout = QtWidgets.QVBoxLayout(paths_group)
        paths_layout.setSpacing(10)
        self.shared_input = QtWidgets.QLineEdit(default_shared)
        self.shared_input.setPlaceholderText("Shared Pfad waehlen")
        self.local_input = QtWidgets.QLineEdit(default_local)
        self.local_input.setPlaceholderText("Local Pfad waehlen")
        self.backup_input = QtWidgets.QLineEdit(default_backup)
        self.backup_input.setPlaceholderText("Backup Pfad waehlen")
        paths_layout.addLayout(self._path_row("Shared Pfad", self.shared_input, self._browse_shared))
        paths_layout.addLayout(self._path_row("Local Pfad", self.local_input, self._browse_local))
        paths_layout.addLayout(self._path_row("Backup Pfad", self.backup_input, self._browse_backup))
        paths_page_layout.addWidget(paths_group)
        paths_page_layout.addStretch(1)
        self._stack.addWidget(paths_page)
        self._form_pages.append(paths_page)

        # Page 2: Appearance
        appearance_page = QtWidgets.QWidget()
        appearance_page_layout = QtWidgets.QVBoxLayout(appearance_page)
        appearance_page_layout.setContentsMargins(0, 0, 0, 0)
        appearance_group = QtWidgets.QGroupBox("Aussehen")
        appearance_layout = QtWidgets.QVBoxLayout(appearance_group)
        appearance_layout.setSpacing(10)

        theme_row = QtWidgets.QHBoxLayout()
        theme_row.setSpacing(8)
        theme_label = QtWidgets.QLabel("Modus")
        theme_label.setObjectName("itemName")
        self.dark_radio = QtWidgets.QRadioButton("Dark")
        self.light_radio = QtWidgets.QRadioButton("Light Mode")
        if default_theme == "light":
            self.light_radio.setChecked(True)
        else:
            self.dark_radio.setChecked(True)
        self._current_theme = "light" if self.light_radio.isChecked() else "dark"
        theme_row.addWidget(theme_label)
        theme_row.addWidget(self.dark_radio)
        theme_row.addWidget(self.light_radio)
        theme_row.addStretch(1)
        appearance_layout.addLayout(theme_row)

        accent_row = QtWidgets.QHBoxLayout()
        accent_row.setSpacing(8)
        accent_label = QtWidgets.QLabel("Akzentfarbe")
        accent_label.setObjectName("itemName")
        self.accent_input = QtWidgets.QLineEdit(default_accent)
        self.accent_input.setPlaceholderText("#rrggbb")
        accent_btn = QtWidgets.QPushButton("Farbe...")
        accent_btn.setObjectName("actionButton")
        accent_btn.setCursor(QtCore.Qt.PointingHandCursor)

        def pick_accent() -> None:
            color = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.accent_input.text() or default_accent), self)
            if color.isValid():
                self.accent_input.setText(color.name())

        accent_btn.clicked.connect(pick_accent)
        accent_row.addWidget(accent_label)
        accent_row.addWidget(self.accent_input, 1)
        accent_row.addWidget(accent_btn)
        appearance_layout.addLayout(accent_row)
        appearance_page_layout.addWidget(appearance_group)
        appearance_page_layout.addStretch(1)
        # Insert appearance between language and paths.
        self._stack.insertWidget(1, appearance_page)
        self._form_pages.insert(1, appearance_page)

        form_layout.addWidget(self._stack_container, 1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(10)
        self._back_btn = QtWidgets.QPushButton("Zurueck")
        self._back_btn.setObjectName("actionButton")
        self._back_btn.clicked.connect(self._go_back)
        self._next_btn = QtWidgets.QPushButton("Weiter")
        self._next_btn.setObjectName("primaryButton")
        self._next_btn.clicked.connect(self._go_next)
        self._finish_btn = QtWidgets.QPushButton("Fertig")
        self._finish_btn.setObjectName("primaryButton")
        self._finish_btn.clicked.connect(self.accept)
        self._cancel_btn = QtWidgets.QPushButton("Abbrechen")
        self._cancel_btn.setObjectName("actionButton")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._back_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._next_btn)
        btn_row.addWidget(self._finish_btn)
        form_layout.addLayout(btn_row)

        root.addWidget(form_container, 1)
        self._form_container = form_container

        self._setup_bg_path = (BASE_DIR / "assets" / "setup_bg.jpg").resolve().as_posix()
        self._default_accent = default_accent or "#0a84ff"
        self._last_valid_accent = self._default_accent
        self._apply_setup_styles(self.accent_input.text().strip() or self._default_accent, theme=self._current_theme)
        self.accent_input.textChanged.connect(self._on_accent_changed)
        self.dark_radio.toggled.connect(lambda checked: self._on_theme_toggled("dark", checked))
        self.light_radio.toggled.connect(lambda checked: self._on_theme_toggled("light", checked))
        self.shared_input.textChanged.connect(self._update_buttons)
        self.local_input.textChanged.connect(self._update_buttons)
        self.backup_input.textChanged.connect(self._update_buttons)
        self._current_step = 0
        self._stack.setCurrentIndex(0)
        self._welcome_started = False
        self._welcome_fade_played = False
        self._welcome_fade_scheduled = False
        form_container.hide()
        form_container.setMaximumWidth(0)
        intro.setMinimumWidth(260)
        self._intro_panel = intro
        self._update_buttons()

        # Slow fade-in for welcome title + Start button when the dialog is shown.
        welcome_frame = self._intro_frames[0] if self._intro_frames else None
        if welcome_frame:
            self._ensure_opacity_effect(welcome_frame).setOpacity(0.0)
        self._ensure_opacity_effect(self._start_btn).setOpacity(0.0)

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # type: ignore[override]
        super().showEvent(event)
        if self._welcome_fade_played or self._welcome_started or self._welcome_fade_scheduled:
            return
        if not self._intro_frames:
            return
        self._welcome_fade_scheduled = True
        timer = QtCore.QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._run_welcome_fade)
        timer.start(400)
        self._welcome_fade_timer = timer

    def _run_welcome_fade(self) -> None:
        if self._welcome_fade_played or self._welcome_started:
            return
        welcome_frame = self._intro_frames[0] if self._intro_frames else None
        if not welcome_frame:
            return

        frame_eff = self._ensure_opacity_effect(welcome_frame)
        btn_eff = self._ensure_opacity_effect(self._start_btn)
        frame_eff.setOpacity(0.0)
        btn_eff.setOpacity(0.0)

        frame_fade = QtCore.QPropertyAnimation(frame_eff, b"opacity", self)
        frame_fade.setDuration(900)
        frame_fade.setStartValue(0.0)
        frame_fade.setEndValue(1.0)
        frame_fade.setEasingCurve(QtCore.QEasingCurve.InOutCubic)

        btn_fade = QtCore.QPropertyAnimation(btn_eff, b"opacity", self)
        btn_fade.setDuration(900)
        btn_fade.setStartValue(0.0)
        btn_fade.setEndValue(1.0)
        btn_fade.setEasingCurve(QtCore.QEasingCurve.InOutCubic)

        group = QtCore.QParallelAnimationGroup(self)
        group.addAnimation(frame_fade)
        group.addAnimation(btn_fade)
        group.finished.connect(lambda: setattr(self, "_welcome_fade_played", True))
        group.start()
        self._welcome_fade_anim = group

    def _on_accent_changed(self) -> None:
        value = self.accent_input.text().strip()
        self._apply_setup_styles(value, theme=self._current_theme)

    def _on_theme_toggled(self, theme: str, checked: bool) -> None:
        if not checked:
            return
        if theme == self._current_theme:
            return
        self._current_theme = theme
        self._fade_apply_theme()

    def _fade_apply_theme(self) -> None:
        accent = self.accent_input.text().strip() or self._default_accent
        # Crossfade the theme change by overlaying a snapshot of the old UI and fading it out
        # after applying the new stylesheet. This avoids stuttery windowOpacity animations.
        try:
            old_pix = self.grab()
        except Exception:
            old_pix = QtGui.QPixmap()

        overlay = getattr(self, "_theme_overlay", None)
        if overlay is None:
            overlay = QtWidgets.QLabel(self)
            overlay.setObjectName("themeFadeOverlay")
            overlay.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            overlay.setScaledContents(True)
            overlay.hide()
            self._theme_overlay = overlay

        anim = getattr(self, "_theme_anim", None)
        if isinstance(anim, QtCore.QAbstractAnimation):
            try:
                anim.stop()
            except Exception:
                pass
        overlay.hide()

        overlay.setPixmap(old_pix)
        overlay.setGeometry(self.rect())
        overlay.show()
        overlay.raise_()

        eff = QtWidgets.QGraphicsOpacityEffect(overlay)
        eff.setOpacity(1.0)
        overlay.setGraphicsEffect(eff)

        self._apply_setup_styles(accent, theme=self._current_theme)

        fade = QtCore.QPropertyAnimation(eff, b"opacity", self)
        fade.setDuration(220)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        def cleanup() -> None:
            overlay.hide()
            overlay.setGraphicsEffect(None)

        fade.finished.connect(cleanup)
        self._theme_anim = fade
        fade.start(QtCore.QAbstractAnimation.DeleteWhenStopped)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # type: ignore[override]
        overlay = getattr(self, "_theme_overlay", None)
        if isinstance(overlay, QtWidgets.QLabel) and overlay.isVisible():
            overlay.setGeometry(self.rect())
        super().resizeEvent(event)

    def _apply_setup_styles(self, accent: str, *, theme: str) -> None:
        color = QtGui.QColor(accent or "")
        if not color.isValid():
            color = QtGui.QColor(self._last_valid_accent)
        else:
            self._last_valid_accent = color.name()

        accent_hex = color.name()
        accent_hover = color.lighter(115).name()
        accent_pressed = color.darker(125).name()

        if theme == "light":
            dialog_bg = "#f6f7f9"
            form_bg = "#ffffff"
            line_bg = "#ffffff"
            line_border = "#d0d7de"
            text_primary = "#111111"
            text_muted = "#5c6770"
            group_border = "#d0d7de"
            btn_default = "#e9eef5"
            btn_default_hover = "#dfe7f1"
            btn_default_pressed = "#d3deeb"
        else:
            dialog_bg = "#1e1e1e"
            form_bg = "#1b1b1b"
            line_bg = "#1e1e1e"
            line_border = "#3c3c3c"
            text_primary = "#dcdcdc"
            text_muted = "#9fa6ad"
            group_border = "#303030"
            btn_default = "#2a2a2a"
            btn_default_hover = "#343434"
            btn_default_pressed = "#202020"

        qss = """
            QDialog {
                background: __DIALOG_BG__;
                color: __TEXT_PRIMARY__;
                font: 12px "Segoe UI";
            }
            QAbstractButton { color: __TEXT_PRIMARY__; }
            QLineEdit {
                background: __LINE_BG__;
                border: 1px solid __LINE_BORDER__;
                color: __TEXT_PRIMARY__;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QLineEdit:focus { border: 1px solid __ACCENT__; }
            QLabel { color: __TEXT_PRIMARY__; }
            QLabel#holderLabel { color: __TEXT_MUTED__; }
            QRadioButton { color: __TEXT_PRIMARY__; }
            QCheckBox { color: __TEXT_PRIMARY__; }
            QComboBox {
                background: __LINE_BG__;
                border: 1px solid __LINE_BORDER__;
                color: __TEXT_PRIMARY__;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QPushButton {
                background: __BTN_DEFAULT__;
                color: __TEXT_PRIMARY__;
                border: none;
                border-radius: 8px;
                padding: 8px 12px;
                font-weight: 600;
            }
            QPushButton:hover { background: __BTN_DEFAULT_HOVER__; }
            QPushButton:pressed { background: __BTN_DEFAULT_PRESSED__; }
            QPushButton#primaryButton,
            QPushButton#actionButton {
                background: __ACCENT__;
                color: #ffffff;
            }
            QPushButton#primaryButton:hover,
            QPushButton#actionButton:hover { background: __ACCENT_HOVER__; }
            QPushButton#primaryButton:pressed,
            QPushButton#actionButton:pressed { background: __ACCENT_PRESSED__; }
            QPushButton#startButton {
                background: #ffffff;
                color: #111111;
            }
            QPushButton#startButton:hover { background: #f0f0f0; }
            QPushButton#startButton:pressed { background: #e6e6e6; }
            QGroupBox {
                border: 1px solid __GROUP_BORDER__;
                border-radius: 10px;
                margin-top: 12px;
                padding: 8px 10px 12px 10px;
                color: __TEXT_PRIMARY__;
                font-weight: 600;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            #setupIntro { border-image: url('__SETUP_BG__') 0 0 0 0 stretch stretch; }
            #setupForm { background: __FORM_BG__; }
        """
        qss = (
            qss.replace("__ACCENT__", accent_hex)
            .replace("__ACCENT_HOVER__", accent_hover)
            .replace("__ACCENT_PRESSED__", accent_pressed)
            .replace("__DIALOG_BG__", dialog_bg)
            .replace("__FORM_BG__", form_bg)
            .replace("__LINE_BG__", line_bg)
            .replace("__LINE_BORDER__", line_border)
            .replace("__TEXT_PRIMARY__", text_primary)
            .replace("__TEXT_MUTED__", text_muted)
            .replace("__GROUP_BORDER__", group_border)
            .replace("__BTN_DEFAULT__", btn_default)
            .replace("__BTN_DEFAULT_HOVER__", btn_default_hover)
            .replace("__BTN_DEFAULT_PRESSED__", btn_default_pressed)
            .replace("__SETUP_BG__", self._setup_bg_path)
        )
        self.setStyleSheet(qss)

    def _build_intro_frame(self, title: str, subtitle: str, detail: str) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title_lbl = QtWidgets.QLabel(title)
        title_lbl.setObjectName("heroTitle")
        subtitle_lbl = QtWidgets.QLabel(subtitle)
        subtitle_lbl.setWordWrap(True)
        subtitle_lbl.setObjectName("holderLabel")
        subtitle_lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        detail_lbl = QtWidgets.QLabel(detail)
        detail_lbl.setWordWrap(True)
        detail_lbl.setObjectName("holderLabel")
        detail_lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        layout.addWidget(title_lbl)
        if subtitle.strip():
            layout.addWidget(subtitle_lbl)
        if detail.strip():
            layout.addWidget(detail_lbl)
        layout.addStretch(1)
        effect = QtWidgets.QGraphicsOpacityEffect(frame)
        effect.setOpacity(1.0)
        frame.setGraphicsEffect(effect)
        return frame

    def _path_row(self, label_text: str, line_edit: QtWidgets.QLineEdit, handler) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        label = QtWidgets.QLabel(label_text)
        browse = QtWidgets.QPushButton("...")
        browse.clicked.connect(handler)
        browse.setFixedWidth(40)
        row.addWidget(label)
        row.addWidget(line_edit, 1)
        row.addWidget(browse)
        return row

    def _browse_shared(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Shared Ordner waehlen", self.shared_input.text())
        if path:
            self.shared_input.setText(path)

    def _browse_local(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Local Ordner waehlen", self.local_input.text())
        if path:
            self.local_input.setText(path)

    def _browse_backup(self) -> None:
        start = self.backup_input.text() or self.shared_input.text() or self.local_input.text()
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Backup Ordner waehlen", start)
        if path:
            self.backup_input.setText(path)

    def _is_complete(self) -> bool:
        return all(field.text().strip() for field in (self.shared_input, self.local_input, self.backup_input))

    def _update_buttons(self) -> None:
        paths_done = self._is_complete()
        self._back_btn.setEnabled(self._current_step > 0)
        self._next_btn.setVisible(self._current_step < 2)
        self._next_btn.setEnabled(True)
        self._finish_btn.setVisible(self._current_step == 2)
        self._finish_btn.setEnabled(paths_done)
        if self._current_step == 0:
            self.step_label.setText("Schritt 1 von 3: Sprache")
        elif self._current_step == 1:
            self.step_label.setText("Schritt 2 von 3: Design")
        else:
            self.step_label.setText("Schritt 3 von 3: Pfade")

    def accept(self) -> None:  # type: ignore[override]
        if not self._is_complete():
            QtWidgets.QMessageBox.warning(self, "Angaben fehlen", "Bitte alle Pfade ausfuellen, bevor du fortfaehrst.")
            return
        self.language_choice = self.language_select.currentData() or self.language_select.currentText()
        super().accept()

    def _start_setup(self) -> None:
        if self._welcome_started:
            return
        self._welcome_started = True
        self._start_btn.hide()
        self._form_container.show()
        self._form_container.setMaximumWidth(0)

        current_intro = self._intro_stack.currentWidget()
        intro_effect = self._ensure_opacity_effect(current_intro) if current_intro else None
        next_intro = self._intro_frames[1] if len(self._intro_frames) > 1 else None
        next_intro_effect = self._ensure_opacity_effect(next_intro) if next_intro else None
        if intro_effect:
            intro_effect.setOpacity(1.0)
        if next_intro_effect:
            next_intro_effect.setOpacity(0.0)

        start_width = max(self.width(), self.minimumWidth())
        target_width = max(240, min(340, int(start_width * 0.36)))
        self._intro_panel.setMaximumWidth(start_width)
        form_target_width = max(320, start_width - target_width)

        fade_out_intro: QtCore.QAbstractAnimation | None = None
        if intro_effect:
            fade_out_intro = QtCore.QPropertyAnimation(intro_effect, b"opacity", self)
            fade_out_intro.setDuration(240)
            fade_out_intro.setStartValue(1.0)
            fade_out_intro.setEndValue(0.0)
            fade_out_intro.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        width_anim = QtCore.QPropertyAnimation(self._intro_panel, b"maximumWidth", self)
        width_anim.setDuration(520)
        width_anim.setStartValue(start_width)
        width_anim.setEndValue(target_width)
        width_anim.setEasingCurve(QtCore.QEasingCurve.InOutCubic)

        form_width_anim = QtCore.QPropertyAnimation(self._form_container, b"maximumWidth", self)
        form_width_anim.setDuration(520)
        form_width_anim.setStartValue(0)
        form_width_anim.setEndValue(form_target_width)
        form_width_anim.setEasingCurve(QtCore.QEasingCurve.InOutCubic)

        resize_group = QtCore.QParallelAnimationGroup(self)
        resize_group.addAnimation(width_anim)
        resize_group.addAnimation(form_width_anim)

        fade_in_intro: QtCore.QAbstractAnimation | None = None
        if next_intro_effect:
            fade_in_intro = QtCore.QPropertyAnimation(next_intro_effect, b"opacity", self)
            fade_in_intro.setDuration(240)
            fade_in_intro.setStartValue(0.0)
            fade_in_intro.setEndValue(1.0)
            fade_in_intro.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        def switch_intro() -> None:
            if next_intro:
                self._intro_stack.setCurrentWidget(next_intro)
                if next_intro_effect:
                    next_intro_effect.setOpacity(0.0)
            # Remove welcome spacers and pin intro content to top/left before fading in the next text.
            intro_layout = self._intro_panel.layout()
            if intro_layout:
                if getattr(self, "_welcome_top_spacer", None):
                    intro_layout.removeItem(self._welcome_top_spacer)
                    self._welcome_top_spacer = None
                if getattr(self, "_welcome_mid_spacer", None):
                    intro_layout.removeItem(self._welcome_mid_spacer)
                    self._welcome_mid_spacer = None
                if getattr(self, "_welcome_bottom_spacer", None):
                    intro_layout.removeItem(self._welcome_bottom_spacer)
                    self._welcome_bottom_spacer = None
                intro_layout.setAlignment(self._intro_container, QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)

        resize_group.finished.connect(switch_intro)

        group = QtCore.QSequentialAnimationGroup(self)
        if fade_out_intro:
            group.addAnimation(fade_out_intro)
        group.addAnimation(resize_group)
        if fade_in_intro:
            group.addAnimation(fade_in_intro)

        def finalize() -> None:
            self._intro_panel.setMaximumWidth(target_width)
            self._intro_panel.setMinimumWidth(target_width)
            self._form_container.setMaximumWidth(16777215)
            self._form_container.setMinimumWidth(form_target_width)
            if next_intro_effect:
                next_intro_effect.setOpacity(1.0)
            self._update_buttons()

        group.finished.connect(finalize)
        group.start(QtCore.QAbstractAnimation.DeleteWhenStopped)

    def _go_next(self) -> None:
        if self._current_step >= 2:
            return
        self._current_step += 1
        self._animate_intro_transition(self._current_step + 1, direction=1)
        self._animate_form_transition(self._current_step, direction=1)
        self._update_buttons()

    def _go_back(self) -> None:
        if self._current_step == 0:
            return
        self._current_step -= 1
        self._animate_intro_transition(self._current_step + 1, direction=-1)
        self._animate_form_transition(self._current_step, direction=-1)
        self._update_buttons()

    def _ensure_opacity_effect(self, widget: QtWidgets.QWidget) -> QtWidgets.QGraphicsOpacityEffect:
        eff = widget.graphicsEffect()
        if not isinstance(eff, QtWidgets.QGraphicsOpacityEffect):
            eff = QtWidgets.QGraphicsOpacityEffect(widget)
            eff.setOpacity(1.0)
            widget.setGraphicsEffect(eff)
        return eff

    def _animate_intro_transition(self, next_index: int, *, direction: int = 1) -> None:
        if next_index == self._intro_stack.currentIndex():
            return
        current = self._intro_stack.currentWidget()
        target = self._intro_frames[next_index]
        if not current or not target:
            self._intro_stack.setCurrentIndex(next_index)
            return
        base_pos = QtCore.QPoint(0, 0)
        # Shift cards vertically: slide the current page up and bring the next from below (or from above when going back).
        out_offset = QtCore.QPoint(0, -60 if direction > 0 else 60)
        in_start = QtCore.QPoint(0, 60 if direction > 0 else -60)

        out_effect = self._ensure_opacity_effect(current)
        in_effect = self._ensure_opacity_effect(target)
        out_effect.setOpacity(1.0)
        in_effect.setOpacity(0.0)
        target.move(in_start)
        target.show()
        target.raise_()

        fade_out = QtCore.QPropertyAnimation(out_effect, b"opacity", self)
        fade_out.setDuration(360)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)

        move_out = QtCore.QPropertyAnimation(current, b"pos", self)
        move_out.setDuration(360)
        move_out.setStartValue(base_pos)
        move_out.setEndValue(out_offset)

        fade_in = QtCore.QPropertyAnimation(in_effect, b"opacity", self)
        fade_in.setDuration(360)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)

        move_in = QtCore.QPropertyAnimation(target, b"pos", self)
        move_in.setDuration(360)
        move_in.setStartValue(in_start)
        move_in.setEndValue(base_pos)

        out_group = QtCore.QParallelAnimationGroup(self)
        out_group.addAnimation(fade_out)
        out_group.addAnimation(move_out)

        in_group = QtCore.QParallelAnimationGroup(self)
        in_group.addAnimation(fade_in)
        in_group.addAnimation(move_in)

        group = QtCore.QSequentialAnimationGroup(self)
        group.addAnimation(out_group)
        group.addAnimation(in_group)

        def finalize() -> None:
            self._intro_stack.setCurrentIndex(next_index)
            current.move(base_pos)
            out_effect.setOpacity(1.0)
            target.move(base_pos)
            in_effect.setOpacity(1.0)

        group.finished.connect(finalize)
        group.start(QtCore.QAbstractAnimation.DeleteWhenStopped)

    def _animate_form_transition(self, next_index: int, *, direction: int = 1) -> None:
        if next_index == self._stack.currentIndex():
            return
        current = self._stack.currentWidget()
        target = self._form_pages[next_index]
        if not current or not target:
            self._stack.setCurrentIndex(next_index)
            return

        out_effect = self._ensure_opacity_effect(current)
        in_effect = self._ensure_opacity_effect(target)
        out_effect.setOpacity(1.0)
        in_effect.setOpacity(0.0)
        target.show()
        target.raise_()

        fade_out = QtCore.QPropertyAnimation(out_effect, b"opacity", self)
        fade_out.setDuration(240)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)

        fade_in = QtCore.QPropertyAnimation(in_effect, b"opacity", self)
        fade_in.setDuration(240)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)

        out_group = QtCore.QParallelAnimationGroup(self)
        out_group.addAnimation(fade_out)

        in_group = QtCore.QParallelAnimationGroup(self)
        in_group.addAnimation(fade_in)

        group = QtCore.QSequentialAnimationGroup(self)
        group.addAnimation(out_group)
        group.addAnimation(in_group)

        def finalize() -> None:
            self._stack.setCurrentIndex(next_index)
            out_effect.setOpacity(1.0)
            in_effect.setOpacity(1.0)

        group.finished.connect(finalize)
        group.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
