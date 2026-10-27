from __future__ import annotations

import csv
import io
import json
import os
import statistics
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    get_s3_client, parse_skills, is_devops, salary_to_rub, iter_vacancy_rows,
    ReadStats, build_manifest, write_manifest, VARIANT_FILTER_MODE,
)

LOCAL_OUT_DIR = "data/results_salary"
OUTPUT_PREFIX = "results/salary"
MANIFEST_DIR = "data/manifests"

MIN_VAC_PAIR   = 10
MIN_VAC_TRIPLE = 8
MIN_VAC_BASE   = 15

TOP_N = 10

def _load_devops(cli) -> tuple[list[dict], list[dict], dict]:
    """Return (all salary rows, salary rows with skills, stats)."""
    stats = ReadStats()
    all_salary: list[dict] = []
    with_skills: list[dict] = []
    n_matched = 0
    n_with_skills = 0
    currencies: dict[str, int] = defaultdict(int)

    for row in iter_vacancy_rows(cli, stats):
        if not is_devops(row):
            continue
        n_matched += 1
        skills = parse_skills(row.get("key_skills", ""))
        if skills:
            n_with_skills += 1
        if (row.get("salary_from") or "").strip() or (row.get("salary_to") or "").strip():
            currencies[(row.get("currency") or "").strip() or "(empty)"] += 1
        rub = salary_to_rub(row)
        if rub is None or rub <= 0:
            continue
        item = {
            "skills": sorted(skills),
            "salary_rub": int(rub),
            "area": row.get("area", ""),
            "experience": row.get("experience", ""),
            "gross": row.get("gross", ""),
        }
        all_salary.append(item)
        if skills:
            with_skills.append(item)

    stats_dict = {
        "rows_matched": n_matched,
        "rows_with_skills": n_with_skills,
        "rows_with_convertible_salary": len(all_salary),
        "rows_with_skills_and_salary": len(with_skills),
        "currencies_seen": dict(currencies),
        "filter_mode": VARIANT_FILTER_MODE,
        "reader": stats.as_dict(),
    }
    return all_salary, with_skills, stats_dict

def _find_base(combo: tuple[str, ...], freq_by_combo: dict, k: int) -> tuple:
    if k == 2:
        s1_freq = freq_by_combo.get((combo[0],), 0)
        s2_freq = freq_by_combo.get((combo[1],), 0)
        return (combo[0],) if s1_freq >= s2_freq else (combo[1],)
    if k == 3:
        candidates = [
            tuple(sorted((combo[0], combo[1]))),
            tuple(sorted((combo[0], combo[2]))),
            tuple(sorted((combo[1], combo[2]))),
        ]
        return max(candidates, key=lambda c: freq_by_combo.get(c, 0))
    return combo[:-1]

def _build_salary_index(rows: list[dict]) -> dict:
    index: dict[tuple, list[int]] = defaultdict(list)
    for r in rows:
        skills = r["skills"]
        salary = r["salary_rub"]
        for s in skills:
            index[(s,)].append(salary)
        if len(skills) >= 2:
            for combo in combinations(sorted(skills), 2):
                index[combo].append(salary)
        if len(skills) >= 3:
            for combo in combinations(sorted(skills), 3):
                index[combo].append(salary)
    return index

def _median_from_list(salaries: list[int]) -> float:
    if not salaries:
        return 0.0
    return float(statistics.median(salaries))

def _build_combos_seen(index: dict, k: int) -> list[tuple]:
    return [c for c in index.keys() if len(c) == k]

def analyze(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("no rows with skills and convertible salary")
    overall_median = statistics.median([r["salary_rub"] for r in rows])
    overall_n = len(rows)

    index = _build_salary_index(rows)

    freq_single = {c: len(sals) for c, sals in index.items() if len(c) == 1}
    freq_pair   = {c: len(sals) for c, sals in index.items() if len(c) == 2}

    pairs_seen   = _build_combos_seen(index, 2)
    triples_seen = _build_combos_seen(index, 3)

    pair_results: list[dict] = []
    for combo in pairs_seen:
        salaries = index[combo]
        n = len(salaries)
        if n < MIN_VAC_PAIR:
            continue
        med = _median_from_list(salaries)
        base = _find_base(combo, freq_single, 2)
        base_salaries = index.get(base, [])
        base_n = len(base_salaries)
        if base_n < MIN_VAC_BASE:
            continue
        base_med = _median_from_list(base_salaries)
        delta_rub = med - base_med if base_med else 0
        delta_pct = 100 * (med / base_med - 1) if base_med else 0
        pair_results.append({
            "combo": combo,
            "combo_median": int(med),
            "combo_n": n,
            "base": base,
            "base_median": int(base_med),
            "base_n": base_n,
            "delta_rub": int(delta_rub),
            "delta_pct": round(delta_pct, 1),
        })

    triple_results: list[dict] = []
    for combo in triples_seen:
        salaries = index[combo]
        n = len(salaries)
        if n < MIN_VAC_TRIPLE:
            continue
        med = _median_from_list(salaries)
        base = _find_base(combo, freq_pair, 3)
        base_salaries = index.get(base, [])
        base_n = len(base_salaries)
        if base_n < MIN_VAC_BASE:
            continue
        base_med = _median_from_list(base_salaries)
        delta_rub = med - base_med if base_med else 0
        delta_pct = 100 * (med / base_med - 1) if base_med else 0
        triple_results.append({
            "combo": combo,
            "combo_median": int(med),
            "combo_n": n,
            "base": base,
            "base_median": int(base_med),
            "base_n": base_n,
            "delta_rub": int(delta_rub),
            "delta_pct": round(delta_pct, 1),
        })

    def sort_key_up(r):
        return (-r["delta_rub"], -r["combo_n"])

    def sort_key_down(r):
        return (r["delta_rub"], -r["combo_n"])

    return {
        "overall_median": int(overall_median),
        "overall_n": overall_n,
        "pairs_up":   sorted(pair_results,   key=sort_key_up)[:TOP_N],
        "pairs_down": sorted(pair_results, key=sort_key_down)[:TOP_N],
        "triples_up":   sorted(triple_results, key=sort_key_up)[:TOP_N],
        "triples_down": sorted(triple_results, key=sort_key_down)[:TOP_N],
        "n_pairs_total": len(pair_results),
        "n_triples_total": len(triple_results),
    }

def _write_csv(cli, name: str, header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    data = buf.getvalue().encode("utf-8")
    local_path = f"{LOCAL_OUT_DIR}/{name}"
    os.makedirs(LOCAL_OUT_DIR, exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(data)
    cli.put_object(f"{OUTPUT_PREFIX}/{name}", data, content_type="text/csv; charset=utf-8")
    return local_path

def run() -> dict:
    os.makedirs(LOCAL_OUT_DIR, exist_ok=True)
    cli = get_s3_client()
    all_salary, rows, stats = _load_devops(cli)

    if not rows:
        raise SystemExit(
            "Нет DevOps-вакансий одновременно с навыками и конвертируемой зарплатой. "
            f"filter_mode={VARIANT_FILTER_MODE}, stats={json.dumps(stats, ensure_ascii=False)}"
        )

    result = analyze(rows)
    result["stats"] = stats
    result["overall_median_all_salary"] = (
        int(statistics.median([r["salary_rub"] for r in all_salary])) if all_salary else 0
    )
    result["overall_n_all_salary"] = len(all_salary)

    for kind in ["pairs_up", "pairs_down", "triples_up", "triples_down"]:
        items = result.get(kind, [])
        header = ["combo", "combo_median", "combo_n", "base",
                  "base_median", "base_n", "delta_rub", "delta_pct"]
        body = [[";".join(r["combo"]), r["combo_median"], r["combo_n"],
                 ";".join(r["base"]), r["base_median"], r["base_n"],
                 r["delta_rub"], r["delta_pct"]] for r in items]
        result[f"{kind}_local"] = _write_csv(cli, f"{kind}.csv", header, body)

    index = _build_salary_index(rows)
    overall_median = result["overall_median"]
    single_rows = []
    for combo, salaries in index.items():
        if len(combo) != 1 or not salaries:
            continue
        median = _median_from_list(salaries)
        single_rows.append({
            "skill": combo[0],
            "freq": len(salaries),
            "median": int(median),
            "delta_rub": int(median - overall_median),
            "delta_pct": round(100 * (median / overall_median - 1), 1) if overall_median else 0.0,
        })
    single_rows.sort(key=lambda r: -r["freq"])
    result["single_skills_count"] = len(single_rows)
    result["single_skills_local"] = _write_csv(
        cli, "single_skills.csv",
        ["skill", "freq", "median", "delta_rub", "delta_pct"],
        [[r["skill"], r["freq"], r["median"], r["delta_rub"], r["delta_pct"]]
         for r in single_rows],
    )

    final_rows = []
    for kind, items in [
        ("pair_up", result["pairs_up"]), ("pair_down", result["pairs_down"]),
        ("triple_up", result["triples_up"]), ("triple_down", result["triples_down"]),
    ]:
        for rank, r in enumerate(items, 1):
            final_rows.append([
                kind, rank, ";".join(r["combo"]), r["combo_n"], r["combo_median"],
                ";".join(r["base"]), r["base_median"], r["base_n"],
                r["delta_rub"], r["delta_pct"],
            ])
    result["final_table_local"] = _write_csv(
        cli, "final_table.csv",
        ["kind", "rank", "combo", "combo_n", "combo_median", "base", "base_median",
         "base_n", "delta_rub", "delta_pct"],
        final_rows,
    )

    summary = {
        "overall_median": result["overall_median"],
        "overall_n": result["overall_n"],
        "overall_median_all_salary": result["overall_median_all_salary"],
        "overall_n_all_salary": result["overall_n_all_salary"],
        "n_pairs_total": result["n_pairs_total"],
        "n_triples_total": result["n_triples_total"],
        "single_skills_count": result["single_skills_count"],
        "stats": stats,
        "thresholds": {
            "min_vac_pair": MIN_VAC_PAIR,
            "min_vac_triple": MIN_VAC_TRIPLE,
            "min_vac_base": MIN_VAC_BASE,
        },
    }
    result["summary_local"] = f"{LOCAL_OUT_DIR}/summary.json"
    with open(result["summary_local"], "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    manifest = build_manifest("salary", cli, {"summary": summary})
    result["manifest"] = write_manifest(cli, "salary", manifest, MANIFEST_DIR)
    return result

def _print_block(title: str, items: list[dict], sign: str = "") -> None:
    print(f"\n=== {title} ===")
    for r in items:
        c = ";".join(r["combo"])
        b = ";".join(r["base"])
        print(f"  {sign}{r['delta_rub']:>+8} ₽ ({r['delta_pct']:>+6}%)  {c:<45}  "
              f"med={r['combo_median']} (n={r['combo_n']})  base {b}={r['base_median']} (n={r['base_n']})")

if __name__ == "__main__":
    res = run()
    print(f"overall_median: {res['overall_median']} ₽ ({res['overall_n']} vacancies with skills+salary)")
    print(f"all salary rows (incl. no skills): {res['overall_n_all_salary']}, "
          f"median {res['overall_median_all_salary']} ₽")
    print(f"n_pairs_total: {res['n_pairs_total']}, n_triples_total: {res['n_triples_total']}")
    print(f"audit stats: {json.dumps(res['stats'], ensure_ascii=False)}")
    _print_block("TOP-10 PAIRS RAISE", res["pairs_up"])
    _print_block("TOP-10 PAIRS LOWER", res["pairs_down"])
    _print_block("TOP-10 TRIPLES RAISE", res["triples_up"])
    _print_block("TOP-10 TRIPLES LOWER", res["triples_down"])
