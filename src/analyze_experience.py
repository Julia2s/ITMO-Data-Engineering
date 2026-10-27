from __future__ import annotations

import csv
import io
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    get_s3_client, parse_skills, is_devops, salary_to_rub, iter_vacancy_rows,
    ReadStats, build_manifest, write_manifest, VARIANT_FILTER_MODE,
)

LOCAL_OUT_DIR = "data/results_experience"
OUTPUT_PREFIX = "results/experience"
MANIFEST_DIR = "data/manifests"

EXPERIENCE_ORDER = [
    "Нет опыта",
    "От 1 года до 3 лет",
    "От 3 до 6 лет",
    "Более 6 лет",
]

def _load_devops_with_salary(cli) -> tuple[list[dict], dict]:
    stats = ReadStats()
    out: list[dict] = []
    n_matched = 0
    for row in iter_vacancy_rows(cli, stats):
        if not is_devops(row):
            continue
        n_matched += 1
        rub = salary_to_rub(row)
        if rub is None or rub <= 0:
            continue
        out.append({
            "salary_rub": int(rub),
            "experience": (row.get("experience") or "").strip(),
            "skills": parse_skills(row.get("key_skills", "")),
            "area": row.get("area", ""),
            "schedule": row.get("schedule", ""),
        })
    return out, {
        "rows_matched": n_matched,
        "rows_with_convertible_salary": len(out),
        "filter_mode": VARIANT_FILTER_MODE,
        "reader": stats.as_dict(),
    }

def _quantile(data: list[float], q: float) -> float:
    if not data:
        return 0
    s = sorted(data)
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)

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
    rows, stats = _load_devops_with_salary(cli)
    if not rows:
        raise SystemExit(f"Нет DevOps-вакансий с зарплатой (filter_mode={VARIANT_FILTER_MODE})")

    by_exp: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        key = r["experience"] or "(не указан)"
        by_exp[key].append(r)

    ordered_exps = [e for e in EXPERIENCE_ORDER if e in by_exp]
    other_exps = sorted(e for e in by_exp if e not in EXPERIENCE_ORDER)
    all_exps = ordered_exps + other_exps

    summary = []
    for exp in all_exps:
        rs = by_exp[exp]
        salaries = [r["salary_rub"] for r in rs]
        n_skills_all = [len(r["skills"]) for r in rs if r["skills"]]
        summary.append({
            "experience": exp,
            "n_vacancies": len(rs),
            "n_with_skills": sum(1 for r in rs if r["skills"]),
            "median_salary_rub": int(statistics.median(salaries)) if salaries else 0,
            "p25_rub": int(_quantile(salaries, 0.25)) if salaries else 0,
            "p75_rub": int(_quantile(salaries, 0.75)) if salaries else 0,
            "mean_n_skills": round(statistics.mean(n_skills_all), 2) if n_skills_all else 0,
        })

    skill_freq_per_exp: dict[str, list] = {}
    for exp in all_exps:
        freq: dict[str, int] = defaultdict(int)
        for r in by_exp[exp]:
            for s in r["skills"]:
                freq[s] += 1
        skill_freq_per_exp[exp] = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:10]

    _write_csv(
        cli, "summary.csv",
        ["experience", "n_vacancies", "n_with_skills", "median_salary_rub",
         "p25_rub", "p75_rub", "mean_n_skills"],
        [[r[k] for k in ["experience", "n_vacancies", "n_with_skills",
                         "median_salary_rub", "p25_rub", "p75_rub", "mean_n_skills"]]
         for r in summary],
    )

    body = [[exp, s, n] for exp, top in skill_freq_per_exp.items() for s, n in top]
    _write_csv(cli, "top_skills_per_experience.csv", ["experience", "skill", "freq"], body)

    result = {
        "summary": summary,
        "skill_freq_per_exp": skill_freq_per_exp,
        "n_total_with_salary": len(rows),
        "stats": stats,
    }
    manifest = build_manifest("experience", cli, {"summary": summary, "stats": stats})
    result["manifest"] = write_manifest(cli, "experience", manifest, MANIFEST_DIR)
    return result

if __name__ == "__main__":
    res = run()
    print(f"DevOps вакансий с зарплатой: {res['n_total_with_salary']}")
    print(json.dumps(res["stats"], ensure_ascii=False))
    print("\n=== Зарплата по грейдам (опыт) ===")
    print(f"{'Опыт':<25} {'N':>6} {'Медиана':>11} {'P25':>11} {'P75':>11} {'#нав':>5}")
    print("-" * 75)
    for r in res["summary"]:
        print(f"{r['experience']:<25} {r['n_vacancies']:>6} "
              f"{r['median_salary_rub']:>10}₽ {r['p25_rub']:>10}₽ {r['p75_rub']:>10}₽ "
              f"{r['mean_n_skills']:>5}")
    print("\n=== Топ-5 навыков по грейдам ===")
    for exp, top in res["skill_freq_per_exp"].items():
        print(f"\n[{exp}]")
        for s, n in top[:5]:
            print(f"  {s:<30} {n:>5}")
