from __future__ import annotations

import os
import stat

from PySide6 import QtCore


def _handle_remove_readonly(func, path, exc_info):
    # Ensure read-only files can be deleted on Windows.
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        raise


class MoveWorker(QtCore.QObject):
    finished = QtCore.Signal(bool, str)
    progress = QtCore.Signal(int, int, str)

    def __init__(self, work_fn):
        super().__init__()
        self.work_fn = work_fn

    @QtCore.Slot()
    def run(self) -> None:
        try:
            def emit_progress(done: int, total: int, stage: str | None = "") -> None:
                self.progress.emit(done, total, stage or "")

            self.work_fn(emit_progress)
            self.finished.emit(True, "")
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(False, str(exc))
