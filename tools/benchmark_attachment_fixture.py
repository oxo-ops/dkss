"""Extend the Q12 loopback fixture with generated patrol images, never real data."""
import os
import sys
import runpy
import json
import random
import hashlib
from pathlib import Path

ROOT = Path(os.environ.get("Q12_SOURCE_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tools")]
import benchmark_read_paths
from PIL import Image, ImageFilter

base_seed = benchmark_read_paths.seed


def seed(case, count):
    result = base_seed(case, count)
    m = case.m
    work = Path(sys.argv[sys.argv.index("--work-dir") + 1]).resolve()
    uploads = work / "static/uploads/TEST"
    uploads.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i in range(12):
        name = f"q12-patrol-{i:02}.jpg"
        image = Image.frombytes("RGB", (1600, 1000), random.Random(50+i).randbytes(1600*1000*3))
        image = image.filter(ImageFilter.GaussianBlur(.8))
        image.save(uploads/name, quality=85, subsampling=2)
        manifest.append(dict(name=name, bytes=(uploads/name).stat().st_size,
                             sha256=hashlib.sha256((uploads/name).read_bytes()).hexdigest()))
        m.db.session.add(m.PatrolResult(company_code="TEST", created_by_username="admin",
            created_by_name="架空作成者", target_type="user", target_username="admin", target_user="架空対象者",
            date="2026-10-29", office="Bench", category="Bad", content="架空の添付画像性能試験",
            files_json=json.dumps([name]), approval_status="未承認"))
    m.db.session.commit()
    (work/"attachment_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return result


benchmark_read_paths.seed = seed
runpy.run_path(str(ROOT / "tools/benchmark_display_fixture.py"), run_name="__main__")
