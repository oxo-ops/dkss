"""Forbid Python network access and SQLite outside the disposable fixture root."""
import os
from pathlib import Path
import sys

ROOT = Path(os.environ["DKSS_VALIDATION_TMP"]).resolve()

def guard(event, args):
    if event == "socket.connect":
        raise RuntimeError("BROWSER_ACCEPTANCE_PYTHON_NETWORK_FORBIDDEN")
    if event == "sqlite3.connect":
        database = str(args[0])
        if database == ":memory:":
            return
        if database.startswith("file:") or not Path(database).resolve().is_relative_to(ROOT):
            raise RuntimeError("BROWSER_ACCEPTANCE_EXISTING_DATABASE_FORBIDDEN")

sys.addaudithook(guard)
