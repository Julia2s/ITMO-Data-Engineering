from __future__ import annotations

import csv
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import psutil
except ImportError:
    print("psutil не установлен: pip install psutil", file=sys.stderr)
    sys.exit(1)

SCRIPTS_DIR = Path(__file__).resolve().parent
LOCAL_OUT_DIR = "data/results_profile"
LOG_DIR = "report/logs"
N_RUNS = int(os.environ.get("PROFILE_RUNS", "3"))
SAMPLING_INTERVAL_S = 0.02

METHODS = [
    {"name": "mapreduce_v1", "label": "MapReduce v1 (naive)",     "script": "mapreduce_v1.py"},
    {"name": "mapreduce_v2", "label": "MapReduce v2 (optimized)", "script": "mapreduce_v2.py"},
    {"name": "duckdb",       "label": "DuckDB SQL",                "script": "duckdb_skills.py"},
]

def measure_process_tree_rss(proc: psutil.Process) -> int:
    try:
        total = proc.memory_info().rss
        for child in proc.children(recursive=True):
            try:
                total += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return total
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0

def run_once(method: dict, run_id: int) -> dict:
    script_path = SCRIPTS_DIR / method["script"]
    cmd = [sys.executable, str(script_path)]
    print(f"\n--- {method['label']} (run {run_id}) ---")
    print(f"    cmd: {' '.join(cmd)}")
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
    )
    try:
        p_psutil = psutil.Process(proc.pid)
    except psutil.NoSuchProcess:
        p_psutil = None
    peak_rss = 0
    samples = 0
    while True:
        if p_psutil is not None:
            peak_rss = max(peak_rss, measure_process_tree_rss(p_psutil))
            samples += 1
        rc = proc.poll()
        if rc is not None:
            break
        time.sleep(SAMPLING_INTERVAL_S)
    rc = proc.wait()
    stdout, stderr = proc.communicate()
    wall = time.perf_counter() - t0
    stderr_tail = (stderr or b"").decode("utf-8", errors="replace")[-400:]

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = f"{LOG_DIR}/profile_{method['name']}_{run_id}.log"
    with open(log_path, "wb") as f:
        f.write(b"$ " + " ".join(cmd).encode("utf-8") + b"\n")
        f.write(b"exit_code=" + str(rc).encode() + b"\n\n")
        f.write(b"--- stdout ---\n")
        f.write(stdout or b"")
        f.write(b"\n--- stderr ---\n")
        f.write(stderr or b"")

    if rc != 0:
        print(f"    ERROR exit={rc}: {stderr_tail}")
    return {
        "method": method["name"],
        "label": method["label"],
        "run_id": run_id,
        "wall_seconds": round(wall, 3),
        "peak_mib": round(peak_rss / 1024 / 1024, 2),
        "samples": samples,
        "exit_code": rc,
        "stderr_tail": stderr_tail,
        "stdout_bytes": len(stdout or b""),
        "log_path": log_path,
    }

def _summary(results: list[dict], methods: list[dict]) -> list[dict]:
    summary = []
    for method in methods:
        runs = [r for r in results if r["method"] == method["name"]]
        ok_runs = [r for r in runs if r["exit_code"] == 0]
        walls = [r["wall_seconds"] for r in ok_runs]
        peaks = [r["peak_mib"] for r in ok_runs]
        summary.append({
            "method": method["name"],
            "label": method["label"],
            "n_runs": len(runs),
            "n_ok": len(ok_runs),
            "wall_median_s": round(statistics.median(walls), 3) if walls else 0.0,
            "wall_min_s": round(min(walls), 3) if walls else 0.0,
            "wall_max_s": round(max(walls), 3) if walls else 0.0,
            "peak_median_mib": round(statistics.median(peaks), 2) if peaks else 0.0,
            "peak_min_mib": round(min(peaks), 2) if peaks else 0.0,
            "peak_max_mib": round(max(peaks), 2) if peaks else 0.0,
        })
    return summary

def run_all() -> dict:
    os.makedirs(LOCAL_OUT_DIR, exist_ok=True)
    results: list[dict] = []

    print("=== Warmup: each method once (excluded from report) ===")
    warmups = []
    for method in METHODS:
        w = run_once(method, 0)
        warmups.append(w)
        print(f"   warmup {method['name']}: wall={w['wall_seconds']}s, "
              f"peak={w['peak_mib']} MiB, exit={w['exit_code']}")

    print(f"\n=== Profiling: {N_RUNS} rounds × {len(METHODS)} methods (interleaved) ===")
    for round_id in range(1, N_RUNS + 1):
        order = METHODS[round_id % len(METHODS):] + METHODS[:round_id % len(METHODS)]
        for method in order:
            r = run_once(method, round_id)
            results.append(r)
            print(f"    -> {method['label']:<35} run {round_id}: "
                  f"wall={r['wall_seconds']:>6.3f}s  peak={r['peak_mib']:>7.2f} MiB  "
                  f"exit={r['exit_code']}")

    fields = ["method", "label", "run_id", "wall_seconds", "peak_mib", "samples",
              "exit_code", "log_path"]
    with open(f"{LOCAL_OUT_DIR}/profile.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({k: r[k] for k in fields})

    summary = _summary(results, METHODS)
    with open(f"{LOCAL_OUT_DIR}/summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["method", "label", "n_runs", "n_ok",
                                          "wall_median_s", "wall_min_s", "wall_max_s",
                                          "peak_median_mib", "peak_min_mib", "peak_max_mib"])
        w.writeheader()
        for r in summary:
            w.writerow(r)

    vm = psutil.virtual_memory()
    result = {
        "n_runs_per_method": N_RUNS,
        "sampling_interval_s": SAMPLING_INTERVAL_S,
        "results": results,
        "summary": summary,
        "warmups": warmups,
        "all_runs_ok": all(r["exit_code"] == 0 for r in results),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "cpu_count": os.cpu_count(),
            "total_memory_gib": round(vm.total / 2**30, 2),
            "available_memory_gib_at_end": round(vm.available / 2**30, 2),
        },
    }
    with open(f"{LOCAL_OUT_DIR}/profile.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return result

if __name__ == "__main__":
    res = run_all()
    print("\n=== Profile Summary ===")
    print(f"{'Method':<35} {'n_ok':>4} {'wall_med_s':>12} {'wall_min_s':>12} {'wall_max_s':>12} {'peak_med_MiB':>14} {'peak_max_MiB':>14}")
    print("-" * 110)
    for s in res["summary"]:
        print(f"{s['label']:<35} {s['n_ok']:>3}/{s['n_runs']} {s['wall_median_s']:>12.3f} "
              f"{s['wall_min_s']:>12.3f} {s['wall_max_s']:>12.3f} "
              f"{s['peak_median_mib']:>14.2f} {s['peak_max_mib']:>14.2f}")
    print(f"\nEnvironment: {res['environment']}")
    if not res["all_runs_ok"]:
        print("\n✗ Профилирование содержит упавшие запуски")
        sys.exit(1)
