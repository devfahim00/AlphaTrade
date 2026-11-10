"""AlphaTrade Brain. Default: GUI. `--nogui`: headless server on 127.0.0.1:8765."""
import os
import sys

# Windowed PyInstaller builds have no stdout/stderr; give libraries something to write to.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

if __name__ == "__main__":
    if "--nogui" in sys.argv:
        import uvicorn
        from server import app
        print("AlphaTrade Brain on http://127.0.0.1:8765  (Ctrl+C to quit)")
        uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
    else:
        import gui
        gui.main()
