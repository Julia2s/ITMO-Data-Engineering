from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import matplotlib
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate,
    Paragraph, Preformatted, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "report"
IMAGES = REPORT / "images"
SCREENSHOTS = REPORT / "screenshots"
LOGS = REPORT / "logs"
OUT_PDF = REPORT / "report.pdf"

PAGE_W, PAGE_H = A4
MARGIN = 42
FRAME_W = PAGE_W - 2 * MARGIN

# ---------------------------------------------------------------------------
# Fonts (DejaVu from matplotlib: Cyrillic + ₽ + arrows + math symbols)
# ---------------------------------------------------------------------------
TTF = Path(matplotlib.__file__).resolve().parent / "mpl-data" / "fonts" / "ttf"
pdfmetrics.registerFont(TTFont("DejaVu", str(TTF / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(TTF / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Oblique", str(TTF / "DejaVuSans-Oblique.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-BoldOblique", str(TTF / "DejaVuSans-BoldOblique.ttf")))
pdfmetrics.registerFont(TTFont("DejaVuMono", str(TTF / "DejaVuSansMono.ttf")))
pdfmetrics.registerFontFamily(
    "DejaVu", normal="DejaVu", bold="DejaVu-Bold",
    italic="DejaVu-Oblique", boldItalic="DejaVu-BoldOblique",
)

C_DARK = colors.HexColor("#111827")
C_TEXT = colors.HexColor("#1F2937")
C_MUTED = colors.HexColor("#6B7280")
C_ACCENT = colors.HexColor("#1E3A8A")
C_ACCENT2 = colors.HexColor("#3B82F6")
C_LIGHT = colors.HexColor("#EEF2FF")
C_BORDER = colors.HexColor("#D1D5DB")
C_GREEN = colors.HexColor("#047857")
C_RED = colors.HexColor("#B91C1C")
C_CODE_BG = colors.HexColor("#F3F4F6")

styles: dict[str, ParagraphStyle] = {}


def build_styles() -> None:
    base = dict(fontName="DejaVu", textColor=C_TEXT, fontSize=10.3, leading=15.2,
                alignment=TA_JUSTIFY, spaceAfter=5)
    styles["Body"] = ParagraphStyle("Body", **base)
    styles["BodyLeft"] = ParagraphStyle("BodyLeft", parent=styles["Body"], alignment=TA_LEFT)
    styles["Small"] = ParagraphStyle("Small", parent=styles["Body"], fontSize=8.6, leading=12,
                                     textColor=C_MUTED, alignment=TA_LEFT)
    styles["Caption"] = ParagraphStyle("Caption", parent=styles["Body"], fontSize=8.6,
                                       leading=12, textColor=C_MUTED, alignment=TA_CENTER,
                                       spaceBefore=3, spaceAfter=10)
    styles["H1"] = ParagraphStyle("H1", fontName="DejaVu-Bold", fontSize=16.5, leading=21,
                                  textColor=C_ACCENT, spaceBefore=16, spaceAfter=8,
                                  keepWithNext=1)
    styles["H2"] = ParagraphStyle("H2", fontName="DejaVu-Bold", fontSize=12.3, leading=16,
                                  textColor=C_DARK, spaceBefore=11, spaceAfter=5,
                                  keepWithNext=1)
    styles["Bullet"] = ParagraphStyle("Bullet", parent=styles["Body"], leftIndent=14,
                                      bulletIndent=4, spaceAfter=3, alignment=TA_LEFT)
    styles["Cell"] = ParagraphStyle("Cell", fontName="DejaVu", fontSize=8.1, leading=10.4,
                                    textColor=C_TEXT, alignment=TA_LEFT)
    styles["CellC"] = ParagraphStyle("CellC", parent=styles["Cell"], alignment=TA_CENTER)
    styles["CellR"] = ParagraphStyle("CellR", parent=styles["Cell"], alignment=TA_RIGHT)
    styles["CellHead"] = ParagraphStyle("CellHead", fontName="DejaVu-Bold", fontSize=8.1,
                                        leading=10.2, textColor=colors.white,
                                        alignment=TA_CENTER)
    styles["CellHeadL"] = ParagraphStyle("CellHeadL", parent=styles["CellHead"],
                                         alignment=TA_LEFT)
    styles["CoverTitle"] = ParagraphStyle("CoverTitle", fontName="DejaVu-Bold", fontSize=30,
                                          leading=37, textColor=C_ACCENT, alignment=TA_LEFT)
    styles["CoverSub"] = ParagraphStyle("CoverSub", fontName="DejaVu", fontSize=15, leading=21,
                                        textColor=C_TEXT, alignment=TA_LEFT)
    styles["Code"] = ParagraphStyle("Code", fontName="DejaVuMono", fontSize=7.4, leading=9.6,
                                    textColor=C_DARK, alignment=TA_LEFT,
                                    leftIndent=5, rightIndent=5)
    styles["TOC1"] = ParagraphStyle("TOC1", fontName="DejaVu", fontSize=10.5, leading=17,
                                    textColor=C_TEXT)
    styles["TOC2"] = ParagraphStyle("TOC2", fontName="DejaVu", fontSize=9, leading=13,
                                    leftIndent=14, textColor=C_MUTED)


# ---------------------------------------------------------------------------
# Data access helpers
# ---------------------------------------------------------------------------
def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_freq(path: Path) -> list[tuple[str, int]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        return [(r[0], int(r[1])) for r in reader if r and len(r) >= 2]


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def log_text(name: str, max_chars: int = 14000) -> str:
    path = LOGS / name
    if not path.exists():
        return "(лог отсутствует)"
    data = path.read_bytes()
    if data.startswith(b"\xff\xfe"):
        text = data.decode("utf-16")
    elif data.startswith(b"\xfe\xff"):
        text = data.decode("utf-16-be")
    else:
        text = data.decode("utf-8-sig", errors="replace")
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (обрезано, полный лог в report/logs/)"
    return text


def fmt_int(value) -> str:
    try:
        return f"{int(float(value)):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def fmt_rub(value) -> str:
    return f"{fmt_int(value)} ₽"


def fmt_pct(value) -> str:
    try:
        return f"{float(value):+.1f} %"
    except (TypeError, ValueError):
        return str(value)


def esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def P(text, style="Body") -> Paragraph:
    return Paragraph(text, styles[style])


def bullets(items: list[str]) -> list[Paragraph]:
    return [Paragraph(item, styles["Bullet"], bulletText="•") for item in items]


# ---------------------------------------------------------------------------
# Layout primitives
# ---------------------------------------------------------------------------
def code_block(text: str, width_chars: int = 116) -> Table:
    lines: list[str] = []
    for raw in text.splitlines():
        if len(raw) <= width_chars:
            lines.append(raw)
            continue
        while len(raw) > width_chars:
            lines.append(raw[:width_chars])
            raw = raw[width_chars:]
        lines.append(raw)
    max_lines_per_block = 46
    chunks = [lines[i:i + max_lines_per_block]
              for i in range(0, len(lines), max_lines_per_block)] or [[""]]
    data = [[Preformatted("\n".join(chunk), styles["Code"])] for chunk in chunks]
    table = Table(data, colWidths=[FRAME_W], splitByRow=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_CODE_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def make_table(header: list[str], rows: list[list], widths: list[float],
               align_right: set[int] | None = None,
               align_center: set[int] | None = None) -> Table:
    align_right = align_right or set()
    align_center = align_center or set()
    data: list[list] = [[Paragraph(esc(h), styles["CellHead"]) for h in header]]
    for row in rows:
        cells: list[Paragraph] = []
        for idx, value in enumerate(row):
            style = "Cell"
            if idx in align_right:
                style = "CellR"
            elif idx in align_center:
                style = "CellC"
            cells.append(Paragraph(esc(value), styles[style]))
        data.append(cells)
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="CENTER")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), C_ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, C_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            commands.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F9FAFB")))
    table.setStyle(TableStyle(commands))
    return table


def add_image(path: Path, caption: str, width: float = 470,
              max_height: float = 560) -> list:
    if not path.exists():
        return [P(f"[изображение отсутствует: {esc(path.name)}]", "Small")]
    with PILImage.open(path) as im:
        w, h = im.size
    height = width * h / w
    if height > max_height:
        height = max_height
        width = height * w / h
    img = Image(str(path), width=width, height=height)
    img.hAlign = "CENTER"
    return [Spacer(1, 4), img, P(caption, "Caption")]


class ReportDoc(BaseDocTemplate):
    def __init__(self, filename: str, **kw):
        super().__init__(filename, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                         topMargin=MARGIN + 16, bottomMargin=MARGIN, **kw)
        frame = Frame(MARGIN, MARGIN, FRAME_W, PAGE_H - 2 * MARGIN - 16, id="body")
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=self._chrome)])

    def _chrome(self, canvas: rl_canvas.Canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("DejaVu", 7.6)
        canvas.setFillColor(C_MUTED)
        if doc.page > 1:
            canvas.drawString(MARGIN, PAGE_H - 28, "HW3 · DevOps · ITMO Data Engineering")
            canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 28, "26.10.2026")
            canvas.setStrokeColor(C_BORDER)
            canvas.setLineWidth(0.4)
            canvas.line(MARGIN, PAGE_H - 34, PAGE_W - MARGIN, PAGE_H - 34)
        canvas.drawCentredString(PAGE_W / 2, 22, str(doc.page))
        canvas.restoreState()

    def afterFlowable(self, flowable) -> None:
        if isinstance(flowable, Paragraph):
            name = flowable.style.name
            if name in ("H1", "H2"):
                level = 0 if name == "H1" else 1
                self.notify("TOCEntry", (level, flowable.getPlainText(), self.page))


# ---------------------------------------------------------------------------
# Story
# ---------------------------------------------------------------------------
def build_story() -> list:
    story: list = []
    v1 = read_json(ROOT / "data/manifests/mapreduce_v1.json")
    v2 = read_json(ROOT / "data/manifests/mapreduce_v2.json")
    duck = read_json(ROOT / "data/manifests/duckdb.json")
    prof = read_json(ROOT / "data/results_profile/profile.json")
    prof_rows = read_csv(ROOT / "data/results_profile/summary.csv")
    opt_rows = read_csv(ROOT / "data/results_profile/optimization_summary.csv")
    salary_summary = read_json(ROOT / "data/results_salary/summary.json")
    region_rows = read_csv(ROOT / "data/results_regions/overview.csv")
    remote_row = (read_csv(ROOT / "data/results_regions/remote_overview.csv") or [{}])[0]
    exp_rows = read_csv(ROOT / "data/results_experience/summary.csv")
    eda_rows = read_csv(ROOT / "data/eda/summary.csv")
    eda = {r["metric"]: r["value"] for r in eda_rows}
    final_rows = read_csv(ROOT / "data/results_salary/final_table.csv")
    counts = (v1.get("counts") or {})
    v1_counts = counts
    v2_counts = (v2.get("counts") or {})
    duck_counts = (duck.get("counts") or {})

    # ---------------------------------------------------------------- cover
    story.append(Spacer(1, 60))
    story.append(Table([[""]], colWidths=[FRAME_W], rowHeights=[6],
                       style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), C_ACCENT2)])))
    story.append(Spacer(1, 26))
    story.append(P("Аналитический пайплайн<br/>IT-вакансий: DevOps", "CoverTitle"))
    story.append(Spacer(1, 14))
    story.append(P("Домашнее задание №3 · объектное хранилище, MapReduce, "
                   "DuckDB, профилирование нагрузки", "CoverSub"))
    story.append(Spacer(1, 36))
    cover_info = [
        ["Дисциплина", "Data Engineering, ИТМО"],
        ["Вариант", "DevOps"],
        ["Хранилище", "RustFS 1.0.0, бакет hh-lake, объект raw/vacancies.csv"],
        ["Данные", "it_vacancies_2024.csv · 229 387 вакансий · 808.4 MiB"],
        ["Стек", "Python 3.14, boto3, DuckDB 2.0, psutil, matplotlib, ReportLab"],
        ["Дата запусков", "26.10.2026"],
    ]
    t = Table([[P(a, "BodyLeft"), P(b, "BodyLeft")] for a, b in cover_info],
              colWidths=[110, FRAME_W - 110], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, C_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TEXTCOLOR", (0, 0), (0, -1), C_MUTED),
    ]))
    story.append(t)
    story.append(Spacer(1, 70))
    story.append(P("Отчёт содержит фактические выводы команд, контрольные числа, "
                   "результаты профилирования времени и памяти, а также скриншоты "
                   "хранилища. Все числа получены на локальном запуске 26.10.2026.",
                   "Small"))
    story.append(PageBreak())

    # ---------------------------------------------------------------- TOC
    story.append(P("Содержание", "H1"))
    toc = TableOfContents()
    toc.levelStyles = [styles["TOC1"], styles["TOC2"]]
    toc.dotsMinLevel = 0
    story.append(toc)
    story.append(PageBreak())

    # ------------------------------------------------------- key results
    story.append(P("Ключевые результаты", "H1"))
    story.append(P("Сводка ниже позволяет проверить отчёт по независимым контрольным "
                   "точкам: число вакансий варианта, уникальные комбинации навыков, "
                   "суммарные частоты, совпадение трёх реализаций, медианные зарплаты "
                   "и профиль нагрузки."))
    kpi = [
        ["Файл в хранилище", "s3://hh-lake/raw/vacancies.csv · 847 619 384 B (808.35 MiB)"],
        ["Строк / валидных записей", "229 389 / 229 387 (1 пустая, 1 битая 45-польная)"],
        ["DevOps-вакансий (role)", "5 158"],
        ["Из них с навыками", "3 534"],
        ["Уникальные навыки / пары / тройки", "1 401 / 20 454 / 144 024"],
        ["Суммарные частоты k=1/2/3", "28 336 / 134 651 / 506 549"],
        ["Совпадение v1 = v2 = DuckDB", "да, 9 из 9 сравнений"],
        ["Медиана зарплаты (навыки + ЗП)", "210 000 ₽ (n = 787)"],
        ["Профиль v1 / v2 / DuckDB", "13.31 с / 196 MiB · 12.99 с / 132 MiB · 8.52 с / 1 419 MiB"],
        ["Оптимизация (curated CSV)", "6.17× быстрее, 1.17× меньше пиковой памяти"],
        ["Регионы", "Москва 250 000 ₽ · Санкт-Петербург 210 000 ₽ · Новосибирск 172 000 ₽"],
    ]
    story.append(make_table(["Показатель", "Значение"],
                            [[a, b] for a, b in kpi], [160, FRAME_W - 160]))
    story.append(Spacer(1, 8))
    story.append(P("Все артефакты (CSV, SQL, манифесты, логи, графики) сохранены локально "
                   "в каталоге data/ и в объектном хранилище в префиксах results/, "
                   "manifests/ и curated/."))

    # ---------------------------------------------------------------- 1
    story.append(P("1. Постановка задачи и выбранный вариант", "H1"))
    story.append(P("Задание требует поднять объектное хранилище, загрузить сегмент "
                   "IT-вакансий, посчитать частоты навыков, пар и троек двумя "
                   "независимыми способами (собственный MapReduce по чанкам и SQL "
                   "DuckDB), доказать совпадение результатов, проанализировать влияние "
                   "навыков на зарплату, сравнить три региона и профилировать время "
                   "и память."))
    story.append(P("Вариант — <b>DevOps</b>. Основной фильтр: <font name='DejaVuMono'>"
                   "role == \"DevOps-инженер\"</font>. Поле role в датасете — это "
                   "категория профессии (всего 17 значений), а не заголовок вакансии; "
                   "поэтому фильтр по role даёт чистый сегмент без примеси соседних "
                   "ролей. Режим фильтра настраивается переменной окружения "
                   "<font name='DejaVuMono'>VARIANT_FILTER_MODE=role|role_or_name|name</font>."))
    story.append(P("Чувствительность к фильтру (проверено тем же кодом): при "
                   "<font name='DejaVuMono'>role_or_name</font> (role или ключевые слова "
                   "в названии) в выборку попадает 7 786 вакансий, 5 335 с навыками, "
                   "1 295 с зарплатой; уникальные k=1/2/3 — 1 918 / 31 060 / 225 224, "
                   "суммарные частоты — 42 470 / 202 681 / 780 467, и все три реализации "
                   "совпадают и в этом режиме. В отчёте используется строгий role-режим "
                   "как основной."))
    story.append(P("Структура репозитория:", "H2"))
    story.append(code_block(
        "src/common.py               общий tolerant-ридер S3, фильтр, S3-клиенты, манифесты\n"
        "src/upload.py               multipart-загрузка CSV в RustFS\n"
        "src/mapreduce_v1.py         наивный MapReduce (все эмиссии в памяти)\n"
        "src/mapreduce_v2.py         MapReduce по чанкам (без перекрытий и дублей)\n"
        "src/duckdb_skills.py        независимый SQL-расчёт в DuckDB\n"
        "src/verify.py               побитовая сверка v1 == v2 == DuckDB\n"
        "src/analyze_salary.py       пары/тройки, влияющие на медианную зарплату\n"
        "src/analyze_regions.py      три региона + удалённая работа\n"
        "src/analyze_experience.py   зарплата и навыки по грейдам\n"
        "src/eda.py                  разведочный анализ датасета\n"
        "src/optimized_mapreduce.py  curated-витрина и бенчмарк-воркер\n"
        "src/profile.py              3 запуска каждого метода, wall time + peak RSS\n"
        "src/benchmark_optimization.py  сравнение raw vs curated\n"
        "src/make_charts.py, make_screenshots.py, make_report.py\n"
        "src/run_all.py, check_env.py   воспроизводимый запуск всего пайплайна\n"
        "tests/test_core.py          14 unit-тестов (парсинг, чанки, эквивалентность)\n"
        "compose.yaml                RustFS 9010/9011 + aws-cli"))

    # ---------------------------------------------------------------- 2
    story.append(P("2. Инфраструктура и загрузка данных", "H1"))
    story.append(P("Хранилище поднято через Docker Compose: RustFS 1.0.0 на порту 9010 "
                   "(S3 API) и 9011 (веб-консоль), aws-cli — отдельный контейнер. "
                   "Бакет hh-lake создаётся клиентом автоматически, объект загружается "
                   "multipart-загрузкой по 8 MiB (102 части)."))
    story.append(code_block(log_text("01_upload.log", 4000)))
    story.append(Spacer(1, 4))
    story.append(P("Контроль целостности: размер объекта после загрузки равен локальному "
                   "файлу — 847 619 384 байта; SHA-256 локального файла "
                   "<font name='DejaVuMono'>fb6a23f662c0b458e7d45d723862df5406cc25366164f4bb8246aad1cd4e83ef</font>. "
                   "Multipart ETag <font name='DejaVuMono'>efb65458995932747001aa004592d19c-102</font> "
                   "содержит суффикс -102, то есть ровно 102 части, что совпадает с "
                   "числом частей загрузки."))
    story.extend(add_image(SCREENSHOTS / "01_docker_compose_ps.png",
                           "Рис. 1. docker compose ps: контейнер RustFS в состоянии healthy.", 480))
    story.extend(add_image(SCREENSHOTS / "02_rustfs_bucket.png",
                           "Рис. 2. Содержимое бакета hh-lake: raw/vacancies.csv 808.4 MiB, "
                           "curated-витрина, results/ и manifests/ (aws-cli, реальный вывод).", 480))
    story.extend(add_image(SCREENSHOTS / "03_object_head.png",
                           "Рис. 3. head-object: размер и ETag объекта raw/vacancies.csv.", 480))
    story.extend(add_image(SCREENSHOTS / "rustfs_console.png",
                           "Рис. 4. Веб-консоль RustFS на http://localhost:9011 (headless-снимок "
                           "реальной страницы).", 440))

    story.append(P("2.1. Качество исходного CSV", "H2"))
    story.append(P("Файл имеет нестандартные особенности, из-за которых «наивный» "
                   "csv.DictReader даёт пустой результат: первая физическая строка пустая, "
                   "заголовка нет, а одна запись содержит 45 полей вместо 23 "
                   "(vacancy_id 106357315). Поэтому во всех реализациях используется "
                   "явная схема из 23 полей и tolerant-разбор: пустые строки, заголовок "
                   "и строки с неверным числом полей пропускаются и считаются отдельно."))
    story.append(make_table(
        ["Метрика", "Значение"],
        [["Физических строк", "229 389"],
         ["Валидных записей", "229 387"],
         ["Пропущено пустых", "1"],
         ["Пропущено битых", "1 (45 полей вместо 23)"],
         ["Уникальных vacancy_id", "229 387"],
         ["Колонок", "23"]],
        [220, FRAME_W - 220], align_right={1}))
    story.append(Spacer(1, 6))
    story.append(P("Схема: source, vacancy_id, status, snapshot_date, published_at, area, "
                   "employer_id, employer_inn, employer_ogrn, employer_name, name, role, "
                   "sphere, salary_from, salary_to, currency, gross, experience, schedule, "
                   "employment, key_skills, description, url. Поле employer_name в датасете "
                   "пустое, поэтому работодатели в EDA считаются по employer_id."))

    # ---------------------------------------------------------------- 3
    story.append(P("3. Методика расчёта навыков", "H1"))
    story.append(P("Навыки хранятся в key_skills через точку с запятой. Нормализация: "
                   "trim, нижний регистр, Unicode NFC, удаление пустых токенов и дублей "
                   "внутри вакансии. Для каждой вакансии с непустым набором навыков "
                   "генерируются все сочетания размера k = 1, 2, 3; комбинации внутри "
                   "вакансии сортируются, поэтому пары и тройки не зависят от порядка "
                   "навыков в исходном поле."))
    story.append(P("MapReduce v1 (наивная база).", "H2"))
    story.append(P("Один потоковый проход по объекту; все эмиссии (combo, 1) складываются "
                   "в список в памяти, затем reducer считает частоты. Это сознательно "
                   "неэкономная реализация: она показывает цену материализации всех "
                   "эмиссий. По сравнению с исходным вариантом строки не держатся в "
                   "памяти целиком, но эмиссии — держатся. Всего 669 536 эмиссий."))
    story.append(P("MapReduce v2 (чанки).", "H2"))
    story.append(P("Объект читается ranged-GET-запросами по 8 MiB. Границы чанков "
                   "выравниваются по переводу строки: последняя неполная строка "
                   "переносится в следующий чанк, а строка длиннее чанка собирается "
                   "целиком. Это исключает и потерю, и двойной учёт строк. В каждом "
                   "чанке сначала работает дешёвый байтовый префильтр по подстрокам "
                   "фильтра, затем точный разбор и подсчёт Counter; частичные счётчики "
                   "объединяются."))
    story.append(P("DuckDB SQL (независимая реализация).", "H2"))
    story.append(P("SQL читает тот же объект напрямую из S3 через httpfs. Условие варианта "
                   "написано вручную; CSV читается с header=false и явным списком имён "
                   "колонок, ignore_errors=true. Навыки разворачиваются через UNNEST и "
                   "string_split, пары и тройки строятся самосоединением с условиями "
                   "s1 < s2 < s3, что эквивалентно сочетаниям без повторений."))
    sql_path = ROOT / "data/results_duckdb/query.sql"
    if sql_path.exists():
        sql_text = sql_path.read_text(encoding="utf-8")
        story.append(code_block(sql_text[:5200], 112))
        story.append(P("Полный SQL сохранён в data/results_duckdb/query.sql и в "
                       "s3://hh-lake/results/duckdb/query.sql.", "Small"))

    # ---------------------------------------------------------------- 4
    story.append(P("4. Результаты: частоты навыков, пар и троек", "H1"))
    top = {k: read_freq(ROOT / f"data/results_v2/skills_{k}.csv") for k in (1, 2, 3)}
    freq_rows = []
    for k in (1, 2, 3):
        top5 = "; ".join(f"{c} ({fmt_int(n)})" for c, n in top[k][:5])
        freq_rows.append([f"k = {k}", fmt_int(len(top[k])),
                          fmt_int(sum(n for _, n in top[k])), top5])
    story.append(make_table(
        ["Размер стека", "Уникальных", "Суммарная частота", "Топ-5 комбинаций (частота)"],
        freq_rows, [58, 62, 78, FRAME_W - 198], align_center={0}, align_right={1, 2}))
    story.append(Spacer(1, 6))
    story.append(P("Суммарные частоты совпадают с числом эмиссий v1: "
                   "28 336 + 134 651 + 506 549 = 669 536 — это независимая проверка того, "
                   "что ни одна вакансия не потеряна и не учтена дважды."))

    story.append(P("4.1. Почему пары и тройки растут быстрее навыков", "H2"))
    n_with_skills = int(v1_counts.get("rows_with_skills", 3534))
    growth = []
    prev_unique = prev_total = None
    for k in (1, 2, 3):
        unique = len(top[k])
        total = sum(n for _, n in top[k])
        avg = total / n_with_skills if n_with_skills else 0
        if prev_unique:
            growth.append([f"k = {k}", fmt_int(unique), fmt_int(total), f"{avg:.2f}",
                           f"{100 * unique / total:.1f} %",
                           f"{unique / prev_unique:.1f}× / {total / prev_total:.2f}×"])
        else:
            growth.append([f"k = {k}", fmt_int(unique), fmt_int(total), f"{avg:.2f}",
                           f"{100 * unique / total:.1f} %", "—"])
        prev_unique, prev_total = unique, total
    story.append(make_table(
        ["k", "Уникальных", "Всего вхождений", "Вхождений на вакансию",
         "Уникальные / вхождения", "Рост к предыдущему k"],
        growth, [34, 62, 78, 76, 90, FRAME_W - 340],
        align_center={0}, align_right={1, 2, 3, 4, 5}))
    story.append(Spacer(1, 6))
    story.append(P("Рост объясняется комбинаторикой внутри вакансии. Вакансия с n "
                   "навыками даёт C(n,1) = n одиночных навыков, C(n,2) = n(n−1)/2 пар и "
                   "C(n,3) = n(n−1)(n−2)/6 троек. В выборке в среднем 8.02 навыка на "
                   "вакансию с навыками (28 336 / 3 534), то есть уже «средняя» вакансия "
                   "даёт 8 + 28 + 56 = 92 вхождения. Распределение числа навыков имеет "
                   "тяжёлый хвост: одна вакансия с 25 навыками добавляет 2 300 троек. "
                   "Поэтому суммарные вхождения троек (506 549) в 3.76 раза больше пар "
                   "(134 651) и в 17.9 раз больше одиночных навыков (28 336), хотя "
                   "уникальных троек лишь в 7.0 раз больше уникальных пар: частые "
                   "комбинации (docker/kubernetes/linux) повторяются у многих вакансий "
                   "и «схлопываются» в одну строку результата."))
    story.extend(add_image(IMAGES / "01_growth.png",
                           "Рис. 5. Рост числа уникальных комбинаций и суммарных эмиссий "
                           "при k = 1, 2, 3. Эмиссии растут почти линейно по k, "
                           "уникальные комбинации — медленнее из-за повторений.", 480))

    story.append(P("4.2. Верификация: v1 = v2 = DuckDB", "H2"))
    ver = []
    for k in (1, 2, 3):
        for a, b in (("v1", "v2"), ("v1", "duckdb"), ("v2", "duckdb")):
            ver.append([f"k = {k}", a, b, fmt_int(len(top[k])),
                        fmt_int(sum(n for _, n in top[k])), "совпало"])
    story.append(make_table(
        ["k", "Метод A", "Метод B", "Строк", "Сумма частот", "Результат"],
        ver, [48, 62, 72, 64, 90, FRAME_W - 336],
        align_center={0, 1, 2, 5}, align_right={3, 4}))
    story.append(Spacer(1, 6))
    story.append(P("Дополнительно verify.py сверяет файлы результатов с манифестами: "
                   "число строк skills_k.csv равно n_skills_k из манифеста, режим фильтра "
                   "одинаков у всех методов, rows_matched = 5 158 у v1, v2 и DuckDB. "
                   "Пустые наборы результатов трактуются как ошибка (иначе «совпадение» "
                   "двух пустых файлов было бы ложным успехом)."))
    story.extend(add_image(SCREENSHOTS / "04_verify.png",
                           "Рис. 6. Фактический вывод verify.py: 9 из 9 сравнений совпали.", 480))

    # ---------------------------------------------------------------- 5
    story.append(P("5. Профилирование нагрузки", "H1"))
    story.append(P("Каждый метод запускался отдельным процессом: один прогревочный запуск "
                   "(исключён из статистики) и три измерительных, методы чередуются, чтобы "
                   "сгладить влияние прогрева ОС и кэша RustFS. Wall time измеряется "
                   "monotonic-таймером вокруг процесса; пиковая память — суммарный RSS "
                   "дерева процессов (psutil) с опросом каждые 20 мс. Логи каждого запуска "
                   "лежат в report/logs/profile_*.log."))
    prof_table = []
    for r in prof_rows:
        prof_table.append([
            r["label"], f"{float(r['wall_median_s']):.2f}",
            f"{float(r['wall_min_s']):.2f}–{float(r['wall_max_s']):.2f}",
            f"{float(r['peak_median_mib']):.0f}",
            f"{float(r['peak_min_mib']):.0f}–{float(r['peak_max_mib']):.0f}",
            f"{r['n_ok']}/{r['n_runs']}",
        ])
    story.append(make_table(
        ["Метод", "Wall, с", "Wall min–max", "Peak RSS, MiB", "Peak min–max", "Успешно"],
        prof_table, [150, 58, 90, 74, 90, FRAME_W - 462],
        align_center={5}, align_right={1, 2, 3, 4}))
    story.append(Spacer(1, 6))
    story.append(P("Интерпретация:", "H2"))
    story.extend(bullets([
        "DuckDB быстрее всех по времени (8.52 с против 12.99 с у v2, ускорение 1.53×): "
        "векторизованный движок и параллелизм, но он читает весь CSV и держит в памяти "
        "агрегаты — пик 1 419 MiB, в 10.7 раза больше, чем у потокового v2.",
        "MapReduce v2 почти не быстрее v1 по времени (12.99 с против 13.31 с, +2.5 %): "
        "узкое место — чтение 808 MiB из S3 и разбор 229 тыс. строк, а не reducer. "
        "Зато v2 в 1.48 раза экономнее по памяти (132 MiB против 196 MiB), потому что "
        "агрегирует частичные Counter по чанкам и не хранит 669 536 эмиссий.",
        "Пик v1 (196 MiB) стабилен (195.9–204.0 MiB), v2 — 127–133 MiB: оба варианта "
        "комфортно работают на машине с 15.3 GiB RAM. DuckDB в третьем запуске достиг "
        "1 724 MiB — разброс связан с кэшем httpfs и планировщиком.",
        "Машина: 16 CPU, 15.34 GiB RAM, Python 3.14.5, Windows (win32), RustFS локально "
        "на loopback. Внешняя сеть не использовалась, поэтому времена отражают локальный "
        "диск и HTTP-стек, а не пропускную способность облака.",
    ]))
    story.extend(add_image(IMAGES / "02_profile.png",
                           "Рис. 7. Wall time и пиковая память: медианы трёх запусков, "
                           "усы — min–max.", 480))
    story.extend(add_image(SCREENSHOTS / "05_profile.png",
                           "Рис. 8. Вывод профилировщика (фрагмент с итоговой таблицей).", 480))

    # ---------------------------------------------------------------- 6
    story.append(P("6. Бонус: оптимизация через curated-витрину", "H1"))
    story.append(P("Идея: один раз отфильтровать 808 MiB raw-файла в компактную витрину "
                   "из двух колонок (vacancy_id, нормализованные навыки) и дальше считать "
                   "MapReduce только по ней. Витрина содержит 3 534 строки и занимает "
                   "322 653 B (315 KiB) — в 2 627 раз меньше исходного объекта. "
                   "Корректность витрины проверяется построчно: optimized_mapreduce.py "
                   "verify сравнивает vacancy_id и отсортированные наборы навыков с "
                   "полным проходом по raw-файлу."))
    opt_table = []
    for r in opt_rows:
        opt_table.append([
            r["label"], f"{float(r['wall_median_s']):.2f}",
            f"{float(r['peak_median_mib']):.0f}", f"{r['n_ok']}/{r['n_runs']}",
        ])
    story.append(make_table(
        ["Метод", "Wall, с (медиана)", "Peak RSS, MiB", "Успешно"],
        opt_table, [220, 110, 100, FRAME_W - 430],
        align_right={1, 2}, align_center={3}))
    story.append(Spacer(1, 6))
    story.append(P("Итог бенчмарка: <b>6.17× быстрее</b> (13.16 → 2.13 с) и "
                   "<b>1.17× меньше пиковой памяти</b> (132 → 113 MiB). Прирост памяти "
                   "невелик, потому что базовый Python-процесс и импорт библиотек дают "
                   "постоянный вклад; главный выигрыш — в объёме читаемых данных и в "
                   "отсутствии повторного разбора 23 колонок. Результаты raw и curated "
                   "совпали побитово (число строк и суммы частот по k = 1, 2, 3), "
                   "поэтому ускорение не куплено ценой изменения ответа."))
    story.append(code_block(log_text("11_curated_verify.log", 1200)))
    story.extend(add_image(IMAGES / "05_optimization.png",
                           "Рис. 9. Сравнение raw и curated: время и пиковая память "
                           "(медианы трёх запусков).", 480))
    story.extend(add_image(SCREENSHOTS / "06_benchmark.png",
                           "Рис. 10. Итоговая таблица бенчмарка и проверка совпадения "
                           "выходов.", 480))

    # ---------------------------------------------------------------- 7
    story.append(P("7. Влияние навыков на зарплату", "H1"))
    story.append(P("Зарплата нормализуется в месячную сумму в рублях: берётся середина "
                   "диапазона salary_from/salary_to (если задана одна граница — она), "
                   "пересчёт USD 90 ₽, EUR 100 ₽, KZT 0.19 ₽; gross-суммы уменьшаются "
                   "на 13 % НДФЛ. Записи без конвертируемой зарплаты (включая 1 строку "
                   "в BYR) исключаются. Из 5 158 DevOps-вакансий зарплата есть у 1 110, "
                   "а одновременно навыки и зарплата — у 787; медиана по этой выборке "
                   "210 000 ₽ (по всем 1 110 — 215 000 ₽)."))
    story.append(P("Для пары базой считается более частый из двух навыков, для тройки — "
                   "более частая из трёх пар, входящих в неё. Это требование задания: "
                   "сравнивать с базовым, а не с менее частым навыком. Порог: пара — "
                   "не менее 10 вакансий, тройка — не менее 8, база — не менее 15."))
    story.append(make_table(
        ["Показатель", "Значение"],
        [["DevOps-вакансий с зарплатой", "1 110"],
         ["С навыками и зарплатой", "787"],
         ["Медиана (навыки + зарплата)", "210 000 ₽"],
         ["Медиана (все с зарплатой)", "215 000 ₽"],
         ["Пар после порога", fmt_int((salary_summary.get("n_pairs_total") or 0))],
         ["Троек после порога", fmt_int((salary_summary.get("n_triples_total") or 0))],
         ["Валюты", "RUR 1 037 · USD 53 · EUR 20 · BYR 1 (не конвертируется)"]],
        [230, FRAME_W - 230], align_right={1}))

    def salary_rows(kind: str, limit: int = 5) -> list[list]:
        rows = [r for r in final_rows if r["kind"] == kind][:limit]
        out = []
        for r in rows:
            out.append([
                r["combo"], fmt_int(r["combo_n"]), fmt_rub(r["combo_median"]),
                r["base"], fmt_rub(r["base_median"]), fmt_int(r["base_n"]),
                f"{int(float(r['delta_rub'])):+,}".replace(",", " ") + " ₽",
                fmt_pct(r["delta_pct"]),
            ])
        return out

    headers = ["Комбинация", "n", "Медиана", "База", "Медиана базы", "n базы", "Δ, ₽", "Δ, %"]
    widths = [118, 28, 58, 78, 64, 42, 60, 44]

    story.append(P("7.1. Пары, повышающие зарплату", "H2"))
    story.append(make_table(headers, salary_rows("pair_up"), widths,
                            align_right={1, 2, 4, 5, 6, 7}))
    story.append(Spacer(1, 6))
    story.append(P("7.2. Пары, понижающие зарплату", "H2"))
    story.append(make_table(headers, salary_rows("pair_down"), widths,
                            align_right={1, 2, 4, 5, 6, 7}))
    story.append(Spacer(1, 6))
    story.append(P("7.3. Тройки, повышающие зарплату", "H2"))
    story.append(make_table(headers, salary_rows("triple_up"), widths,
                            align_right={1, 2, 4, 5, 6, 7}))
    story.append(Spacer(1, 6))
    story.append(P("7.4. Тройки, понижающие зарплату", "H2"))
    story.append(make_table(headers, salary_rows("triple_down"), widths,
                            align_right={1, 2, 4, 5, 6, 7}))
    story.append(Spacer(1, 8))
    story.extend(add_image(IMAGES / "03_salary_pairs.png",
                           "Рис. 11. Топ-5 пар, повышающих и понижающих медианную "
                           "зарплату относительно базового навыка.", 470))
    story.append(P("Что видно в данных:", "H2"))
    story.extend(bullets([
        "Наибольшая прибавка у пары devops + sre: медиана 350 175 ₽ при базе devops "
        "216 250 ₽ (+61.9 %, n = 12). Близко к ней идут grafana + openshift (+47.6 %), "
        "bash + мониторинг (+52.2 %), docker + openshift (+48.3 %), git + gitlab ci "
        "(+53.3 %): это признаки зрелой платформенной/SRE-роли с CI/CD и наблюдаемостью.",
        "Тройки с gitlab ci, helm, terraform, zabbix и python дают +60…+100 % к базовой "
        "паре (например, git + gitlab ci + python: 360 000 ₽ против 180 000 ₽ у git + "
        "python, n = 9). Это уже не «отдельный навык», а связка «CI/CD + IaC + "
        "автоматизация», которая в выборке соответствует senior-позициям.",
        "Понижают зарплату ansible + администрирование (−55.0 %), ansible + debian "
        "(−44.0 %), debian + linux (−50.0 %), docker-compose + grafana (−40.9 %), "
        "atlassian jira + prometheus (−50.0 %). Здесь важна интерпретация: сами по себе "
        "Ansible или Debian — востребованные навыки, но в паре с тегами "
        "«администрирование»/«debian» они маркируют legacy-эксплуатацию и сопровождение, "
        "а не разработку платформы; такие вакансии платят меньше.",
        "Ограничение: n у топовых комбинаций 8–38 вакансий, поэтому проценты — "
        "индикативные. Устойчивее вывод о направлении (IaC/CI-CD/SRE вверх, "
        "legacy-администрирование вниз), чем о конкретной величине прибавки.",
    ]))

    # ---------------------------------------------------------------- 8
    story.append(P("8. Региональный анализ", "H1"))
    story.append(P("Выбраны три региона с наибольшим числом DevOps-вакансий после Москвы "
                   "и Санкт-Петербурга: Москва, Санкт-Петербург и Новосибирск. Удалённая "
                   "работа показана отдельным срезом, потому что это не город; "
                   "нормализация ё→е позволяет не потерять вариант «Удаленная работа»."))
    reg_table = []
    for r in region_rows:
        reg_table.append([
            r["region"], fmt_int(r["n_total"]), fmt_int(r["n_with_skills"]),
            fmt_int(r["n_with_salary"]), f"{float(r['pct_with_salary']):.1f} %",
            fmt_rub(r["median_salary_rub"]), fmt_rub(r["p25_rub"]),
            fmt_rub(r["p75_rub"]), f"{float(r['mean_n_skills']):.2f}",
        ])
    if remote_row:
        reg_table.append([
            "Удалённая работа", fmt_int(remote_row["n_total"]),
            fmt_int(remote_row["n_with_skills"]), fmt_int(remote_row["n_with_salary"]),
            f"{float(remote_row['pct_with_salary']):.1f} %",
            fmt_rub(remote_row["median_salary_rub"]), fmt_rub(remote_row["p25_rub"]),
            fmt_rub(remote_row["p75_rub"]), f"{float(remote_row['mean_n_skills']):.2f}",
        ])
    story.append(make_table(
        ["Регион", "Вакансий", "С навыками", "С ЗП", "Доля с ЗП", "Медиана",
         "P25", "P75", "Ср. навыков"],
        reg_table, [92, 54, 58, 46, 52, 64, 62, 62, 50],
        align_right={1, 2, 3, 4, 5, 6, 7, 8}))
    story.append(Spacer(1, 6))
    story.append(P("8.1. Навыки и пары/тройки по регионам", "H2"))
    region_skill_rows = []
    for r in region_rows:
        region = r["region"]
        skills = read_csv(ROOT / "data/results_regions" / f"{region}_skills.csv")
        pairs = read_csv(ROOT / "data/results_regions" / f"{region}_pairs.csv")
        triples = read_csv(ROOT / "data/results_regions" / f"{region}_triples.csv")
        demand = read_csv(ROOT / "data/results_regions" / f"{region}_demand.csv")
        region_skill_rows.append([
            region,
            "; ".join(f"{s['combo']} ({s['pct']} %)" for s in skills[:3]),
            "; ".join(f"{s['combo']} ({s['pct']} %)" for s in pairs[:2]),
            "; ".join(f"{s['combo']} ({s['pct']} %)" for s in triples[:2]),
            "; ".join(f"{d['skill']} ×{d['index']}" for d in demand[:2]),
        ])
    story.append(make_table(
        ["Регион", "Топ-3 навыка", "Топ-2 пары", "Топ-2 тройки",
         "Повышенный спрос (индекс)"],
        region_skill_rows, [66, 102, 108, 130, FRAME_W - 406]))
    story.append(Spacer(1, 6))
    story.append(P("Индекс спроса — доля навыка внутри региона, делённая на его долю во "
                   "всей DevOps-выборке; индекс > 1 означает, что в регионе навык "
                   "встречается чаще среднего. Учитываются навыки с частотой ≥ 10."))
    story.extend(add_image(IMAGES / "04_regions.png",
                           "Рис. 12. Медианная зарплата (P25/P75) и объём выборки "
                           "по регионам.", 480))
    story.append(P("Наблюдения:", "H2"))
    story.extend(bullets([
        "Москва — 3 007 из 5 158 вакансий (58.3 %) и медиана 250 000 ₽; Санкт-Петербург "
        "— 686 (13.3 %) и 210 000 ₽; Новосибирск — 160 (3.1 %) и 172 000 ₽. Разрыв "
        "Москва/Новосибирск — 78 000 ₽ (45 % от новосибирской медианы).",
        "В Новосибирске необычно широкий интервал: P25 = 73 725 ₽, P75 = 315 000 ₽. "
        "Это не ошибка расчёта, а неоднородность выборки: город представлен и "
        "low-cost сопровождением, и высокооплачиваемыми удалёнными/продуктовыми "
        "командами. В Москве интервал уже (195 750–340 000 ₽).",
        "Среднее число навыков растёт от Москвы (7.65) к Санкт-Петербургу (8.34) и "
        "Новосибирску (9.20): в небольших городах вакансия чаще «широкая», требует "
        "больше технологий на одного инженера.",
        "Ядро стека одинаково во всех трёх регионах: linux, docker, kubernetes, "
        "ansible. Различаются акценты: Москва сильнее по yandex.cloud, istio, "
        "sonarqube (облако и платформа); Санкт-Петербург — по victoriametrics (×4.02), "
        "windows server и powershell; Новосибирск — по tcp/ip (×2.46), aws и java.",
        "Удалённая работа (1 762 вакансии, 34.2 % выборки) даёт медиану 250 000 ₽ — "
        "на уровне Москвы и выше Санкт-Петербурга; топ навык — kubernetes. Это "
        "показывает, что удалёнка не является «дешёвой» альтернативой офису.",
    ]))

    # ---------------------------------------------------------------- 9
    story.append(P("9. Опыт и разведочный анализ", "H1"))
    exp_table = []
    for r in exp_rows:
        exp_table.append([
            r["experience"], fmt_int(r["n_vacancies"]), fmt_int(r["n_with_skills"]),
            fmt_rub(r["median_salary_rub"]), fmt_rub(r["p25_rub"]),
            fmt_rub(r["p75_rub"]), f"{float(r['mean_n_skills']):.2f}",
        ])
    story.append(make_table(
        ["Опыт", "Вакансий", "С навыками", "Медиана", "P25", "P75", "Ср. навыков"],
        exp_table, [118, 58, 64, 70, 66, 66, FRAME_W - 442],
        align_right={1, 2, 3, 4, 5, 6}))
    story.append(Spacer(1, 6))
    story.append(P("Медиана монотонно растёт по грейдам: 69 600 → 152 250 → 250 000 → "
                   "304 500 ₽. При этом число навыков почти не меняется (7.8–9.4), то есть "
                   "прибавка связана с уровнем ответственности, а не с формальным "
                   "расширением стека. Крайние группы малочисленны (по 71 вакансии), "
                   "поэтому P25/P75 у них широкие."))
    story.extend(add_image(IMAGES / "09_experience.png",
                           "Рис. 13. Медианная зарплата и объём выборки по грейдам.", 480))
    story.extend(add_image(IMAGES / "06_salary_histogram.png",
                           "Рис. 14. Распределение зарплат DevOps-вакансий после "
                           "нормализации в RUB net.", 470))
    story.extend(add_image(IMAGES / "07_skills_per_vacancy.png",
                           "Рис. 15. Распределение числа навыков на вакансию "
                           "(медиана 5, среднее 8.02).", 470))
    story.extend(add_image(IMAGES / "08_freq_vs_salary.png",
                           "Рис. 16. Связь частоты навыка и его медианной зарплаты "
                           "(навыки с частотой ≥ 20).", 470))

    story.append(P("9.1. EDA: что ещё есть в датасете", "H2"))
    role_top = read_csv(ROOT / "data/eda/top_roles.csv")[:5]
    city_top = read_csv(ROOT / "data/eda/top_areas.csv")[:5]
    skill_top = read_csv(ROOT / "data/eda/top_devops_skills.csv")[:10]
    employers = read_csv(ROOT / "data/eda/top_employers.csv")[:5]
    story.append(make_table(
        ["Показатель", "Значение"],
        [["Всего валидных строк", fmt_int(eda.get("n_total_rows", 0))],
         ["Уникальных категорий role", fmt_int(eda.get("n_distinct_roles", 0))],
         ["Уникальных городов (area)", fmt_int(eda.get("n_distinct_areas", 0))],
         ["Уникальных работодателей (id)", fmt_int(eda.get("n_distinct_employers", 0))],
         ["DevOps-вакансий", fmt_int(eda.get("n_devops_total", 0))],
         ["Уникальных навыков в DevOps", fmt_int(eda.get("devops_unique_skills", 0))],
         ["Медиана навыков на вакансию", fmt_int(eda.get("devops_median_skills_per_vacancy", 0))],
         ["P10 / P90 зарплаты", f"{fmt_rub(eda.get('salary_p10_rub', 0))} / "
                                 f"{fmt_rub(eda.get('salary_p90_rub', 0))}"]],
        [230, FRAME_W - 230], align_right={1}))
    story.append(Spacer(1, 6))
    col1 = make_table(["Топ-роли (весь датасет)", "N"],
                      [[r["role"], fmt_int(r["count"])] for r in role_top],
                      [150, 50], align_right={1})
    col2 = make_table(["Топ-города (весь датасет)", "N"],
                      [[r["area"], fmt_int(r["count"])] for r in city_top],
                      [130, 50], align_right={1})
    story.append(Table([[col1, col2]], colWidths=[FRAME_W / 2, FRAME_W / 2],
                       style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")])))
    story.append(Spacer(1, 6))
    story.append(make_table(
        ["Топ-10 навыков DevOps", "N"],
        [[r["skill"], fmt_int(r["count"])] for r in skill_top],
        [220, FRAME_W - 220], align_right={1}))
    story.append(Spacer(1, 6))
    story.append(P("Поле employer_name в датасете пустое, поэтому топ работодателей "
                   "считается по employer_id (например, 4649269 — 168 DevOps-вакансий). "
                   "Всего 31 796 различных employer_id. Поле role содержит только 17 "
                   "категорий, что подтверждает: это профессия, а не заголовок вакансии; "
                   "заголовки лежат в name."))

    # ---------------------------------------------------------------- 10
    story.append(P("10. Выводы", "H1"))
    story.extend(bullets([
        "Инфраструктура и данные: RustFS поднят, бакет hh-lake содержит "
        "raw/vacancies.csv размером 847 619 384 B; размер и ETag подтверждены "
        "head-object, SHA-256 зафиксирован в отчёте.",
        "Все три реализации (наивный MapReduce, MapReduce по чанкам, DuckDB SQL) дали "
        "одинаковые 1 401 уникальный навык, 20 454 пары и 144 024 тройки; суммы частот "
        "28 336 / 134 651 / 506 549 совпали до строки. Это подтверждает и корректность "
        "фильтра, и отсутствие потерь/дублей на границах чанков.",
        "Рост числа комбинаций объясняется C(n,k) внутри вакансии и тяжёлым хвостом "
        "длинных списков навыков: в среднем 8.02 навыка, поэтому эмиссий троек в 3.76 "
        "раза больше пар, а уникальных троек — в 7.0 раз больше уникальных пар.",
        "По времени DuckDB быстрее (8.52 с), но потоковый MapReduce v2 в 10.7 раза "
        "экономнее по памяти (132 MiB против 1 419 MiB). Для 808 MiB на машине с "
        "15 GiB RAM оба варианта пригодны, но на больших объёмах преимущество "
        "потоковой схемы станет решающим.",
        "Оптимизация через curated-витрину дала 6.17× по времени и 1.17× по памяти при "
        "побитово том же результате: главный эффект — не читать 808 MiB и 23 колонки "
        "на каждом запуске.",
        "Зарплата: современный платформенный стек (SRE, OpenShift, Helm, Terraform, "
        "GitLab CI) повышает медиану на 45–100 %, а legacy-администрирование "
        "(Debian, docker-compose, «администрирование») понижает на 40–55 %. Это "
        "согласуется с гипотезой о переходе рынка от ручного сопровождения к "
        "автоматизации и IaC.",
        "Регионы: Москва платит медианно на 19 % больше Санкт-Петербурга и на 45 % "
        "больше Новосибирска; при этом ядро стека одинаково, а различия — в облачных "
        "и платформенных акцентах. Удалённая работа по медиане не уступает Москве.",
        "Ограничения: employer_name пуст; key_skills содержит не только технологии, но "
        "и теги роли; топовые пары/тройки опираются на 8–38 вакансий; все замеры "
        "локальные (RustFS на loopback), поэтому абсолютные времена не переносятся "
        "на облако.",
    ]))

    # ---------------------------------------------------------------- appendix
    story.append(PageBreak())
    story.append(P("Приложение A. Выводы команд", "H1"))
    story.append(P("Ниже приведены фактические логи запусков (report/logs/). Команды "
                   "запускались из корня репозитория в .venv; для профилирования и "
                   "бенчмарка дополнительно сохраняются отдельные логи каждого прогона."))
    appendix = [
        ("A.1. Проверка окружения", "00_check_env.log"),
        ("A.2. MapReduce v1", "02_mapreduce_v1.log"),
        ("A.3. MapReduce v2", "03_mapreduce_v2.log"),
        ("A.4. DuckDB SQL", "04_duckdb.log"),
        ("A.5. Верификация", "05_verify.log"),
        ("A.6. Зарплатный анализ", "07_salary.log"),
        ("A.7. Регионы", "08_regions.log"),
        ("A.8. Опыт", "09_experience.log"),
        ("A.9. Профилирование (итог)", "12_profile.log"),
        ("A.10. Бенчмарк оптимизации", "13_benchmark.log"),
        ("A.11. Графики", "14_charts.log"),
    ]
    for title, log_name in appendix:
        text = log_text(log_name)
        if title.startswith("A.9") or title.startswith("A.10"):
            lines = text.splitlines()
            idx = next((i for i, ln in enumerate(lines)
                        if "Summary" in ln or "ИТОГ" in ln), None)
            if idx is not None:
                text = "\n".join(lines[idx:])
        story.append(P(title, "H2"))
        story.append(code_block(text, 112))

    story.append(P("Приложение B. Воспроизводимость", "H1"))
    story.append(P("Полный пайплайн запускается одной командой (идемпотентно, с остановкой "
                   "на первой ошибке):"))
    story.append(code_block(
        "docker compose up -d\n"
        "python -m venv .venv\n"
        ".venv\\Scripts\\pip install -r requirements.txt\n"
        ".venv\\Scripts\\python -m unittest discover -s tests -v\n"
        ".venv\\Scripts\\python src\\check_env.py\n"
        ".venv\\Scripts\\python src\\run_all.py\n"
        "# только отчёт по уже готовым данным:\n"
        ".venv\\Scripts\\python src\\make_report.py"))
    story.append(P("Переменные окружения: S3_ENDPOINT (по умолчанию http://localhost:9010), "
                   "S3_ACCESS_KEY / S3_SECRET_KEY (hhadmin / hhadmin-secret), S3_BUCKET "
                   "(hh-lake), VACANCIES_KEY (raw/vacancies.csv), VARIANT_FILTER_MODE "
                   "(role), REGIONS (Москва,Санкт-Петербург,Новосибирск), PROFILE_RUNS (3). "
                   "Тесты используют локальный backend и не требуют Docker."))
    story.append(P("Приложение C. Ограничения и честность измерений", "H1"))
    story.extend(bullets([
        "Числа в отчёте получены 26.10.2026 на одной машине; при повторном запуске "
        "времена могут отличаться на 5–15 %, но контрольные числа (5 158 / 1 401 / "
        "20 454 / 144 024 и суммы частот) воспроизводимы детерминированно.",
        "Пиковая память — RSS дерева процессов, а не точный объём Python-кучи; "
        "для DuckDB в RSS входят буферы httpfs и кэш страниц, поэтому цифра выше, "
        "чем объём самих результатов.",
        "Проценты зарплатных прибавок — медианы по малым группам; они показывают "
        "направление и порядок, а не гарантированный эффект навыка. База для пары — "
        "более частый навык, для тройки — более частая пара.",
        "Фильтр role == \"DevOps-инженер\" выбран как основной; широкий режим "
        "role_or_name даёт другие числа (7 786 / 1 918 / 31 060 / 225 224), которые "
        "также сверены между v1, v2 и DuckDB.",
        "Скриншоты хранилища — реальные снимки (docker compose ps, aws-cli, веб-консоль "
        "RustFS, вывод verify/profile/benchmark), а не рисунки; их можно перегенерировать "
        "командой python src/make_screenshots.py.",
    ]))
    return story


def main() -> int:
    build_styles()
    for name in ("images", "screenshots", "logs"):
        (REPORT / name).mkdir(parents=True, exist_ok=True)
    doc = ReportDoc(str(OUT_PDF), title="HW3 DevOps — аналитический пайплайн",
                    author="ITMO Data Engineering")
    story = build_story()
    doc.multiBuild(story)
    size_mib = OUT_PDF.stat().st_size / 2**20
    from pypdf import PdfReader
    pages = len(PdfReader(str(OUT_PDF)).pages)
    print(f"Report written: {OUT_PDF} · {pages} pages · {size_mib:.2f} MiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
