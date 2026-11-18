"""Synthetic CI only: temporary SQLite, no credentials and no remote sockets."""
import os, sys, tempfile, socket, unittest
from pathlib import Path
from urllib.parse import urlsplit, unquote
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="candidate-offline-") as tmp:
    os.environ.clear()
    os.environ.update(HOME=tmp,TMPDIR=tmp,DKSS_VALIDATION_TMP=tmp,
        SECRET_KEY="synthetic-only",DATABASE_URL="sqlite:///:memory:",RENDER="",
        AWS_EC2_METADATA_DISABLED="true",AWS_SHARED_CREDENTIALS_FILE="/dev/null",
        AWS_CONFIG_FILE="/dev/null",OPENAI_API_KEY="",SMTP_HOST="",S3_BUCKET_NAME="",
        VAPID_PRIVATE_KEY="",VAPID_PUBLIC_KEY="",RATELIMIT_STORAGE_URI="memory://",
        DOCUMENT_IMPORT_WORKER_ENABLED="0")
    tempfile.tempdir=tmp
    def guard(event,args):
        if event in ("subprocess.Popen","os.system"):
            raise RuntimeError("SUBPROCESS_FORBIDDEN")
        if event in ("socket.connect","socket.bind"):
            address=args[1]
            if not isinstance(address,tuple) or address[0] not in ("127.0.0.1","::1"):
                raise RuntimeError("REMOTE_SOCKET_FORBIDDEN")
        if event=="socket.getaddrinfo" and args[0] not in ("127.0.0.1","::1"):
            raise RuntimeError("REMOTE_DNS_FORBIDDEN")
        if event=="sqlite3.connect":
            value=str(args[0])
            if value==":memory:": return
            if value.startswith("file:"):
                parsed=urlsplit(value)
                if parsed.netloc: raise RuntimeError("SQLITE_HOST_FORBIDDEN")
                value=unquote(parsed.path)
            if not Path(value).resolve().is_relative_to(Path(tmp)):
                raise RuntimeError("DATABASE_OUTSIDE_TEMP_FORBIDDEN")
    sys.addaudithook(guard)
    sys.path[:0]=[str(ROOT),str(ROOT/"tests")]
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_overview_recent_preview', 'test_read_path_performance'])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if result.testsRun==0: raise SystemExit("No tests executed")
    raise SystemExit(not result.wasSuccessful())
