from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6 import QtWidgets


if getattr(sys, "frozen", False):
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    exe_dir = Path(sys.executable).resolve().parent
    if (exe_dir / "assets").exists():
        base = exe_dir
    BASE_DIR = base
else:
    BASE_DIR = Path(__file__).resolve().parent
APPDATA_DIR = Path(os.getenv("LOCALAPPDATA", Path.home() / ".local" / "share"))
CONFIG_DIR = APPDATA_DIR / "Neuranel"
CONFIG_FILE = CONFIG_DIR / "config.json"
SUITE_VERSION = "v0.2.0"
PROJECT_MANAGER_VERSION = "v0.0.2"

DEFAULT_PRESETS = {
    "dark": {
        "bg1": "#181818",
        "bg2": "#212121",
        "bg3": "#303030",
        "accent": "#9047DF",
        "accent2": "#13a8cd",
    },
    "light": {
        "bg1": "#f2f2f2",
        "bg2": "#ffffff",
        "bg3": "#e5e5e5",
        "accent": "#0a84ff",
        "accent2": "#13a8cd",
    },
}


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(cfg: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        QtWidgets.QMessageBox.critical(None, "Fehler", f"Konnte config.json nicht speichern: {exc}")
