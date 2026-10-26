from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
LOG_DIR = ROOT / "report" / "logs"
PY = sys.executable

STEPS: list[dict] = [
    {"name": "00_check_env", "args": ["check_env.py"]},
    {"name": "01_upload", "args": ["upload.py"], "skip_if": "object_uploaded"},
    {"name": "02_mapreduce_v1", "args": ["mapreduce_v1.py"]},
    {"name": "03_mapreduce_v2", "args": ["mapreduce_v2.py"]},
    {"name": "04_duckdb", "args": ["duckdb_skills.py"]},
    {"name": "05_verify", "args": ["verify.py"]},
    {"name": "06_eda", "args": ["eda.py"]},
    {"name": "07_salary", "args": ["analyze_salary.py"]},
    {"name": "08_regions", "args": ["analyze_regions.py"]},
    {"name": "09_experience", "args": ["analyze_experience.py"]},
    {"name": "10_curated_prepare", "args": ["optimized_mapreduce.py", "prepare"]},
    {"name": "11_curated_verify", "args": ["optimized_mapreduce.py", "verify"]},
    {"name": "12_profile", "args": ["profile.py"], "long": True},
    {"name": "13_benchmark", "args": ["benchmark_optimization.py"], "long": True},
    {"name": "14_charts", "args": ["make_charts.py"]},
    {"name": "15_screenshots", "args": ["make_screenshots.py"]},
    {"name": "16_report", "args": ["make_report.py"], "optional": True},
]


def _object_uploaded() -> bool:
    sys.path.insert(0, str(SRC))
    try:
        from common import get_s3_client, VACANCIES_KEY
        info = get_s3_client().head_object(VACANCIES_KEY)
    except Exception as exc:
        print(f"  (cannot check storage: {type(exc).__name__}: {exc})")
        return False
    if info is None:
        return False
    expected = Path("data/it_vacancies_2024.csv")
    if expected.exists() and info.size != expected.stat().st_size:
        print(f"  (object size {info.size} != local {expected.stat().st_size}; will re-upload)")
        return False
    print(f"  Object already uploaded: {info.size:,} B — skipping upload")
    return True


def run_step(index: int, total: int, step: dict, skip_upload: bool,
             skip_profile: bool) -> bool:
    name = step["name"]
    if skip_upload and name == "01_upload":
        print(f"[{index}/{total}] {name} — skipped (--skip-upload)")
        return True
    if skip_profile and name in ("12_profile", "13_benchmark"):
        print(f"[{index}/{total}] {name} — skipped (--skip-profile)")
        return True
    if step.get("skip_if") == "object_uploaded" and _object_uploaded():
        return True

    script = SRC / step["args"][0]
    if not script.exists():
        if step.get("optional"):
            print(f"[{index}/{total}] {name} — skipped (script not found)")
            return True
        print(f"[{index}/{total}] {name} — FAILED: {script} not found")
        return False

    cmd = [PY, str(script)] + step["args"][1:]
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{name}.log"
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 78}\n[{index}/{total}] {name} — {started}\n"
          f"$ {' '.join(cmd)}\n{'=' * 78}", flush=True)

    t0 = time.perf_counter()
    with open(log_path, "wb") as log:
        log.write(f"$ {' '.join(cmd)}\nstarted={started}\n\n".encode("utf-8"))
        proc = subprocess.Popen(
            cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
        )
        assert proc.stdout is not None
        for raw in proc.stdout:
            sys.stdout.buffer.write(raw)
            sys.stdout.flush()
            log.write(raw)
        rc = proc.wait()
        elapsed = time.perf_counter() - t0
        log.write(f"\nfinished={datetime.now():%Y-%m-%d %H:%M:%S}\n"
                  f"exit_code={rc}\nduration_s={elapsed:.3f}\n".encode("utf-8"))

    print(f"\n[{index}/{total}] {name}: exit={rc}, {elapsed:.1f}s, log={log_path}")
    if rc != 0:
        print(f"  Pipeline stopped at {name}. See {log_path}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full HW3 pipeline.")
    parser.add_argument("--skip-upload", action="store_true",
                        help="do not re-upload raw/vacancies.csv")
    parser.add_argument("--skip-profile", action="store_true",
                        help="skip profiling and benchmark (saves ~10 min)")
    args = parser.parse_args()

    if not Path("data/it_vacancies_2024.csv").exists():
        print("WARNING: data/it_vacancies_2024.csv not found locally; "
              "upload will fail unless the object already exists.")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    total = len(STEPS)
    started = time.perf_counter()
    for index, step in enumerate(STEPS, 1):
        if not run_step(index, total, step, args.skip_upload, args.skip_profile):
            return 1
    elapsed = time.perf_counter() - started
    print(f"\n{'=' * 78}\nPIPELINE COMPLETE in {elapsed / 60:.1f} min\n"
          f"Logs: {LOG_DIR}\n{'=' * 78}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
