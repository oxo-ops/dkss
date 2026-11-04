"""Entrypoint for offline checks or explicitly owned GitHub PostgreSQL tests."""
import argparse
import json
import os
from pathlib import Path
import platform
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=("offline", "postgres"))
parser.add_argument("--source-root", type=Path, default=HERE.parent)
args = parser.parse_args()
root = args.source_root.resolve(strict=True)
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "tests"))
from bootstrap_trace_fixture import check_source, validate_service_url
if args.mode == "postgres":
    validate_service_url(os.environ.get("DKSS_TRACE_POSTGRES_URL", ""), os.environ)
from bootstrap_trace_observer import driver_versions
print(json.dumps({"scope": "synthetic-only", "mode": args.mode,
    "pinned_source_files_verified": check_source(root), "python": list(sys.version_info[:3]),
    "os": platform.system(), "machine": platform.machine(), **driver_versions()}, sort_keys=True))
module = "test_bootstrap_trace_offline" if args.mode == "offline" else "test_bootstrap_trace_postgres"
suite = unittest.defaultTestLoader.loadTestsFromName(module)
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
