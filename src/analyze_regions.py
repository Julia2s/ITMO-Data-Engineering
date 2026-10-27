from __future__ import annotations

import csv
import io
import json
import os
import statistics
import sys
import unicodedata
from collections import Counter
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    get_s3_client, parse_skills, is_devops, salary_to_rub, iter_vacancy_rows,
    ReadStats, build_manifest, write_manifest, VARIANT_FILTER_MODE,
)

REGIONS_ENV = os.environ.get("REGIONS", "")
REGIONS = ([r.strip() for r in REGIONS_ENV.split(",") if r.strip()]
           if REGIONS_ENV else ["Москва", "Санкт-Петербург", "Новосибирск"])
REMOTE_ALIASES = {"Удалённая работа", "Удаленная работа", "удалёнка", "удаленка", "remote"}
TOP_K = 5

LOCAL_OUT_DIR = "data/results_regions"
OUTPUT_PREFIX = "results/regions"
MANIFEST_DIR = "data/manifests"

def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", (text or "").lower()).replace("ё", "е")

def is_remote(row: dict) -> bool:
    schedule = _norm(row.get("schedule", ""))
    return "удален" in schedule or "remote" in schedule

def is_remote_region(region: str) -> bool:
    return region.strip() in REMOTE_ALIASES or "удален" in _norm(region)

def _load_devops(cli) -> tuple[list[dict], dict]:
    stats = ReadStats()
    rows: list[dict] = []
    n_matched = 0
    for row in iter_vacancy_rows(cli, stats):
        if not is_devops(row):
            continue
        n_matched += 1
        rub = salary_to_rub(row)
        rows.append({
            "skills": sorted(parse_skills(row.get("key_skills", ""))),
            "salary_rub": rub if rub and rub > 0 else None,
            "area": (row.get("area") or "").strip(),
            "schedule": (row.get("schedule") or "").strip(),
            "experience": (row.get("experience") or "").strip(),
            "employer_name": (row.get("employer_name") or "").strip(),
            "remote": is_remote(row),
        })
    return rows, {
        "rows_matched": n_matched,
        "rows_loaded": len(rows),
        "filter_mode": VARIANT_FILTER_MODE,
        "reader": stats.as_dict(),
    }

def _pct(value: float, total: float) -> float:
    if not total:
        return 0.0
    return round(100 * value / total, 1)

def _quantile(data: list[float], q: float) -> float:
    if not data:
        return 0
    s = sorted(data)
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)

def _build_skill_freq(rows: list[dict]) -> dict[int, Counter]:
    out: dict[int, Counter] = {1: Counter(), 2: Counter(), 3: Counter()}
    for r in rows:
        skills = r["skills"]
        for s in skills:
            out[1][(s,)] += 1
        if len(skills) >= 2:
            for c in combinations(sorted(skills), 2):
                out[2][c] += 1
        if len(skills) >= 3:
            for c in combinations(sorted(skills), 3):
                out[3][c] += 1
    return out

def analyze_one_region(rows: list[dict], global_freq: Counter, global_n_skills: int) -> dict:
    n_total = len(rows)
    skill_rows = [r for r in rows if r["skills"]]
    n_with_skills = len(skill_rows)
    salary_values = [int(r["salary_rub"]) for r in rows if r["salary_rub"] and r["salary_rub"] > 0]
    n_with_salary = len(salary_values)

    median = int(statistics.median(salary_values)) if salary_values else 0
    p25 = int(_quantile(salary_values, 0.25)) if salary_values else 0
    p75 = int(_quantile(salary_values, 0.75)) if salary_values else 0
    mean_n_skills = (
        sum(len(r["skills"]) for r in skill_rows) / n_with_skills if n_with_skills else 0
    )

    local_freq = _build_skill_freq(skill_rows)

    tops: dict[int, list] = {}
    for k in (1, 2, 3):
        items_sorted = sorted(local_freq[k].items(), key=lambda kv: (-kv[1], kv[0]))
        tops[k] = [
            {"combo": ";".join(combo), "freq": freq, "pct": _pct(freq, n_with_skills)}
            for combo, freq in items_sorted[:TOP_K]
        ]

    demand_indexes: dict[str, float] = {}
    for combo, freq in local_freq[1].items():
        skill = combo[0]
        region_share = freq / n_with_skills if n_with_skills else 0
        global_share = global_freq.get(combo, 0) / global_n_skills if global_n_skills else 0
        if global_share > 0 and freq >= 10:
            demand_indexes[skill] = round(region_share / global_share, 2)
    demand_indexes_sorted = sorted(demand_indexes.items(), key=lambda kv: -kv[1])[:5]

    return {
        "n_total": n_total,
        "n_with_skills": n_with_skills,
        "n_with_salary": n_with_salary,
        "pct_with_salary": _pct(n_with_salary, n_total),
        "median_salary_rub": median,
        "p25_rub": p25,
        "p75_rub": p75,
        "mean_n_skills": round(mean_n_skills, 2),
        "top_skills": tops[1],
        "top_pairs": tops[2],
        "top_triples": tops[3],
        "top_demand_index": [{"skill": s, "index": idx} for s, idx in demand_indexes_sorted],
    }

def _select(rows: list[dict], region: str) -> list[dict]:
    if is_remote_region(region):
        return [r for r in rows if r["remote"]]
    return [r for r in rows if r["area"] == region]

def _write_csv(cli, name: str, header: list[str], body: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in body:
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
    rows, stats = _load_devops(cli)
    if not rows:
        raise SystemExit(f"Нет DevOps-вакансий (filter_mode={VARIANT_FILTER_MODE})")

    skill_rows = [r for r in rows if r["skills"]]
    global_freq: Counter = Counter()
    for r in skill_rows:
        for s in r["skills"]:
            global_freq[(s,)] += 1
    global_n_skills = len(skill_rows)

    area_counter = Counter(r["area"] for r in rows if r["area"])
    schedule_counter = Counter(r["schedule"] for r in rows if r["schedule"])
    top_areas = area_counter.most_common(10)
    top_schedules = schedule_counter.most_common(5)

    by_region: dict[str, dict] = {}
    for region in REGIONS:
        by_region[region] = analyze_one_region(_select(rows, region), global_freq, global_n_skills)

    remote_key = "Удалённая работа"
    remote_slice = analyze_one_region(_select(rows, remote_key), global_freq, global_n_skills)

    summary_rows = []
    for region, r in by_region.items():
        summary_rows.append({
            "region": region,
            "n_total": r["n_total"],
            "n_with_skills": r["n_with_skills"],
            "n_with_salary": r["n_with_salary"],
            "pct_with_salary": r["pct_with_salary"],
            "median_salary_rub": r["median_salary_rub"],
            "p25_rub": r["p25_rub"],
            "p75_rub": r["p75_rub"],
            "mean_n_skills": r["mean_n_skills"],
            "top_skill": r["top_skills"][0]["combo"] if r["top_skills"] else "",
            "top_pair": r["top_pairs"][0]["combo"] if r["top_pairs"] else "",
            "top_triple": r["top_triples"][0]["combo"] if r["top_triples"] else "",
            "top_demand_skill": r["top_demand_index"][0]["skill"] if r["top_demand_index"] else "",
            "top_demand_index": r["top_demand_index"][0]["index"] if r["top_demand_index"] else 0,
        })

    _write_csv(cli, "overview.csv", list(summary_rows[0].keys()),
               [[r[k] for k in summary_rows[0]] for r in summary_rows])

    remote_row = {
        "region": remote_key,
        "n_total": remote_slice["n_total"],
        "n_with_skills": remote_slice["n_with_skills"],
        "n_with_salary": remote_slice["n_with_salary"],
        "pct_with_salary": remote_slice["pct_with_salary"],
        "median_salary_rub": remote_slice["median_salary_rub"],
        "p25_rub": remote_slice["p25_rub"],
        "p75_rub": remote_slice["p75_rub"],
        "mean_n_skills": remote_slice["mean_n_skills"],
        "top_skill": remote_slice["top_skills"][0]["combo"] if remote_slice["top_skills"] else "",
        "top_pair": remote_slice["top_pairs"][0]["combo"] if remote_slice["top_pairs"] else "",
        "top_triple": remote_slice["top_triples"][0]["combo"] if remote_slice["top_triples"] else "",
        "top_demand_skill": remote_slice["top_demand_index"][0]["skill"] if remote_slice["top_demand_index"] else "",
        "top_demand_index": remote_slice["top_demand_index"][0]["index"] if remote_slice["top_demand_index"] else 0,
    }
    _write_csv(cli, "remote_overview.csv", list(remote_row.keys()),
               [[remote_row[k] for k in remote_row]])

    for region, r in by_region.items():
        safe = region.replace(" ", "_")
        for k, kind in [(1, "skills"), (2, "pairs"), (3, "triples")]:
            _write_csv(cli, f"{safe}_{kind}.csv", ["combo", "freq", "pct"],
                       [[it["combo"], it["freq"], it["pct"]] for it in r[f"top_{kind}"]])
        _write_csv(cli, f"{safe}_demand.csv", ["skill", "index"],
                   [[it["skill"], it["index"]] for it in r["top_demand_index"]])

    for k, kind in [(1, "skills"), (2, "pairs"), (3, "triples")]:
        _write_csv(cli, f"Удалённая_работа_{kind}.csv", ["combo", "freq", "pct"],
                   [[it["combo"], it["freq"], it["pct"]] for it in remote_slice[f"top_{kind}"]])

    result = {
        "regions": by_region,
        "summary": summary_rows,
        "remote": remote_slice,
        "remote_overview": remote_row,
        "n_devops_total": len(rows),
        "n_devops_with_skills": global_n_skills,
        "top_areas": top_areas,
        "top_schedules": top_schedules,
        "stats": stats,
    }
    manifest = build_manifest("regions", cli, {
        "regions": REGIONS,
        "stats": stats,
        "summary": summary_rows,
        "remote_overview": remote_row,
    })
    result["manifest"] = write_manifest(cli, "regions", manifest, MANIFEST_DIR)
    return result

if __name__ == "__main__":
    res = run()
    print(f"\nDevOps вакансий всего: {res['n_devops_total']} "
          f"(с навыками: {res['n_devops_with_skills']})")
    print("\n=== Топ-10 регионов (поле area) ===")
    for area, n in res.get("top_areas", []):
        marker = " ✓" if area in REGIONS else ""
        print(f"  {area:<30} {n:>5}{marker}")
    print("\n=== Топ-5 типов занятости (поле schedule) ===")
    for sch, n in res.get("top_schedules", []):
        print(f"  {sch:<30} {n:>5}")
    print(f"\nАнализируемые регионы (REGIONS): {REGIONS}")
    print("  (изменить: $env:REGIONS='Москва,Санкт-Петербург,Екатеринбург')")
    print("\n=== Сводка по регионам ===")
    print(f"{'Регион':<25} {'N':>6} {'N нав':>6} {'N ЗП':>6} {'Медиана':>9} {'P25':>9} {'P75':>9} {'#нав':>5}")
    print("-" * 90)
    for r in res["summary"]:
        print(f"{r['region']:<25} {r['n_total']:>6} {r['n_with_skills']:>6} "
              f"{r['n_with_salary']:>6} {r['median_salary_rub']:>8}₽ {r['p25_rub']:>8}₽ "
              f"{r['p75_rub']:>8}₽ {r['mean_n_skills']:>5}")
    print("\n=== Удалённая работа (отдельный срез) ===")
    r = res["remote_overview"]
    print(f"  n={r['n_total']}  skills={r['n_with_skills']}  salary={r['n_with_salary']}  "
          f"median={r['median_salary_rub']}₽  top={r['top_skill']}")
    print("\n=== Топ-5 навыков по регионам ===")
    for region, r in res["regions"].items():
        print(f"\n[{region}]  median={r['median_salary_rub']}₽  n={r['n_total']}  "
              f"mean_skills={r['mean_n_skills']}")
        for s in r["top_skills"]:
            print(f"  {s['combo']:<25} {s['freq']:>5} вакансий  ({s['pct']}%)")
