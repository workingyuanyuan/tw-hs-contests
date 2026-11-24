"""Check out.json in a task folder. Copied into each folder as check.py.

Run in the folder: python3 check.py
A reading task is checked with the publishing checks (pipeline/validate.py), a triage task with
pipeline/triage.py, a search task with pipeline/search.py. Prints OK when out.json may be used.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPELINE = HERE.parents[2] / "pipeline"  # the folder is work/tasks/<name>/ in the repository
sys.path.insert(0, str(PIPELINE))
try:
    import jsonschema  # noqa: F401
except ImportError:  # the checks need jsonschema: run again with it
    if os.environ.get("CHECK_RERUN"):
        sys.exit("jsonschema is not installed and uv could not provide it")
    cmd = ["uv", "run", "-q", "--isolated", "--with", "jsonschema", "python", str(HERE / "check.py")]
    sys.exit(subprocess.run(cmd, env={**os.environ, "CHECK_RERUN": "1"}, check=False).returncode)

task = json.loads((HERE / "task.json").read_text(encoding="utf-8"))
out = HERE / "out.json"
try:
    rec = json.loads(out.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as e:
    sys.exit(f"out.json is missing or not valid JSON: {e}")

if task["kind"] in ("triage", "search"):
    if task["kind"] == "triage":
        from triage import problems  # noqa: E402
    else:
        from search import problems  # noqa: E402
    errors = problems(rec, task)
    for e in errors:
        print("error:", e)
    print("OK" if not errors else f"{len(errors)} errors")
    sys.exit(1 if errors else 0)

from extract import reading_shape  # noqa: E402
from validate import Cache, check  # noqa: E402

kind, problems = reading_shape(rec, task)
for e in problems:
    print("error:", e)
if problems:
    sys.exit(f"{len(problems)} errors")
if kind != "record":
    print(f"OK ({kind})")
    sys.exit(0)
folder = HERE / "check"
shutil.rmtree(folder, ignore_errors=True)
folder.mkdir()
target = folder / f"{rec['id']}.json"
shutil.copy(out, target)
errors, warnings, level = check(target, Cache(strict=True))
for e in errors:
    print("error:", e)
for w in warnings:
    print("note: ", w)
print("OK" if not errors else f"{len(errors)} errors", f"(level: {level})")
sys.exit(1 if errors else 0)
