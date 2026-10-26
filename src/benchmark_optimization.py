from __future__ import annotations

import csv
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
N_RUNS = 3
SAMPLING_INTERVAL_S = 0.02

RESULT_DIRS = {"original": "data/results_v2", "optimized": "data/results_optimized"}

METHODS = [
    {"name": "original",  "label": "MapReduce v2 (raw CSV)",
     "script": "mapreduce_v2.py"},
    {"name": "optimized", "label": "MapReduce v2 (curated CSV)",
     "script": "optimized_mapreduce.py", "args": ["benchmark-worker"]},
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
    cmd = [sys.executable, str(script_path)] + method.get("args", [])
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
    }


def load_counts(directory: str) -> dict[int, tuple[int, int]] | None:
    path_dir = Path(directory)
    if not path_dir.exists():
        return None
    out: dict[int, tuple[int, int]] = {}
    for k in (1, 2, 3):
        path = path_dir / f"skills_{k}.csv"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            rows = [(r[0], int(r[1])) for r in reader if r and len(r) >= 2]
        out[k] = (len(rows), sum(freq for _, freq in rows))
    return out


def compare_outputs() -> dict:
    original = load_counts(RESULT_DIRS["original"])
    optimized = load_counts(RESULT_DIRS["optimized"])
    if original is None or optimized is None:
        return {"ok": False, "reason": "result files missing"}
    diffs = {}
    for k in (1, 2, 3):
        if original[k] != optimized[k]:
            diffs[k] = {"original": original[k], "optimized": optimized[k]}
    nonempty = all(v[0] > 0 and v[1] > 0 for v in original.values())
    return {
        "ok": nonempty and not diffs,
        "nonempty": nonempty,
        "original": {k: {"rows": v[0], "sum": v[1]} for k, v in original.items()},
        "optimized": {k: {"rows": v[0], "sum": v[1]} for k, v in optimized.items()},
        "diffs": diffs,
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

    print(f"\n=== Benchmark optimization: {N_RUNS} rounds × {len(METHODS)} methods (interleaved) ===")
    for round_id in range(1, N_RUNS + 1):
        order = METHODS[round_id % len(METHODS):] + METHODS[:round_id % len(METHODS)]
        for method in order:
            r = run_once(method, round_id)
            results.append(r)
            print(f"    -> {method['label']:<40} run {round_id}: "
                  f"wall={r['wall_seconds']:>6.3f}s  peak={r['peak_mib']:>7.2f} MiB  "
                  f"exit={r['exit_code']}")

    with open(f"{LOCAL_OUT_DIR}/optimization.csv", "w", newline="", encoding="utf-8") as f:
        fields = ["method", "label", "run_id", "wall_seconds", "peak_mib", "samples", "exit_code"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({k: r[k] for k in fields})

    summary = _summary(results, METHODS)
    with open(f"{LOCAL_OUT_DIR}/optimization_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["method", "label", "n_runs", "n_ok",
                                          "wall_median_s", "wall_min_s", "wall_max_s",
                                          "peak_median_mib", "peak_min_mib", "peak_max_mib"])
        w.writeheader()
        for r in summary:
            w.writerow(r)

    comparison = compare_outputs()
    speedup = None
    mem_savings = None
    if len(summary) == 2 and summary[1]["wall_median_s"] > 0:
        speedup = round(summary[0]["wall_median_s"] / summary[1]["wall_median_s"], 2)
    if len(summary) == 2 and summary[1]["peak_median_mib"] > 0:
        mem_savings = round(summary[0]["peak_median_mib"] / summary[1]["peak_median_mib"], 2)

    return {
        "n_runs_per_method": N_RUNS,
        "results": results,
        "summary": summary,
        "warmups": warmups,
        "comparison": comparison,
        "speedup": speedup,
        "memory_savings": mem_savings,
        "all_runs_ok": all(r["exit_code"] == 0 for r in results),
    }


if __name__ == "__main__":
    res = run_all()
    print("\n=== Optimization Benchmark Summary ===")
    print(f"{'Method':<40} {'n_ok':>4} {'wall_med_s':>12} {'wall_min_s':>12} {'wall_max_s':>12} {'peak_med_MiB':>14}")
    print("-" * 100)
    for s in res["summary"]:
        print(f"{s['label']:<40} {s['n_ok']:>3}/{s['n_runs']} {s['wall_median_s']:>12.3f} "
              f"{s['wall_min_s']:>12.3f} {s['wall_max_s']:>12.3f} {s['peak_median_mib']:>14.2f}")
    c = res["comparison"]
    print(f"\nOutputs identical (raw vs curated): {c['ok']}")
    if c.get("diffs"):
        print(f"  diffs: {c['diffs']}")
    if res["speedup"] is not None:
        print(f"Speedup:  {res['speedup']:.2f}× faster (curated vs raw)")
    if res["memory_savings"] is not None:
        print(f"Memory:   {res['memory_savings']:.2f}× less (curated vs raw)")
    if not (res["all_runs_ok"] and c["ok"]):
        print("\n✗ Бенчмарк некорректен: есть упавшие запуски или расхождение результатов")
        sys.exit(1)
