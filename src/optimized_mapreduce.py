from __future__ import annotations

import csv
import io
import json
import os
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    get_s3_client, VACANCIES_KEY, CURATED_KEY, parse_skills, is_devops,
    iter_vacancy_rows, ReadStats, build_manifest, write_manifest,
    write_frequency_results, VARIANT_FILTER_MODE,
)

STACK_SIZES = (1, 2, 3)
OUTPUT_PREFIX = "results/optimized_mapreduce"
LOCAL_OUT_DIR = "data/results_optimized"
MANIFEST_DIR = "data/manifests"


def prepare() -> dict:
    cli = get_s3_client()
    t0 = time.perf_counter()
    reader_stats = ReadStats()
    out_rows: list[dict] = []
    n_matched = 0
    for row in iter_vacancy_rows(cli, reader_stats):
        if not is_devops(row):
            continue
        n_matched += 1
        skills = parse_skills(row.get("key_skills", ""))
        if not skills:
            continue
        out_rows.append({
            "vacancy_id": row.get("vacancy_id", ""),
            "key_skills": ";".join(sorted(skills)),
        })

    if not out_rows:
        raise SystemExit(
            f"Curated-датасет пуст: ни одной DevOps-вакансии с навыками "
            f"(filter_mode={VARIANT_FILTER_MODE})"
        )

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["vacancy_id", "key_skills"], lineterminator="\n")
    w.writeheader()
    for r in out_rows:
        w.writerow(r)
    data = buf.getvalue().encode("utf-8")
    t1 = time.perf_counter()
    cli.put_object(CURATED_KEY, data, content_type="text/csv; charset=utf-8")
    local_path = "data/curated_devops_skills.csv"
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(data)
    info = cli.head_object(CURATED_KEY)
    t2 = time.perf_counter()

    result = {
        "action": "prepare",
        "rows": len(out_rows),
        "rows_matched": n_matched,
        "filter_mode": VARIANT_FILTER_MODE,
        "reader": reader_stats.as_dict(),
        "size_bytes": info.size if info else 0,
        "size_kib": round((info.size if info else 0) / 1024, 2),
        "s3_key": CURATED_KEY,
        "local_path": local_path,
        "phase_time_filter_s": round(t1 - t0, 3),
        "phase_time_put_s": round(t2 - t1, 3),
        "phase_time_total_s": round(t2 - t0, 3),
    }
    manifest = build_manifest("optimized_prepare", cli, {"counts": {"curated_rows": len(out_rows)},
                                                        "result": result})
    result["manifest"] = write_manifest(cli, "optimized_prepare", manifest, MANIFEST_DIR)
    return result


def run_worker() -> dict:
    cli = get_s3_client()
    t0 = time.perf_counter()
    info = cli.head_object(CURATED_KEY)
    if info is None:
        raise FileNotFoundError(
            f"S3-объект {CURATED_KEY} не найден. Сначала запустите: "
            "python optimized_mapreduce.py prepare"
        )
    file_size = info.size
    t1 = time.perf_counter()

    raw = cli.get_object(CURATED_KEY)
    text = raw.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    final_counters: dict[int, Counter] = {k: Counter() for k in STACK_SIZES}
    n_rows = 0
    for row in reader:
        n_rows += 1
        skills = parse_skills(row.get("key_skills", ""))
        if not skills:
            continue
        sorted_skills = sorted(skills)
        for k in STACK_SIZES:
            final_counters[k].update(combinations(sorted_skills, k))
    t2 = time.perf_counter()

    if n_rows == 0:
        raise SystemExit("Curated-датасет содержит 0 строк — бенчмарк был бы фиктивным")

    written = write_frequency_results(cli, final_counters, OUTPUT_PREFIX, LOCAL_OUT_DIR)
    t3 = time.perf_counter()

    result = {
        "action": "benchmark-worker",
        "filter_mode": VARIANT_FILTER_MODE,
        "curated_size_bytes": file_size,
        "rows_read": n_rows,
        "n_skills_1": written[1]["n_combinations"],
        "n_skills_2": written[2]["n_combinations"],
        "n_skills_3": written[3]["n_combinations"],
        "total_frequency": {k: written[k]["total_frequency"] for k in STACK_SIZES},
        "phase_time_stat_s": round(t1 - t0, 3),
        "phase_time_map_reduce_s": round(t2 - t1, 3),
        "phase_time_write_s": round(t3 - t2, 3),
        "phase_time_total_s": round(t3 - t0, 3),
        "results": written,
    }
    manifest = build_manifest("optimized_worker", cli, {
        "counts": {
            "rows_read": n_rows,
            "n_skills_1": result["n_skills_1"],
            "n_skills_2": result["n_skills_2"],
            "n_skills_3": result["n_skills_3"],
        },
        "curated_size_bytes": file_size,
    })
    result["manifest"] = write_manifest(cli, "optimized_worker", manifest, MANIFEST_DIR)
    return result


def verify() -> dict:
    cli = get_s3_client()
    if cli.head_object(CURATED_KEY) is None:
        raise SystemExit(f"Нет curated-объекта {CURATED_KEY}")

    raw_cur = cli.get_object(CURATED_KEY)
    text_cur = raw_cur.decode("utf-8", errors="replace")
    cur_skills_by_vid: dict[str, tuple[str, ...]] = {}
    for r in csv.DictReader(io.StringIO(text_cur)):
        cur_skills_by_vid[r.get("vacancy_id", "")] = tuple(
            sorted(parse_skills(r.get("key_skills", "")))
        )

    full_skills_by_vid: dict[str, tuple[str, ...]] = {}
    for r in iter_vacancy_rows(cli):
        if not is_devops(r):
            continue
        skills = parse_skills(r.get("key_skills", ""))
        if not skills:
            continue
        full_skills_by_vid[r.get("vacancy_id", "")] = tuple(sorted(skills))

    n_full = len(full_skills_by_vid)
    n_cur = len(cur_skills_by_vid)
    matching = sum(1 for vid, sk in cur_skills_by_vid.items()
                   if full_skills_by_vid.get(vid) == sk)
    mismatches = n_cur - matching
    missing_in_cur = sum(1 for vid in full_skills_by_vid if vid not in cur_skills_by_vid)

    ok = n_full > 0 and n_cur == n_full and matching == n_full and mismatches == 0
    return {
        "action": "verify",
        "filter_mode": VARIANT_FILTER_MODE,
        "full_devops_rows": n_full,
        "curated_rows": n_cur,
        "matching_rows": matching,
        "mismatches": mismatches,
        "missing_in_curated": missing_in_cur,
        "ok": ok,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("prepare", "benchmark-worker", "verify"):
        print("Usage:")
        print("  python optimized_mapreduce.py prepare           # creates curated/devops_skills.csv")
        print("  python optimized_mapreduce.py benchmark-worker  # runs MapReduce on curated")
        print("  python optimized_mapreduce.py verify            # verifies curated == raw filtered")
        sys.exit(1)
    action = sys.argv[1]
    if action == "prepare":
        print(json.dumps(prepare(), ensure_ascii=False, indent=2, default=str))
    elif action == "benchmark-worker":
        print(json.dumps(run_worker(), ensure_ascii=False, indent=2, default=str))
    elif action == "verify":
        result = verify()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if not result["ok"]:
            sys.exit(1)
