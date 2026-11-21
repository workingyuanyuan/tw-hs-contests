"""Check out.json in a reader's folder with the publishing checks. Copied into each folder as check.py.

Run in the folder: python3 check.py
"""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPELINE = Path("__PIPELINE__")
sys.path.insert(0, str(PIPELINE))
from validate import Cache, check  # noqa: E402

out = HERE / "out.json"
try:
    rec = json.loads(out.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as e:
    sys.exit(f"out.json is missing or not valid JSON: {e}")
if "need" in rec or "skip" in rec:
    print("OK (need or skip)")
    sys.exit(0)
folder = HERE / "check"
shutil.rmtree(folder, ignore_errors=True)
folder.mkdir()
target = folder / f"{rec.get('id', 'no-id')}.json"
shutil.copy(out, target)
errors, warnings, level = check(target, Cache())
for e in errors:
    print("error:", e)
for w in warnings:
    print("note: ", w)
print("OK" if not errors else f"{len(errors)} errors", f"(level: {level})")
sys.exit(1 if errors else 0)
