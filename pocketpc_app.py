"""PyInstaller entry point for the PocketPC Windows application."""
import ctypes
import os
from pathlib import Path
import traceback

from backend.main import main


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        # Windowed builds have no console. Preserve only the local Python
        # traceback so startup failures do not silently disappear.
        folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PocketPC"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "startup-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        except OSError:
            pass
        ctypes.windll.user32.MessageBoxW(
            0,
            "PocketPC could not start. See %LOCALAPPDATA%\\PocketPC\\startup-error.log.",
            "PocketPC startup error",
            0x10,
        )
        raise
