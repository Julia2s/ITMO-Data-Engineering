from __future__ import annotations

import csv
import io
import os
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    get_s3_client, parse_skills, is_devops, salary_to_rub, iter_vacancy_rows,
    is_devops_role, is_devops_name, ReadStats, build_manifest, write_manifest,
    VARIANT_ROLE, VARIANT_FILTER_MODE,
)

LOCAL_OUT_DIR = "data/eda"
OUTPUT_PREFIX = "results/eda"
MANIFEST_DIR = "data/manifests"

def _quantile(data: list[float], q: float) -> float:
    if not data:
        return 0
    s = sorted(data)
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)

def _fmt_rub(v: float) -> str:
    return f"{int(v):,} ₽".replace(",", " ")

def run() -> dict:
    os.makedirs(LOCAL_OUT_DIR, exist_ok=True)
    cli = get_s3_client()
    reader_stats = ReadStats()

    role_counter: Counter = Counter()
    area_counter: Counter = Counter()
    employer_counter: Counter = Counter()
    experience_counter: Counter = Counter()
    schedule_counter: Counter = Counter()
    sphere_counter: Counter = Counter()
    source_counter: Counter = Counter()
    status_counter: Counter = Counter()

    devops_area_counter: Counter = Counter()
    devops_employer_counter: Counter = Counter()
    devops_experience_counter: Counter = Counter()
    devops_schedule_counter: Counter = Counter()
    devops_status_counter: Counter = Counter()

    devops_skills_counter: Counter = Counter()
    devops_n_skills_dist: Counter = Counter()
    devops_skill_counts: list[int] = []
    devops_salaries: list[float] = []
    n_role_match = 0
    n_name_match = 0
    n_devops = 0
    n_devops_with_skills = 0

    for r in iter_vacancy_rows(cli, reader_stats):
        if r.get("role"):
            role_counter[r["role"].strip()] += 1
        if r.get("area"):
            area_counter[r["area"].strip()] += 1
        employer_key = (r.get("employer_id") or "").strip() or (r.get("employer_name") or "").strip()
        if employer_key:
            employer_counter[employer_key] += 1
        if r.get("experience"):
            experience_counter[r["experience"].strip()] += 1
        if r.get("schedule"):
            schedule_counter[r["schedule"].strip()] += 1
        if r.get("sphere"):
            sphere_counter[r["sphere"].strip()] += 1
        if r.get("source"):
            source_counter[r["source"].strip()] += 1
        if r.get("status"):
            status_counter[r["status"].strip()] += 1

        role_hit = is_devops_role(r)
        name_hit = is_devops_name(r)
        if role_hit:
            n_role_match += 1
        if name_hit:
            n_name_match += 1
        if not is_devops(r):
            continue

        n_devops += 1
        if r.get("area"):
            devops_area_counter[r["area"].strip()] += 1
        employer_key = (r.get("employer_id") or "").strip() or (r.get("employer_name") or "").strip()
        if employer_key:
            devops_employer_counter[employer_key] += 1
        if r.get("experience"):
            devops_experience_counter[r["experience"].strip()] += 1
        if r.get("schedule"):
            devops_schedule_counter[r["schedule"].strip()] += 1
        if r.get("status"):
            devops_status_counter[r["status"].strip()] += 1

        skills = parse_skills(r.get("key_skills", ""))
        devops_skill_counts.append(len(skills))
        if skills:
            n_devops_with_skills += 1
            devops_n_skills_dist[len(skills)] += 1
            for s in skills:
                devops_skills_counter[s] += 1

        rub = salary_to_rub(r)
        if rub and rub > 0:
            devops_salaries.append(rub)

    salary_overall_median = statistics.median(devops_salaries) if devops_salaries else 0
    salary_p25 = _quantile(devops_salaries, 0.25) if devops_salaries else 0
    salary_p75 = _quantile(devops_salaries, 0.75) if devops_salaries else 0
    salary_p10 = _quantile(devops_salaries, 0.10) if devops_salaries else 0
    salary_p90 = _quantile(devops_salaries, 0.90) if devops_salaries else 0

    summary = {
        "n_total_rows": reader_stats.rows_parsed,
        "n_distinct_roles": len(role_counter),
        "n_distinct_areas": len(area_counter),
        "n_distinct_employers": len(employer_counter),
        "n_devops_role_match": n_role_match,
        "n_devops_name_match": n_name_match,
        "n_devops_total": n_devops,
        "filter_mode": VARIANT_FILTER_MODE,
        "devops_with_salary": len(devops_salaries),
        "devops_with_skills": n_devops_with_skills,
        "salary_median_rub": int(salary_overall_median),
        "salary_p25_rub": int(salary_p25),
        "salary_p75_rub": int(salary_p75),
        "salary_p10_rub": int(salary_p10),
        "salary_p90_rub": int(salary_p90),
        "devops_unique_skills": len(devops_skills_counter),
        "devops_median_skills_per_vacancy": statistics.median(devops_skill_counts)
        if devops_skill_counts else 0,
        "reader": reader_stats.as_dict(),
    }

    top_roles = role_counter.most_common(20)
    top_areas = area_counter.most_common(15)
    top_employers_all = employer_counter.most_common(15)
    top_employers = devops_employer_counter.most_common(15)
    top_experiences = devops_experience_counter.most_common(10)
    top_schedules = devops_schedule_counter.most_common(10)
    top_status = devops_status_counter.most_common(10)
    top_spheres = [(s, n) for s, n in sphere_counter.most_common(10) if s]
    top_sources = source_counter.most_common(10)
    top_devops_areas = devops_area_counter.most_common(15)
    top_devops_skills = devops_skills_counter.most_common(30)
    skills_count_dist = sorted(devops_n_skills_dist.items())

    def write_csv(name: str, header: list[str], rows: list[list]) -> str:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(header)
        for row in rows:
            w.writerow(row)
        data = buf.getvalue().encode("utf-8")
        local = f"{LOCAL_OUT_DIR}/{name}"
        with open(local, "wb") as f:
            f.write(data)
        cli.put_object(f"{OUTPUT_PREFIX}/{name}", data, content_type="text/csv; charset=utf-8")
        return local

    write_csv("top_roles.csv", ["role", "count"], top_roles)
    write_csv("top_areas.csv", ["area", "count"], top_areas)
    write_csv("top_employers.csv", ["employer_id", "count"], top_employers)
    write_csv("top_employers_all.csv", ["employer_id", "count"], top_employers_all)
    write_csv("top_experiences.csv", ["experience", "count"], top_experiences)
    write_csv("top_schedules.csv", ["schedule", "count"], top_schedules)
    write_csv("top_spheres.csv", ["sphere", "count"], top_spheres)
    write_csv("top_sources.csv", ["source", "count"], top_sources)
    write_csv("top_status.csv", ["status", "count"], top_status)
    write_csv("top_devops_areas.csv", ["area", "count"], top_devops_areas)
    write_csv("top_devops_skills.csv", ["skill", "count"], top_devops_skills)
    write_csv("skills_count_distribution.csv",
              ["n_skills_in_vacancy", "n_vacancies"], skills_count_dist)
    write_csv("summary.csv", ["metric", "value"],
              [[k, str(v)] for k, v in summary.items()])

    salary_buckets = Counter()
    for s in devops_salaries:
        bucket = int(s // 50000) * 50
        salary_buckets[bucket] += 1
    salary_hist = sorted(salary_buckets.items())
    write_csv("salary_histogram.csv", ["bucket_k_rub", "n_vacancies"], salary_hist)

    result = {
        "summary": summary,
        "top_roles": top_roles,
        "top_areas": top_areas,
        "top_employers": top_employers,
        "top_employers_all": top_employers_all,
        "top_devops_areas": top_devops_areas,
        "top_experiences": top_experiences,
        "top_schedules": top_schedules,
        "top_spheres": top_spheres,
        "top_devops_skills": top_devops_skills,
        "skills_count_distribution": skills_count_dist,
        "salary_histogram": salary_hist,
    }
    manifest = build_manifest("eda", cli, {"summary": summary})
    result["manifest"] = write_manifest(cli, "eda", manifest, MANIFEST_DIR)
    return result

if __name__ == "__main__":
    res = run()
    s = res["summary"]
    print("=" * 70)
    print("EXPLORATORY DATA ANALYSIS — it_vacancies_2024.csv")
    print("=" * 70)
    print(f"\nВсего строк в датасете:        {s['n_total_rows']:,}".replace(",", " "))
    print(f"Уникальных ролей:              {s['n_distinct_roles']}")
    print(f"Уникальных городов (area):     {s['n_distinct_areas']}")
    print(f"Уникальных работодателей:      {s['n_distinct_employers']}")
    print("\n--- ВАРИАНТ DevOps ---")
    print(f"Совпадение по role=='{VARIANT_ROLE}': {s['n_devops_role_match']}")
    print(f"Совпадение по name keywords:   {s['n_devops_name_match']}")
    print(f"Всего DevOps-вакансий:         {s['n_devops_total']:,}".replace(",", " "))
    print(f"Режим фильтра:                 {s['filter_mode']}")
    print(f"DevOps с навыками:             {s['devops_with_skills']}")
    print(f"DevOps с зарплатой:            {s['devops_with_salary']}")
    print("\n--- ЗАРПЛАТА (RUB, net после нормализации) ---")
    print(f"P10:    {_fmt_rub(s['salary_p10_rub'])}")
    print(f"P25:    {_fmt_rub(s['salary_p25_rub'])}")
    print(f"Median: {_fmt_rub(s['salary_median_rub'])}")
    print(f"P75:    {_fmt_rub(s['salary_p75_rub'])}")
    print(f"P90:    {_fmt_rub(s['salary_p90_rub'])}")
    print("\n--- НАВЫКИ ---")
    print(f"Уникальных навыков в DevOps-выборке: {s['devops_unique_skills']}")
    print(f"Медиана числа навыков на вакансию:  {s['devops_median_skills_per_vacancy']}")

    print("\n=== Топ-10 ролей в датасете ===")
    for role, n in res["top_roles"][:10]:
        marker = " ✓" if role == VARIANT_ROLE else ""
        print(f"  {role:<35} {n:>6}{marker}")

    print("\n=== Топ-10 городов (area) ===")
    for area, n in res["top_areas"][:10]:
        print(f"  {area:<30} {n:>6}")

    print("\n=== Топ-10 работодателей DevOps-вакансий (по employer_id) ===")
    for e, n in res["top_employers"][:10]:
        print(f"  {e[:35]:<35} {n:>6}")

    print("\n=== Распределение числа навыков на вакансию ===")
    for n_skills, n_vac in res["skills_count_distribution"][:15]:
        bar = "█" * min(n_vac // 50, 40)
        print(f"  {n_skills:>2} навыков: {n_vac:>5}  {bar}")

    print("\n=== Гистограмма зарплат (бакеты по 50k ₽) ===")
    for bucket, n_vac in res["salary_histogram"]:
        if n_vac < 5:
            continue
        bar = "█" * min(n_vac // 5, 40)
        print(f"  {bucket:>4}-{bucket+50:<4}k ₽: {n_vac:>5}  {bar}")

    print("\n=== Топ-15 навыков DevOps ===")
    for skill, n in res["top_devops_skills"][:15]:
        print(f"  {skill:<35} {n:>5}")

    print("\n=== Срез по опыту ===")
    for exp, n in res["top_experiences"]:
        print(f"  {exp:<35} {n:>6}")

    print(f"\nВсе результаты сохранены в data/eda/ и s3://{OUTPUT_PREFIX}/")
