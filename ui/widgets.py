from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets


class ProjectCard(QtWidgets.QFrame):
    def __init__(self, title: str, parent: QtWidgets.QWidget | None = None, with_header: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._apply_shadow()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setObjectName("searchField")
        self.search_edit.setPlaceholderText("Search")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedHeight(28)

        if with_header:
            header = QtWidgets.QHBoxLayout()
            header.setSpacing(8)
            heading = QtWidgets.QLabel(title)
            heading.setObjectName("cardTitle")
            header.addWidget(heading)
            header.addStretch(1)
            header.addWidget(self.search_edit)
            layout.addLayout(header)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.list_widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.list_widget.setObjectName("projectList")
        self.list_widget.setSpacing(6)
        self.list_widget.verticalScrollBar().setObjectName("cardScrollBar")

        layout.addWidget(self.list_widget)

    def _apply_shadow(self) -> None:
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 10)
        shadow.setColor(QtGui.QColor(40, 80, 120, 60))
        self.setGraphicsEffect(shadow)


class ProjectItem(QtWidgets.QWidget):
    def __init__(
        self,
        name: str,
        holder: str | None,
        timestamp: str | None,
        action_label: str,
        action_handler,
        *,
        enabled: bool = True,
        variant: str = "action",
        extra_actions: list[dict] | None = None,
        main_last: bool = False,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("projectItem")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self._spinner_timer: QtCore.QTimer | None = None
        self._base_status_text = ""
        self._default_status_prefix = ""
        self._static_disabled = not enabled
        self._variant = variant
        self._prev_button_text: str | None = None
        self._prev_button_style: str | None = None
        self.extra_buttons: list[QtWidgets.QPushButton] = []
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        name_label = QtWidgets.QLabel(name)
        name_label.setObjectName("itemName")

        holder_label = QtWidgets.QLabel()
        holder_label.setObjectName("holderLabel")
        if holder:
            date_info = f" - {timestamp}" if timestamp else ""
            holder_label.setText(f"held by {holder}{date_info}")
        else:
            holder_label.setText("")
        self.holder_label = holder_label

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("holderLabel")
        self.status_label.setMinimumHeight(self.status_label.fontMetrics().height() + 2)

        text_layout = QtWidgets.QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(name_label)
        text_layout.addWidget(holder_label)
        text_layout.addWidget(self.status_label)

        self.button = QtWidgets.QPushButton(action_label)
        btn_obj = "dangerButton" if variant == "danger" else ("secondaryButton" if variant == "secondary" else "actionButton")
        self.button.setObjectName(btn_obj)
        self.button.setCursor(QtCore.Qt.PointingHandCursor)
        self.button.setEnabled(enabled)
        if action_handler:
            self.button.clicked.connect(action_handler)

        layout.addLayout(text_layout, 1)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)

        targets: list[tuple[str, str, bool, object]] = []
        for extra in extra_actions or []:
            label = extra.get("label")
            handler = extra.get("handler")
            variant_extra = extra.get("variant", "action")
            enabled_extra = extra.get("enabled", True)
            if not label:
                continue
            btn = QtWidgets.QPushButton(label)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn_obj_extra = "dangerButton" if variant_extra == "danger" else ("secondaryButton" if variant_extra == "secondary" else "actionButton")
            btn.setObjectName(btn_obj_extra)
            btn.setEnabled(enabled_extra)
            if handler:
                btn.clicked.connect(handler)
            self.extra_buttons.append(btn)
            targets.append((label, btn_obj_extra, enabled_extra, btn))

        if main_last:
            targets.append((action_label, btn_obj, enabled, self.button))
        else:
            targets.insert(0, (action_label, btn_obj, enabled, self.button))

        for _, _, _, btn in targets:
            btn_row.addWidget(btn)

        layout.addLayout(btn_row)

    def show_loading(self, text: str) -> None:
        self._prev_button_text = self.button.text()
        self._prev_button_style = self.button.styleSheet()
        self.button.setEnabled(False)
        self.button.setText("Transfer")
        self.button.setStyleSheet("background: #4d9cd6; color: #ffffff;")
        self._base_status_text = text
        self._default_status_prefix = text
        self.status_label.show()
        self.status_label.setText(f"{text} ...")

    def hide_loading(self) -> None:
        self.button.setEnabled(True)
        if self._prev_button_text is not None:
            self.button.setText(self._prev_button_text)
        self.button.setStyleSheet(self._prev_button_style or "")
        self.status_label.setText("")
        self._base_status_text = ""
        self._default_status_prefix = ""

    def update_progress(self, done_bytes: int, total_bytes: int) -> None:
        if total_bytes <= 0:
            total_bytes = 1
        mb_done = done_bytes / (1024 * 1024)
        mb_total = total_bytes / (1024 * 1024)
        self.status_label.setText(f"{self._base_status_text} {mb_done:.1f} MB / {mb_total:.1f} MB")

    def set_status_prefix(self, prefix: str | None) -> None:
        if prefix:
            self._base_status_text = prefix
        else:
            self._base_status_text = self._default_status_prefix


class TitleBar(QtWidgets.QFrame):
    def __init__(self, window: QtWidgets.QWidget, logo_path: Path | None = None) -> None:
        super().__init__(window)
        self._window = window
        self.setFixedHeight(32)
        self.setObjectName("titleBar")
        self._drag_pos: QtCore.QPoint | None = None
        self._was_maximized = False
        self._system_move_started = False

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(5, 0, 0, 0)
        layout.setSpacing(0)

        self.logo_label = QtWidgets.QLabel()
        self.logo_label.setObjectName("titleBarLogo")
        self.logo_label.setFixedSize(26, 26)
        self.logo_label.setScaledContents(True)
        if logo_path and Path(logo_path).exists():
            pix = QtGui.QPixmap(str(logo_path))
            self.logo_label.setPixmap(pix)

        layout.addWidget(self.logo_label)
        self.extra_layout = QtWidgets.QHBoxLayout()
        self.extra_layout.setContentsMargins(10, 0, 0, 0)
        self.extra_layout.setSpacing(1)
        layout.addLayout(self.extra_layout)
        layout.addStretch(1)

        # Simple labels for window controls.
        self.min_btn = self._build_btn("-")
        self.max_btn = self._build_btn("[]")
        self.close_btn = self._build_btn("X", obj_name="closeButton")

        self.min_btn.clicked.connect(self._window.showMinimized)
        self.max_btn.clicked.connect(self._toggle_max_restore)
        self.close_btn.clicked.connect(self._window.close)

        btn_bar = QtWidgets.QHBoxLayout()
        btn_bar.setSpacing(0)
        btn_bar.setContentsMargins(0, 0, 0, 0)
        btn_bar.addWidget(self.min_btn)
        btn_bar.addWidget(self.max_btn)
        btn_bar.addWidget(self.close_btn)
        layout.addLayout(btn_bar, 0)

    def _build_btn(self, text: str, obj_name: str = "titleBarButton") -> QtWidgets.QToolButton:
        btn = QtWidgets.QToolButton(self)
        btn.setText(text)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.setFixedSize(37, 32)
        btn.setObjectName(obj_name)
        btn.setAutoRaise(True)
        return btn

    def _toggle_max_restore(self) -> None:
        if self._window.isFullScreen():
            self._window.showNormal()
        elif self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self._was_maximized = self._window.isMaximized()
            global_pos = event.globalPosition().toPoint()
            if self._was_maximized:
                ratio = event.position().x() / max(1, self.width())
                self._window.showNormal()
                new_x = global_pos.x() - int(self._window.width() * ratio)
                new_y = global_pos.y() - 10
                self._window.move(new_x, new_y)
                self._was_maximized = False
            self._system_move_started = False
            self._drag_pos = global_pos - self._window.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._drag_pos and event.buttons() & QtCore.Qt.LeftButton:
            global_pos = event.globalPosition().toPoint()
            if not self._system_move_started:
                handle = self._window.windowHandle()
                if handle and handle.startSystemMove():
                    self._system_move_started = True
                    self._drag_pos = None
                    event.accept()
                    return
            self._window.move(global_pos - self._drag_pos)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._drag_pos = None
        self._system_move_started = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self._toggle_max_restore()
            event.accept()
        super().mouseDoubleClickEvent(event)
