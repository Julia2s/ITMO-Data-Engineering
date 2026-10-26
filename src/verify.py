from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SOURCES = {
    "v1":     "data/results_v1",
    "v2":     "data/results_v2",
    "duckdb": "data/results_duckdb",
}
MANIFESTS = {
    "v1":     "data/manifests/mapreduce_v1.json",
    "v2":     "data/manifests/mapreduce_v2.json",
    "duckdb": "data/manifests/duckdb.json",
}
STACK_SIZES = (1, 2, 3)


def load_canonical(path: str) -> list[tuple[tuple, int]]:
    rows: list[tuple[tuple, int]] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for r in reader:
            if not r or len(r) < 2:
                continue
            combo = tuple(r[0].split(";"))
            freq = int(r[1])
            rows.append((combo, freq))
    rows.sort(key=lambda kv: (len(kv[0]), -kv[1], kv[0]))
    return rows


def _first_diff(a: list[tuple], b: list[tuple]) -> dict | None:
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return {"position": i, "a": a[i], "b": b[i]}
    if len(a) != len(b):
        return {"position": min(len(a), len(b)), "a": None, "b": None}
    return None


def compare_pair(a_name: str, a_path: str, b_name: str, b_path: str) -> dict:
    a = load_canonical(a_path)
    b = load_canonical(b_path)
    sum_a = sum(f for _, f in a)
    sum_b = sum(f for _, f in b)
    match = bool(a) and (a == b)
    return {
        "a_name": a_name,
        "b_name": b_name,
        "a_rows": len(a),
        "b_rows": len(b),
        "a_sum": sum_a,
        "b_sum": sum_b,
        "match": match,
        "empty": not a or not b,
        "diff_first": None if match else _first_diff(a, b),
    }


def load_manifest(name: str) -> dict | None:
    path = Path(MANIFESTS[name])
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def manifest_checks() -> dict:
    """Cross-check result-file sizes and matched-row counts against manifests."""
    issues: list[str] = []
    counts: dict[str, dict] = {}
    modes: set[str] = set()
    for name in SOURCES:
        m = load_manifest(name)
        if m is None:
            issues.append(f"{name}: manifest missing")
            continue
        c = (m.get("counts") or {})
        counts[name] = c
        modes.add(str(m.get("filter_mode")))
        for k in STACK_SIZES:
            path = Path(SOURCES[name]) / f"skills_{k}.csv"
            if not path.exists():
                issues.append(f"{name}: {path} missing")
                continue
            rows = load_canonical(str(path))
            if len(rows) != int(c.get(f"n_skills_{k}", -1)):
                issues.append(
                    f"{name}: k={k} file rows {len(rows)} != manifest {c.get(f'n_skills_{k}')}"
                )
    if len(modes) > 1:
        issues.append(f"filter modes differ across methods: {sorted(modes)}")
    matched = {name: c.get("rows_matched") for name, c in counts.items()}
    if len({v for v in matched.values() if v is not None}) > 1:
        issues.append(f"rows_matched differ across methods: {matched}")
    return {
        "ok": not issues,
        "issues": issues,
        "counts": counts,
        "filter_modes": sorted(m for m in modes if m),
        "rows_matched": matched,
    }


def run() -> dict:
    summary = {"comparisons": [], "all_match": True, "manifest_checks": manifest_checks()}
    if not summary["manifest_checks"]["ok"]:
        summary["all_match"] = False

    for k in STACK_SIZES:
        for left, right in [("v1", "v2"), ("v1", "duckdb"), ("v2", "duckdb")]:
            a_path = f"{SOURCES[left]}/skills_{k}.csv"
            b_path = f"{SOURCES[right]}/skills_{k}.csv"
            try:
                r = compare_pair(left, a_path, right, b_path)
            except FileNotFoundError as e:
                r = {"a_name": left, "b_name": right, "match": False,
                     "empty": True, "error": str(e)}
            r["stack_size"] = k
            summary["comparisons"].append(r)
            if not r["match"]:
                summary["all_match"] = False

    # Cross-check total frequency consistency across k for the same source.
    for name, directory in SOURCES.items():
        try:
            sums = {
                k: sum(f for _, f in load_canonical(f"{directory}/skills_{k}.csv"))
                for k in STACK_SIZES
            }
        except FileNotFoundError:
            continue
        summary.setdefault("total_frequency", {})[name] = sums
    return summary


if __name__ == "__main__":
    res = run()
    print("=== Verification summary ===")
    print(f"all_match: {res['all_match']}")
    print()
    print(f"{'stack':<6} {'left':<8} {'right':<8} {'rows_a':>9} {'rows_b':>9} {'sum_a':>9} {'sum_b':>9}  match")
    print("-" * 75)
    for c in res["comparisons"]:
        print(f"{c['stack_size']:<6} {c['a_name']:<8} {c['b_name']:<8} "
              f"{c.get('a_rows','-'):>9} {c.get('b_rows','-'):>9} "
              f"{c.get('a_sum','-'):>9} {c.get('b_sum','-'):>9}  {c['match']}")
        if not c["match"] and c.get("diff_first"):
            print(f"   first diff: {c['diff_first']}")
        if c.get("empty"):
            print("   empty result set: results were not produced")
    mc = res["manifest_checks"]
    print("\n=== Manifest checks ===")
    print(f"filter modes: {mc['filter_modes']}")
    print(f"rows matched: {mc['rows_matched']}")
    if mc["issues"]:
        for issue in mc["issues"]:
            print(f"  ✗ {issue}")
    else:
        print("  ✓ manifests consistent")
    print()
    if res["all_match"]:
        print("✓ ВСЕ РЕЗУЛЬТАТЫ СОВПАЛИ (v1 == v2 == duckdb)")
    else:
        print("✗ ОБНАРУЖЕНЫ РАСХОЖДЕНИЯ")
        sys.exit(1)
