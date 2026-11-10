"""Entry point for the packaged exe (PyInstaller)."""
import uvicorn

from server import app

if __name__ == "__main__":
    print("AlphaTrade Brain listening on http://127.0.0.1:8765  (Ctrl+C to quit)")
    print("journal.csv is written to the folder you started this exe from.")
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
