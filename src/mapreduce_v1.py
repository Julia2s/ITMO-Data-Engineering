from __future__ import annotations

import io
import os
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    get_s3_client, VACANCIES_KEY, parse_skills, is_devops, iter_vacancy_rows,
    ReadStats, build_manifest, write_manifest, write_frequency_results,
    VARIANT_FILTER_MODE,
)

STACK_SIZES = (1, 2, 3)
OUTPUT_PREFIX = "results/mapreduce_v1"
LOCAL_OUT_DIR = "data/results_v1"
MANIFEST_DIR = "data/manifests"


def mapper_naive(rows: list[dict]) -> list[tuple[tuple, int]]:
    """Reference naive mapper: materialises every emitted (combo, 1) pair."""
    emitted: list[tuple[tuple, int]] = []
    for row in rows:
        if not is_devops(row):
            continue
        skills = parse_skills(row.get("key_skills", ""))
        if not skills:
            continue
        for k in STACK_SIZES:
            for combo in combinations(sorted(skills), k):
                emitted.append((combo, 1))
    return emitted


def reducer_naive(emissions: list[tuple[tuple, int]]) -> dict[int, Counter]:
    out: dict[int, Counter] = {k: Counter() for k in STACK_SIZES}
    for combo, _cnt in emissions:
        out[len(combo)][combo] += 1
    return out


def run() -> dict:
    """Naive baseline: one full pass over the object, all emissions in RAM.

    Compared with the original implementation this streams vacancies instead
    of keeping 229k dicts alive, so it fits on a laptop while still being
    deliberately memory-hungry (all 1M+ emissions are materialised).
    """
    cli = get_s3_client()
    t0 = time.perf_counter()

    reader_stats = ReadStats()
    emissions: list[tuple[tuple, int]] = []
    n_matched = 0
    n_with_skills = 0
    for row in iter_vacancy_rows(cli, reader_stats):
        if not is_devops(row):
            continue
        n_matched += 1
        skills = parse_skills(row.get("key_skills", ""))
        if not skills:
            continue
        n_with_skills += 1
        sorted_skills = sorted(skills)
        for k in STACK_SIZES:
            for combo in combinations(sorted_skills, k):
                emissions.append((combo, 1))
    t1 = time.perf_counter()

    counters = reducer_naive(emissions)
    t2 = time.perf_counter()

    written = write_frequency_results(cli, counters, OUTPUT_PREFIX, LOCAL_OUT_DIR)
    t3 = time.perf_counter()

    info = cli.head_object(VACANCIES_KEY)

    result = {
        "file_size_bytes": info.size if info else 0,
        "filter_mode": VARIANT_FILTER_MODE,
        "n_chunks": 1,
        "rows_total": reader_stats.lines_total,
        "rows_parsed": reader_stats.rows_parsed,
        "rows_matched": n_matched,
        "rows_with_skills": n_with_skills,
        "reader_stats": reader_stats.as_dict(),
        "emissions_total": len(emissions),
        "n_skills_1": written[1]["n_combinations"],
        "n_skills_2": written[2]["n_combinations"],
        "n_skills_3": written[3]["n_combinations"],
        "total_frequency": {k: written[k]["total_frequency"] for k in STACK_SIZES},
        "phase_time_read_map_s": round(t1 - t0, 3),
        "phase_time_reduce_s": round(t2 - t1, 3),
        "phase_time_write_s": round(t3 - t2, 3),
        "phase_time_total_s": round(t3 - t0, 3),
        "results": written,
    }
    manifest = build_manifest("mapreduce_v1", cli, {
        "counts": {
            "rows_total": result["rows_total"],
            "rows_matched": n_matched,
            "rows_with_skills": n_with_skills,
            "n_skills_1": result["n_skills_1"],
            "n_skills_2": result["n_skills_2"],
            "n_skills_3": result["n_skills_3"],
        },
        "timings": {
            "read_map_s": result["phase_time_read_map_s"],
            "reduce_s": result["phase_time_reduce_s"],
            "write_s": result["phase_time_write_s"],
            "total_s": result["phase_time_total_s"],
        },
    })
    local_manifest = write_manifest(cli, "mapreduce_v1", manifest, MANIFEST_DIR)
    result["manifest"] = local_manifest
    return result


if __name__ == "__main__":
    import json
    stats = run()
    print(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
