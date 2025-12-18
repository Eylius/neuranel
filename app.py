from __future__ import annotations

import sys
import traceback

from PySide6 import QtCore, QtGui, QtWidgets

from config import BASE_DIR
from ui.main_window import MainWindow


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    splash = None
    try:
        logo_path = BASE_DIR / "assets" / "Neuranel_Logo_256x256.png"
        pix = QtGui.QPixmap(str(logo_path))
        if pix.isNull():
            pix = QtGui.QPixmap(300, 200)
            pix.fill(QtGui.QColor("#1f1f1f"))
        splash = QtWidgets.QSplashScreen(pix, QtCore.Qt.WindowStaysOnTopHint)
        splash.setWindowFlag(QtCore.Qt.FramelessWindowHint, True)
        splash.show()
        app.processEvents()

        window = MainWindow(splash)
        if splash:
            splash.finish(window)
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen:
            window.setGeometry(screen.availableGeometry())
        window.show()
        sys.exit(app.exec())
    except Exception:
        if splash:
            splash.close()
        # Show a visible error if startup fails (e.g. missing config/path issues).
        err = traceback.format_exc()
        QtWidgets.QMessageBox.critical(None, "Startfehler", err)
        print(err, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
