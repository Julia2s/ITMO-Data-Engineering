from __future__ import annotations

import csv
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 150
plt.rcParams["savefig.dpi"] = 150

C_BG = "#FFFFFF"
C_TEXT = "#1F2937"
C_GRID = "#E5E7EB"
C_ACCENT = "#1E3A8A"
C_ACCENT2 = "#3B82F6"
C_NEUTRAL = "#9CA3AF"
C_GREEN = "#059669"
C_RED = "#DC2626"
PALETTE = [C_ACCENT, C_ACCENT2, C_NEUTRAL, C_GREEN, "#7C3AED", "#B45309"]

OUT_DIR = Path("report/images")
OUT_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = Path("data/results_profile")
SALARY_DIR = Path("data/results_salary")
REGIONS_DIR = Path("data/results_regions")
V2_DIR = Path("data/results_v2")
EDA_DIR = Path("data/eda")
EXPERIENCE_DIR = Path("data/results_experience")

def _load_freq_csv(path: Path):
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        return [r for r in reader if r]

def _read_dicts(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def _limit_labels(labels: list[str], width: int = 28) -> list[str]:
    return [label if len(label) <= width else label[: width - 1] + "…" for label in labels]

def chart_growth_combinations() -> bool:
    sizes = [1, 2, 3]
    n_combos = []
    sum_freq = []
    for k in sizes:
        path = V2_DIR / f"skills_{k}.csv"
        if not path.exists():
            return False
        rows = _load_freq_csv(path)
        if not rows:
            return False
        n_combos.append(len(rows))
        sum_freq.append(sum(int(r[1]) for r in rows))

    fig, ax1 = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    ax2 = ax1.twinx()

    bars = ax1.bar(sizes, n_combos, color=C_ACCENT, alpha=0.85, width=0.45,
                   label="Уникальные комбинации", edgecolor=C_ACCENT, linewidth=0.5)
    ax1.set_xlabel("Размер стека навыков k")
    ax1.set_ylabel("Уникальные комбинации", color=C_ACCENT)
    ax1.tick_params(axis="y", labelcolor=C_ACCENT)
    ax1.set_xticks(sizes)
    ax1.set_xticklabels(["k=1 (навык)", "k=2 (пара)", "k=3 (тройка)"])
    ax1.grid(True, axis="y", color=C_GRID, linewidth=0.6)
    ax1.set_axisbelow(True)
    for b, v in zip(bars, n_combos):
        ax1.text(b.get_x() + b.get_width() / 2, v + max(n_combos) * 0.015,
                 f"{v:,}".replace(",", " "), ha="center", va="bottom",
                 fontsize=9, color=C_TEXT)

    ax2.plot(sizes, sum_freq, color=C_NEUTRAL, marker="o", linewidth=2,
             label="Суммарная частота")
    ax2.set_ylabel("Суммарная частота (эмиссий)", color=C_NEUTRAL)
    ax2.tick_params(axis="y", labelcolor=C_NEUTRAL)
    for x, y in zip(sizes, sum_freq):
        ax2.text(x, y + max(sum_freq) * 0.02, f"{y:,}".replace(",", " "),
                 ha="center", va="bottom", fontsize=9, color=C_NEUTRAL)

    ax1.set_title("Рост числа комбинаций и эмиссий (вариант DevOps)",
                  fontsize=11, color=C_TEXT, pad=12)
    plt.savefig(OUT_DIR / "01_growth.png", facecolor=C_BG)
    plt.close()
    return True

def chart_profile() -> bool:
    rows = _read_dicts(DATA_DIR / "summary.csv")
    if not rows:
        return False
    labels = {
        "mapreduce_v1": "MR v1\n(naive)",
        "mapreduce_v2": "MR v2\n(chunked)",
        "duckdb": "DuckDB",
    }
    short_labels = [labels.get(r["method"], r.get("label", r["method"])) for r in rows]
    wall_med = [float(r["wall_median_s"]) for r in rows]
    wall_min = [float(r["wall_min_s"]) for r in rows]
    wall_max = [float(r["wall_max_s"]) for r in rows]
    peak_med = [float(r["peak_median_mib"]) for r in rows]
    peak_min = [float(r["peak_min_mib"]) for r in rows]
    peak_max = [float(r["peak_max_mib"]) for r in rows]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 3.8), constrained_layout=True)
    x = list(range(len(rows)))
    colors = [PALETTE[i % len(PALETTE)] for i in x]

    err_lo = [max(0.0, m - lo) for m, lo in zip(wall_med, wall_min)]
    err_hi = [max(0.0, hi - m) for m, hi in zip(wall_med, wall_max)]
    bars1 = ax1.bar(x, wall_med, color=colors, width=0.55,
                    edgecolor=C_TEXT, linewidth=0.4)
    ax1.errorbar(x, wall_med, yerr=[err_lo, err_hi], fmt="none",
                 ecolor=C_TEXT, capsize=4, capthick=1)
    for b, v in zip(bars1, wall_med):
        ax1.text(b.get_x() + b.get_width() / 2, v + max(wall_max) * 0.04,
                 f"{v:.2f}s", ha="center", va="bottom", fontsize=9, color=C_TEXT)
    ax1.set_xticks(x)
    ax1.set_xticklabels(short_labels, fontsize=9)
    ax1.set_ylabel("Время выполнения, с")
    ax1.set_title("Wall time (медиана за 3 запуска)",
                  fontsize=10, color=C_TEXT, pad=8)
    ax1.grid(True, axis="y", color=C_GRID, linewidth=0.6)
    ax1.set_axisbelow(True)
    ax1.set_ylim(0, max(wall_max) * 1.2 if max(wall_max) > 0 else 1)

    err_lo = [max(0.0, m - lo) for m, lo in zip(peak_med, peak_min)]
    err_hi = [max(0.0, hi - m) for m, hi in zip(peak_med, peak_max)]
    bars2 = ax2.bar(x, peak_med, color=colors, width=0.55,
                    edgecolor=C_TEXT, linewidth=0.4)
    ax2.errorbar(x, peak_med, yerr=[err_lo, err_hi], fmt="none",
                 ecolor=C_TEXT, capsize=4, capthick=1)
    for b, v in zip(bars2, peak_med):
        ax2.text(b.get_x() + b.get_width() / 2, v + max(peak_max) * 0.04,
                 f"{v:.0f} MiB", ha="center", va="bottom", fontsize=9, color=C_TEXT)
    ax2.set_xticks(x)
    ax2.set_xticklabels(short_labels, fontsize=9)
    ax2.set_ylabel("Пиковая память, MiB")
    ax2.set_title("Peak RSS (медиана за 3 запуска)",
                  fontsize=10, color=C_TEXT, pad=8)
    ax2.grid(True, axis="y", color=C_GRID, linewidth=0.6)
    ax2.set_axisbelow(True)
    ax2.set_ylim(0, max(peak_max) * 1.2 if max(peak_max) > 0 else 1)

    plt.savefig(OUT_DIR / "02_profile.png", facecolor=C_BG)
    plt.close()
    return True

def chart_salary_pairs() -> bool:
    up = _read_dicts(SALARY_DIR / "pairs_up.csv")[:5]
    down = _read_dicts(SALARY_DIR / "pairs_down.csv")[:5]
    if not up and not down:
        return False
    labels = [r["combo"] for r in up] + [r["combo"] for r in down]
    deltas = [int(r["delta_rub"]) for r in up] + [int(r["delta_rub"]) for r in down]
    colors = [C_GREEN] * len(up) + [C_RED] * len(down)

    fig, ax = plt.subplots(figsize=(8, 4.8), constrained_layout=True)
    y_pos = list(range(len(labels)))
    bars = ax.barh(y_pos, deltas, color=colors, alpha=0.85, edgecolor=C_TEXT, linewidth=0.4)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.axvline(0, color=C_TEXT, linewidth=0.8)
    ax.set_xlabel("Δ к медианной зарплате базового навыка, ₽")
    ax.set_title("Топ-5 пар навыков, влияющих на зарплату\n"
                 "(зелёный — повышение, красный — понижение)",
                 fontsize=11, color=C_TEXT, pad=12)
    ax.grid(True, axis="x", color=C_GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    span = max(abs(v) for v in deltas) if deltas else 1
    for b, v in zip(bars, deltas):
        x_pos = v + (span * 0.01 if v >= 0 else -span * 0.01)
        ax.text(x_pos, b.get_y() + b.get_height() / 2,
                f"{'+' if v >= 0 else ''}{v:,} ₽".replace(",", " "),
                va="center", ha="left" if v >= 0 else "right",
                fontsize=9, color=C_TEXT)
    ax.set_xlim(min(0, min(deltas)) - span * 0.35, max(0, max(deltas)) + span * 0.35)
    plt.savefig(OUT_DIR / "03_salary_pairs.png", facecolor=C_BG)
    plt.close()
    return True

def chart_regions() -> bool:
    rows = _read_dicts(REGIONS_DIR / "overview.csv")
    if not rows:
        return False
    regions = [r["region"] for r in rows]
    medians = [int(float(r["median_salary_rub"])) for r in rows]
    p25 = [int(float(r["p25_rub"])) for r in rows]
    p75 = [int(float(r["p75_rub"])) for r in rows]
    n_total = [int(float(r["n_total"])) for r in rows]
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(rows))]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 3.8), constrained_layout=True)
    x = list(range(len(regions)))

    err_lo = [max(0.0, m - lo) for m, lo in zip(medians, p25)]
    err_hi = [max(0.0, hi - m) for m, hi in zip(medians, p75)]
    bars1 = ax1.bar(x, medians, color=colors, width=0.55,
                    edgecolor=C_TEXT, linewidth=0.4)
    ax1.errorbar(x, medians, yerr=[err_lo, err_hi], fmt="none",
                 ecolor=C_TEXT, capsize=4, capthick=1)
    for b, v in zip(bars1, medians):
        ax1.text(b.get_x() + b.get_width() / 2, v + max(p75) * 0.04,
                 f"{v:,} ₽".replace(",", " "), ha="center", va="bottom",
                 fontsize=9, color=C_TEXT)
    ax1.set_xticks(x)
    ax1.set_xticklabels([r.replace(" ", "\n") for r in regions], fontsize=9)
    ax1.set_ylabel("Медиана ЗП, ₽ (error bars=P25/P75)")
    ax1.set_title("Медианная зарплата по регионам", fontsize=10, color=C_TEXT, pad=8)
    ax1.grid(True, axis="y", color=C_GRID, linewidth=0.6)
    ax1.set_axisbelow(True)
    ax1.set_ylim(0, max(p75) * 1.2 if max(p75) > 0 else 1)

    bars2 = ax2.bar(x, n_total, color=colors, width=0.55,
                    edgecolor=C_TEXT, linewidth=0.4)
    for b, v in zip(bars2, n_total):
        ax2.text(b.get_x() + b.get_width() / 2, v + max(n_total) * 0.02,
                 f"{v:,}".replace(",", " "), ha="center", va="bottom",
                 fontsize=9, color=C_TEXT)
    ax2.set_xticks(x)
    ax2.set_xticklabels([r.replace(" ", "\n") for r in regions], fontsize=9)
    ax2.set_ylabel("Всего вакансий DevOps")
    ax2.set_title("Объём выборки по регионам", fontsize=10, color=C_TEXT, pad=8)
    ax2.grid(True, axis="y", color=C_GRID, linewidth=0.6)
    ax2.set_axisbelow(True)
    ax2.set_ylim(0, max(n_total) * 1.2 if max(n_total) > 0 else 1)

    plt.savefig(OUT_DIR / "04_regions.png", facecolor=C_BG)
    plt.close()
    return True

def chart_optimization_speedup() -> bool:
    rows = _read_dicts(DATA_DIR / "optimization_summary.csv")
    if len(rows) < 2:
        return False
    orig = next((r for r in rows if r["method"] == "original"), None)
    optm = next((r for r in rows if r["method"] == "optimized"), None)
    if orig is None or optm is None:
        return False

    raw_size = Path("data/manifests/mapreduce_v2.json")
    curated_size = Path("data/manifests/optimized_prepare.json")
    raw_label = "Raw CSV\n(808 MiB)"
    curated_label = "Curated CSV"
    try:
        import json
        raw_bytes = json.loads(raw_size.read_text(encoding="utf-8"))["input"]["size_bytes"]
        raw_label = f"Raw CSV\n({raw_bytes / 2**20:.0f} MiB)"
    except Exception:
        pass
    try:
        import json
        cur_bytes = json.loads(curated_size.read_text(encoding="utf-8"))["counts"]["curated_rows"]
        curated_label = f"Curated CSV\n({cur_bytes:,} строк)".replace(",", " ")
    except Exception:
        pass

    labels = [raw_label, curated_label]
    times = [float(orig["wall_median_s"]), float(optm["wall_median_s"])]
    mems = [float(orig["peak_median_mib"]), float(optm["peak_median_mib"])]
    if max(times + mems) <= 0:
        return False

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 3.5), constrained_layout=True)
    x = list(range(len(labels)))
    speedup_t = times[0] / times[1] if times[1] > 0 else 0
    speedup_m = mems[0] / mems[1] if mems[1] > 0 else 0

    bars1 = ax1.bar(x, times, color=[C_NEUTRAL, C_ACCENT], width=0.55,
                    edgecolor=C_TEXT, linewidth=0.4)
    for b, v in zip(bars1, times):
        ax1.text(b.get_x() + b.get_width() / 2, v + max(times) * 0.04,
                 f"{v:.2f}s", ha="center", va="bottom", fontsize=10, color=C_TEXT)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=10)
    ax1.set_ylabel("Время, с")
    ax1.set_title(f"Ускорение: {speedup_t:.2f}× (curated быстрее)",
                  fontsize=10, color=C_TEXT, pad=8)
    ax1.grid(True, axis="y", color=C_GRID, linewidth=0.6)
    ax1.set_axisbelow(True)
    ax1.set_ylim(0, max(times) * 1.3 if max(times) > 0 else 1)

    bars2 = ax2.bar(x, mems, color=[C_NEUTRAL, C_ACCENT], width=0.55,
                    edgecolor=C_TEXT, linewidth=0.4)
    for b, v in zip(bars2, mems):
        ax2.text(b.get_x() + b.get_width() / 2, v + max(mems) * 0.04,
                 f"{v:.0f} MiB", ha="center", va="bottom", fontsize=10, color=C_TEXT)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=10)
    ax2.set_ylabel("Пиковая память, MiB")
    ax2.set_title(f"Экономия памяти: {speedup_m:.2f}×",
                  fontsize=10, color=C_TEXT, pad=8)
    ax2.grid(True, axis="y", color=C_GRID, linewidth=0.6)
    ax2.set_axisbelow(True)
    ax2.set_ylim(0, max(mems) * 1.3 if max(mems) > 0 else 1)

    plt.savefig(OUT_DIR / "05_optimization.png", facecolor=C_BG)
    plt.close()
    return True

def chart_salary_histogram() -> bool:
    path = EDA_DIR / "salary_histogram.csv"
    if not path.exists():
        return False
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        rows = [(int(r[0]), int(r[1])) for r in reader if r and len(r) >= 2]
    if not rows:
        return False
    xs = [r[0] for r in rows]
    ys = [r[1] for r in rows]

    fig, ax = plt.subplots(figsize=(9, 4.2), constrained_layout=True)
    ax.bar(xs, ys, width=45, color=C_ACCENT, alpha=0.85,
           edgecolor=C_ACCENT, linewidth=0.5)
    ax.set_xlabel("Зарплата, тыс. ₽ (бакеты по 50к)")
    ax.set_ylabel("Число вакансий DevOps")
    ax.set_title("Распределение зарплат DevOps-вакансий (после нормализации в RUB net)",
                 fontsize=11, color=C_TEXT, pad=10)
    ax.grid(True, axis="y", color=C_GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    plt.savefig(OUT_DIR / "06_salary_histogram.png", facecolor=C_BG)
    plt.close()
    return True

def chart_skill_count_distribution() -> bool:
    path = EDA_DIR / "skills_count_distribution.csv"
    if not path.exists():
        return False
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        rows = [(int(r[0]), int(r[1])) for r in reader if r and len(r) >= 2]
    if not rows:
        return False
    xs = [r[0] for r in rows]
    ys = [r[1] for r in rows]

    fig, ax = plt.subplots(figsize=(9, 3.8), constrained_layout=True)
    ax.bar(xs, ys, color=C_ACCENT2, alpha=0.85, edgecolor=C_TEXT, linewidth=0.4)
    ax.set_xlabel("Число навыков в вакансии")
    ax.set_ylabel("Число вакансий DevOps")
    ax.set_title("Распределение числа навыков на вакансию",
                 fontsize=11, color=C_TEXT, pad=10)
    ax.grid(True, axis="y", color=C_GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    if max(xs) > 20:
        ax.set_xlim(0, 20)
    plt.savefig(OUT_DIR / "07_skills_per_vacancy.png", facecolor=C_BG)
    plt.close()
    return True

def chart_skill_freq_vs_salary() -> bool:
    candidate = SALARY_DIR / "single_skills.csv"
    if not candidate.exists():
        return False
    with open(candidate, encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        rows = list(reader)
    if not rows or len(header) < 3:
        return False
    points = []
    for r in rows:
        try:
            freq = int(r[1])
            med = int(r[2])
        except (ValueError, IndexError):
            continue
        if freq < 20:
            continue
        points.append((freq, med))
    if len(points) < 5:
        return False

    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    ax.scatter(xs, ys, color=C_ACCENT, alpha=0.6, s=50,
               edgecolor=C_TEXT, linewidth=0.5)
    ax.set_xlabel("Частота навыка (число вакансий с этим навыком)")
    ax.set_ylabel("Медианная зарплата навыка, ₽")
    ax.set_title("Корреляция: частота навыка ↔ медианная зарплата\n"
                 "(навыки с частотой ≥ 20 вакансий)",
                 fontsize=11, color=C_TEXT, pad=10)
    ax.grid(True, color=C_GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sum((x - mean_x) ** 2 for x in xs)
    den_y = sum((y - mean_y) ** 2 for y in ys)
    r_value = num / (den_x ** 0.5 * den_y ** 0.5) if den_x > 0 and den_y > 0 else 0
    ax.text(0.05, 0.95, f"Pearson r = {r_value:.3f}",
            transform=ax.transAxes, fontsize=11, verticalalignment="top", color=C_TEXT,
            bbox=dict(boxstyle="round,pad=0.4", facecolor=C_BG, edgecolor=C_GRID))
    plt.savefig(OUT_DIR / "08_freq_vs_salary.png", facecolor=C_BG)
    plt.close()
    return True

def chart_experience_salary() -> bool:
    rows = _read_dicts(EXPERIENCE_DIR / "summary.csv")
    if len(rows) < 2:
        return False
    rows = [r for r in rows if int(r["n_vacancies"]) > 0]
    if len(rows) < 2:
        return False

    labels = [r["experience"][:22] for r in rows]
    medians = [int(r["median_salary_rub"]) for r in rows]
    p25 = [int(r["p25_rub"]) for r in rows]
    p75 = [int(r["p75_rub"]) for r in rows]
    n_vac = [int(r["n_vacancies"]) for r in rows]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    x = list(range(len(labels)))

    err_lo = [max(0.0, m - lo) for m, lo in zip(medians, p25)]
    err_hi = [max(0.0, hi - m) for m, hi in zip(medians, p75)]
    ax1.bar(x, medians, color=C_ACCENT, width=0.55, edgecolor=C_TEXT, linewidth=0.4)
    ax1.errorbar(x, medians, yerr=[err_lo, err_hi], fmt="none",
                 ecolor=C_TEXT, capsize=4, capthick=1)
    for i, (v, nv) in enumerate(zip(medians, n_vac)):
        ax1.text(i, v + max(p75) * 0.04, f"{v:,}₽\n(n={nv})".replace(",", " "),
                 ha="center", va="bottom", fontsize=8, color=C_TEXT)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=8, rotation=15, ha="right")
    ax1.set_ylabel("Медиана ЗП, ₽ (error bars=P25/P75)")
    ax1.set_title("Зарплата по грейдам (опыт)", fontsize=10, color=C_TEXT, pad=8)
    ax1.grid(True, axis="y", color=C_GRID, linewidth=0.6)
    ax1.set_axisbelow(True)
    ax1.set_ylim(0, max(p75) * 1.25 if max(p75) > 0 else 1)

    ax2.bar(x, n_vac, color=C_ACCENT2, width=0.55, edgecolor=C_TEXT, linewidth=0.4)
    for i, v in enumerate(n_vac):
        ax2.text(i, v + max(n_vac) * 0.02, f"{v:,}".replace(",", " "),
                 ha="center", va="bottom", fontsize=9, color=C_TEXT)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=8, rotation=15, ha="right")
    ax2.set_ylabel("Число вакансий с зарплатой")
    ax2.set_title("Объём выборки по грейдам", fontsize=10, color=C_TEXT, pad=8)
    ax2.grid(True, axis="y", color=C_GRID, linewidth=0.6)
    ax2.set_axisbelow(True)
    ax2.set_ylim(0, max(n_vac) * 1.2 if max(n_vac) > 0 else 1)

    plt.savefig(OUT_DIR / "09_experience.png", facecolor=C_BG)
    plt.close()
    return True

def main() -> dict:
    charts = [
        ("01_growth", chart_growth_combinations),
        ("02_profile", chart_profile),
        ("03_salary_pairs", chart_salary_pairs),
        ("04_regions", chart_regions),
        ("05_optimization", chart_optimization_speedup),
        ("06_salary_histogram", chart_salary_histogram),
        ("07_skills_per_vacancy", chart_skill_count_distribution),
        ("08_freq_vs_salary", chart_skill_freq_vs_salary),
        ("09_experience", chart_experience_salary),
    ]
    generated, skipped = [], []
    for name, fn in charts:
        try:
            ok = fn()
        except Exception as exc:
            print(f"  ! {name}: {type(exc).__name__}: {exc}")
            ok = False
        (generated if ok else skipped).append(name)
    print(f"Charts generated in {OUT_DIR}: {len(generated)}/{len(charts)}")
    for name in generated:
        path = OUT_DIR / f"{name}.png"
        print(f"  {path.name}  ({path.stat().st_size // 1024} KiB)")
    if skipped:
        print(f"Skipped (no data): {', '.join(skipped)}")
    return {"generated": generated, "skipped": skipped}

if __name__ == "__main__":
    main()
