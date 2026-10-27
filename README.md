# HW#3 Data Engineering — вариант DevOps

Лабораторная работа №3 по курсу Data Engineering (ITMO).
Полный пайплайн: RustFS → MapReduce (v1 naive + v2 optimized) → DuckDB →
EDA → анализ навыков → анализ зарплат → региональный анализ → анализ опыта →
профилирование → бонусная оптимизация через curated-датасет.

## Датасет

В бакет `hh-lake` грузится **полный** `it_vacancies_2024.csv` (все 23 колонки,
все варианты) по S3-ключу `raw/vacancies.csv`. Фильтр варианта DevOps
происходит **в рантайме** по полю `role == 'DevOps-инженер'` (точное совпадение
после TRIM). Разделитель в `key_skills` — `;`. Навыки не нормализуются
алиасами — остаются «сырые» lowercased значения.

Режим фильтра настраивается через `VARIANT_FILTER_MODE` env-переменную:
- `role` (по умолчанию) — строго `role == 'DevOps-инженер'`
- `role_or_name` — role OR regex по name (devops|sre|ci/cd|...)
- `name` — только regex по name

## Схема CSV (23 колонки, порядок важен!)

```
source, vacancy_id, status, snapshot_date, published_at, area,
employer_id, employer_inn, employer_ogrn, employer_name, name, role,
sphere, salary_from, salary_to, currency, gross, experience, schedule,
employment, key_skills, description, url
```

## Структура репозитория

```
.
├── README.md
├── requirements.txt            # boto3, duckdb, psutil, matplotlib
├── compose.yaml               # Минимальный: только RustFS + s3cli
├── .gitignore
│
├── src/                       
│   ├── common.py              # S3-клиент + умный фильтр DevOps (role || name)
│   ├── upload.py              # Multipart upload в raw/vacancies.csv
│   ├── check_env.py           # Проверка окружения перед запуском
│   ├── run_all.py             # Оркестратор: запускает все шаги по очереди
│   ├── eda.py                 # Разведывательный анализ всего датасета
│   ├── mapreduce_v1.py        # Наивный MapReduce (baseline)
│   ├── mapreduce_v2.py        # Byte-range chunks + combiner + prefilter
│   ├── duckdb_skills.py       # DuckDB SQL через httpfs из S3
│   ├── verify.py              # Строгое сравнение v1 == v2 == DuckDB
│   ├── analyze_salary.py      # Пары/тройки up/down + single_skills.csv
│   ├── analyze_regions.py     # Города + "Удалёнка" (по полю schedule)
│   ├── analyze_experience.py  # Зарплата по грейдам (Нет опыта/1-3/3-6/>6)
│   ├── profile.py             # 3×3 профайлинг: v1/v2/duckdb
│   ├── optimized_mapreduce.py  # Бонус: prepare/verify/benchmark-worker
│   ├── benchmark_optimization.py # Бонус: raw vs curated
│   └── make_charts.py         # 9 PNG-чартов
│
├── data/                      # Локальные данные (см. .gitignore)
│   ├── it_vacancies_2024.csv  # исходный датасет
│   ├── curated_devops_skills.csv # бонусный curated
│   ├── eda/                   # результаты EDA
│   ├── manifests/             # JSON-манифесты (время запуска, etag)
│   ├── results_v1/            # результаты MapReduce v1
│   ├── results_v2/            # результаты MapReduce v2
│   ├── results_duckdb/        # результаты DuckDB
│   ├── results_salary/        # таблицы salary + single_skills.csv
│   ├── results_regions/       # таблицы регионов
│   ├── results_experience/    # таблицы по грейдам
│   ├── results_optimized/     # результаты на curated
│   └── results_profile/       # профайлинг CSV
│
└── report/
    ├── images/                # PNG-чарты (от make_charts.py)
    └── logs/                  # логи запуска (от run_all.py)
```

**Отчёт (`report.pdf`)** 

## Запуск пайплайна

### 1. Поднять RustFS

```bash
docker compose up -d

# Создать бакет hh-lake через s3cli
docker exec hh-s3cli aws --endpoint-url http://rustfs-home:9000 s3 mb s3://hh-lake

# Проверить, что RustFS отвечает
curl http://localhost:9010/health
docker compose ps
```

### 2. Установить зависимости и настроить окружение

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export S3_BACKEND=boto3
export S3_ENDPOINT=http://localhost:9010
export S3_ACCESS_KEY=hhadmin
export S3_SECRET_KEY=hhadmin-secret
export S3_BUCKET=hh-lake
export S3_REGION=us-east-1
```

### 3. Загрузить ПОЛНЫЙ it_vacancies_2024.csv

```bash
cp ~/Downloads/it_vacancies_2024.csv data/it_vacancies_2024.csv
python src/upload.py
# → s3://hh-lake/raw/vacancies.csv
```

### 4. Проверить окружение

```bash
python src/check_env.py
# Должно вывести все OK без FAIL
```

### 5. Запустить весь пайплайн одной командой

```bash
python src/run_all.py
# Прогонит 15 шагов: check_env → upload → mapreduce v1/v2 → duckdb →
# verify → eda → salary → regions → experience → curated → profile →
# benchmark → charts
```

### 6. Сделать скриншоты и отчёт (вручную)

После прогона:
- Скриншоты: RustFS Web UI (http://localhost:9011), `docker compose ps`,
  `python src/upload.py --list`, вывод команд в терминале
- Отчёт: соберите в PDF вручную, вставив таблицы из `data/results_*/` и
  PNG-чарты из `report/images/`

## Регионы

По умолчанию: **Москва, Санкт-Петербург, Новосибирск**. Скрипт печатает
топ-10 городов (поле `area`) и топ-5 типов занятости (поле `schedule`).

ВАЖНО: **«Удалённая работа» живёт в поле `schedule`, не в `area`!** Если
хотите анализировать удалёнку:

```bash
export REGIONS='Москва,Санкт-Петербург,Удалённая работа'
python src/analyze_regions.py
```

Скрипт распознает "Удалённая работа" (с любой орфографией ё/е) и
фильтрует по `schedule` автоматически.

## Аналитические срезы

Помимо обязательных этапов задания, пайплайн считает **дополнительные инсайты**:

1. **EDA** (`eda.py`):
   - Распределение вакансий по ролям (топ-20)
   - Распределение по городам (топ-15)
   - Топ-15 работодателей
   - Распределение по опыту и типам занятости
   - Гистограмма распределения зарплат (бакеты по 50k ₽)
   - Распределение числа навыков на вакансию
   - Топ-30 навыков DevOps

2. **Зарплата по грейдам** (`analyze_experience.py`):
   - Медиана / P25 / P75 по experience: Нет опыта / 1-3 / 3-6 / >6 лет
   - Топ-10 навыков в каждом грейде
   - Среднее число навыков на вакансию в каждом грейде

3. **Корреляция частота ↔ зарплата** (`make_charts.py`, chart 08):
   - Scatter plot: частота навыка vs медианная зарплата
   - Pearson r — положительная корреляция означает «чем чаще навык, тем выше
     медиана зарплаты»
