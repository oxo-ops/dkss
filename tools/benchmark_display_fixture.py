"""Q12 local-only fixture server; generated DB/images, public code assets only."""
import argparse
from collections import Counter
from contextvars import ContextVar
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import sys
import time

ROOT = Path(os.environ.get("Q12_SOURCE_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tools")]
os.environ.update(AWS_EC2_METADATA_DISABLED="true", DOCUMENT_IMPORT_WORKER_ENABLED="0",
                  OPENAI_API_KEY="", S3_BUCKET_NAME="", SMTP_HOST="", VAPID_PRIVATE_KEY="", VAPID_PUBLIC_KEY="")
parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=51212)
parser.add_argument("--work-dir", required=True)
args = parser.parse_args()
work = Path(args.work_dir).resolve()
work.mkdir(parents=True, exist_ok=True)

from test_workflow_regressions import WorkflowRegressionTests
from benchmark_read_paths import seed
from sqlalchemy import event
from PIL import Image, ImageFilter
from flask import request
from werkzeug.serving import make_server

WorkflowRegressionTests.setUpClass()
case = WorkflowRegressionTests()
case.setUp()
app, m = case.m.app, case.m
seed(case, 200)
types = ["トラック", "トラクタ", "トレーラ", "クレーン", "平ボディ", "乗用車"]
for i, row in enumerate(m.Vehicle.query.order_by(m.Vehicle.id)):
    row.type = types[i % len(types)]
    row.plate_area, row.plate_class, row.plate_kana, row.plate_number = "架空", "100", "あ", str(i+1)
user = m.User.query.filter_by(company_code="TEST", username="admin").one()
user.profile_image = "q12-synthetic-avatar.jpg"
m.db.session.commit()
static = work / "static"
static.mkdir(exist_ok=True)
# Never copy legacy uploads/manuals from the repository.
for folder in (ROOT / "static").iterdir():
    if folder.is_dir() and folder.name not in {"uploads", "manuals"}:
        shutil.copytree(folder, static / folder.name, dirs_exist_ok=True)
    elif folder.is_file():
        shutil.copy2(folder, static / folder.name)
uploads = static / "uploads" / "TEST"
uploads.mkdir(parents=True, exist_ok=True)
image_path = uploads / user.profile_image
if not image_path.exists():
    source = Image.frombytes("RGB", (2400, 1600), random.Random(12).randbytes(2400*1600*3))
    source = source.filter(ImageFilter.GaussianBlur(.55))
    source.save(image_path, quality=88, subsampling=2)
template_copy = work / "templates"
shutil.copytree(ROOT / "templates", template_copy, dirs_exist_ok=True)
app.template_folder = str(template_copy)
app.jinja_env.cache.clear()
app.static_folder = str(static)
app.config["UPLOAD_FOLDER"] = str(static / "uploads")
app.config["Q12_FIXTURE"] = True
cookie = app.session_interface.get_signing_serializer(app).dumps(dict(company_code="TEST", username="admin", role="admin",
    account_identity=user.account_identity, password_changed_at=user.password_changed_at, name="架空 検証", profile_image=user.profile_image))
fixture = dict(port=args.port, pid=os.getpid(), cookie=cookie, db="temporary SQLite", vehicles=200,
               avatar=dict(size=image_path.stat().st_size, dimensions=[2400,1600], sha256=hashlib.sha256(image_path.read_bytes()).hexdigest()))
(work / "fixture.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
current = ContextVar("q12_request", default=None)

def before_sql(conn,cursor,statement,parameters,context,executemany):
    meter = current.get()
    if meter is not None:
        context.q12_start = time.perf_counter()
        meter["sql"] += 1
        fingerprint = hashlib.sha256((statement+repr(parameters)).encode()).hexdigest()
        meter["fingerprints"][fingerprint] += 1
        match = re.search(r"\b(?:FROM|INTO|UPDATE)\s+[\"\[]?(\w+)", statement, re.I)
        meter["groups"][match.group(1) if match else "other"] += 1

def after_sql(conn,cursor,statement,parameters,context,executemany):
    meter = current.get()
    if meter is not None:
        meter["sql_ms"] += (time.perf_counter()-context.q12_start)*1000

event.listen(m.db.engine,"before_cursor_execute",before_sql)
event.listen(m.db.engine,"after_cursor_execute",after_sql)
wrapped = app.wsgi_app

def measured(environ, start_response):
    started = time.perf_counter()
    meter = dict(sql=0, sql_ms=0., fingerprints=Counter(), groups=Counter())
    token = current.set(meter)
    def start(status, headers, exc_info=None):
        elapsed = (time.perf_counter()-started)*1000
        duplicate = meter["sql"]-len(meter["fingerprints"])
        headers.append(("Server-Timing", f'app;dur={elapsed:.3f}, sql;dur={meter["sql_ms"]:.3f}, queries;desc="{meter["sql"]}", duplicates;desc="{duplicate}"'))
        record = dict(path=environ.get("PATH_INFO"), status=status, prepare_ms=elapsed, sql_count=meter["sql"],
                      duplicate_sql=duplicate, sql_ms=meter["sql_ms"], sql_groups=dict(meter["groups"]))
        with (work / "requests.jsonl").open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(record,ensure_ascii=False)+"\n")
        return start_response(status,headers,exc_info)
    try:
        result = wrapped(environ, start)
    finally:
        current.reset(token)
    return result

app.wsgi_app = measured
case.ctx.pop()
server = make_server("127.0.0.1", args.port, app, threaded=True)
print("Q12_FIXTURE_READY", work, flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
    WorkflowRegressionTests.tearDownClass()
