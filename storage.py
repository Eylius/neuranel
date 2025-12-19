from __future__ import annotations

import json
import os
import time
from pathlib import Path


def list_projects(folder: Path) -> list[str]:
    if not folder.exists():
        return []
    try:
        return sorted(entry.name for entry in folder.iterdir() if entry.is_dir())
    except OSError:
        return []


def load_loans(loans_file: Path) -> dict:
    candidates = [
        loans_file,
        loans_file.with_name("." + loans_file.name),
        loans_file.with_name("_" + loans_file.name),
    ]
    for candidate in candidates:
        try:
            with candidate.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            continue
        except json.JSONDecodeError:
            return {}
        except OSError as exc:
            raise RuntimeError(f"Konnte loans.json nicht lesen: {exc}") from exc
    return {}


def _try_set_hidden(path: Path) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        FILE_ATTRIBUTE_HIDDEN = 0x02
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:
            return
        ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs | FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        return


def save_loans(loans_file: Path, loans: dict) -> None:
    loans_file.parent.mkdir(parents=True, exist_ok=True)
    _try_set_hidden(loans_file.parent)
    target = loans_file
    hidden_variant = loans_file.with_name("." + loans_file.name)
    underscore_variant = loans_file.with_name("_" + loans_file.name)
    if hidden_variant.exists():
        target = hidden_variant
    elif underscore_variant.exists():
        target = underscore_variant

    payload = json.dumps(loans, indent=2, ensure_ascii=False)
    tmp = target.with_name(target.name + ".tmp")

    last_exc: OSError | None = None
    for attempt in range(6):
        try:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, target)
            _try_set_hidden(target)
            return
        except OSError as exc:
            last_exc = exc
            time.sleep(0.15 * (attempt + 1))
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass

    raise RuntimeError(f"Konnte loans.json nicht speichern: {last_exc}") from last_exc
