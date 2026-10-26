from __future__ import annotations

import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    get_s3_client, VACANCIES_KEY, VACANCY_FIELDS, VARIANT_ROLE,
    VARIANT_NAME_KEYWORDS, VARIANT_FILTER_MODE,
    S3_BUCKET, S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION,
    build_manifest, write_manifest, write_frequency_results,
)

import duckdb

OUTPUT_PREFIX = "results/duckdb"
LOCAL_OUT_DIR = "data/results_duckdb"
MANIFEST_DIR = "data/manifests"
STACK_SIZES = (1, 2, 3)


def _q(value: str) -> str:
    return value.replace("'", "''")


def _names_sql() -> str:
    return "[" + ", ".join("'" + _q(n) + "'" for n in VACANCY_FIELDS) + "]"


def _filter_sql() -> str:
    role = f"TRIM(COALESCE(role, '')) = '{_q(VARIANT_ROLE)}'"
    name = "(" + " OR ".join(
        f"lower(name) LIKE '%{_q(kw.lower())}%'" for kw in VARIANT_NAME_KEYWORDS
    ) + ")"
    if VARIANT_FILTER_MODE == "role":
        return role
    if VARIANT_FILTER_MODE == "name":
        return name
    return f"({role}) OR ({name})"


def build_sql(csv_path: str) -> str:
    read_csv = (
        f"read_csv('{_q(csv_path)}', header=false, names={_names_sql()}, "
        "all_varchar=true, max_line_size=20000000, ignore_errors=true)"
    )
    where = _filter_sql()
    return f"""
WITH vacancies AS (
    SELECT row_number() OVER () AS rid, vacancy_id, role, name, key_skills
    FROM {read_csv}
    WHERE {where}
),
stacks AS (
    SELECT rid, list_sort(list_distinct(list(lower(trim(skill))))) AS skills
    FROM vacancies, UNNEST(string_split(COALESCE(key_skills, ''), ';')) AS t(skill)
    WHERE trim(skill) <> ''
    GROUP BY rid
),
single AS (
    SELECT t.s AS s1, COUNT(*) AS freq
    FROM stacks, UNNEST(skills) AS t(s)
    GROUP BY 1
),
pairs AS (
    SELECT ta.s AS s1, tb.s AS s2, COUNT(*) AS freq
    FROM stacks, UNNEST(skills) AS ta(s), UNNEST(skills) AS tb(s)
    WHERE ta.s < tb.s
    GROUP BY 1, 2
),
triples AS (
    SELECT ta.s AS s1, tb.s AS s2, tc.s AS s3, COUNT(*) AS freq
    FROM stacks, UNNEST(skills) AS ta(s), UNNEST(skills) AS tb(s), UNNEST(skills) AS tc(s)
    WHERE ta.s < tb.s AND tb.s < tc.s
    GROUP BY 1, 2, 3
)
SELECT CAST(0 AS BIGINT) AS k, 'n_matched' AS combo1, CAST(COUNT(*) AS VARCHAR) AS combo2,
       '' AS combo3, CAST(0 AS BIGINT) AS freq
FROM vacancies
UNION ALL
SELECT 0, 'n_with_skills', CAST(COUNT(*) AS VARCHAR), '', 0 FROM stacks
UNION ALL
SELECT CAST(1 AS BIGINT), CAST(s1 AS VARCHAR), CAST('' AS VARCHAR), CAST('' AS VARCHAR), CAST(freq AS BIGINT) FROM single
UNION ALL
SELECT CAST(2 AS BIGINT), CAST(s1 AS VARCHAR), CAST(s2 AS VARCHAR), CAST('' AS VARCHAR), CAST(freq AS BIGINT) FROM pairs
UNION ALL
SELECT CAST(3 AS BIGINT), CAST(s1 AS VARCHAR), CAST(s2 AS VARCHAR), CAST(s3 AS VARCHAR), CAST(freq AS BIGINT) FROM triples
ORDER BY k, freq DESC
""".strip() + "\n"


def _init_httpfs() -> None:
    try:
        duckdb.execute("INSTALL httpfs")
    except Exception:
        pass  # already installed or offline; LOAD reports the real problem
    try:
        duckdb.execute("LOAD httpfs")
    except Exception as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "Не удалось загрузить DuckDB httpfs. Проверьте интернет/расширения: "
            f"{exc}"
        ) from exc


def run() -> dict:
    cli = get_s3_client()
    t0 = time.perf_counter()

    if hasattr(cli, "_path"):
        csv_path = cli._path(VACANCIES_KEY).replace("\\", "/")
    else:
        _init_httpfs()
        endpoint = S3_ENDPOINT.replace("http://", "").replace("https://", "")
        use_ssl = S3_ENDPOINT.startswith("https://")
        duckdb.execute(f"""
            CREATE OR REPLACE SECRET rustfs (
                TYPE s3,
                KEY_ID '{_q(S3_ACCESS_KEY)}',
                SECRET '{_q(S3_SECRET_KEY)}',
                ENDPOINT '{_q(endpoint)}',
                URL_STYLE 'path',
                USE_SSL {'true' if use_ssl else 'false'},
                REGION '{_q(S3_REGION)}'
            );
        """)
        csv_path = f"s3://{S3_BUCKET}/{VACANCIES_KEY}"

    sql = build_sql(csv_path)
    os.makedirs(LOCAL_OUT_DIR, exist_ok=True)
    with open(f"{LOCAL_OUT_DIR}/query.sql", "w", encoding="utf-8") as f:
        f.write(sql)
    cli.put_object(f"{OUTPUT_PREFIX}/query.sql", sql.encode("utf-8"),
                   content_type="text/plain; charset=utf-8")

    rows = duckdb.execute(sql).fetchall()
    t1 = time.perf_counter()

    by_k: dict[int, list[tuple]] = {k: [] for k in STACK_SIZES}
    meta: dict[str, int] = {}
    for k, s1, s2, s3, freq in rows:
        if k == 0:
            meta[str(s1)] = int(s2)
            continue
        combo = [x for x in (s1, s2, s3) if x]
        by_k[k].append((tuple(combo), int(freq)))

    counters = {k: Counter(dict(by_k[k])) for k in STACK_SIZES}
    written = write_frequency_results(cli, counters, OUTPUT_PREFIX, LOCAL_OUT_DIR)
    t2 = time.perf_counter()

    result = {
        "csv_path": csv_path,
        "filter_mode": VARIANT_FILTER_MODE,
        "rows_matched": meta.get("n_matched", 0),
        "rows_with_skills": meta.get("n_with_skills", 0),
        "n_skills_1": written[1]["n_combinations"],
        "n_skills_2": written[2]["n_combinations"],
        "n_skills_3": written[3]["n_combinations"],
        "total_frequency": {k: written[k]["total_frequency"] for k in STACK_SIZES},
        "duckdb_version": duckdb.__version__,
        "phase_time_query_s": round(t1 - t0, 3),
        "phase_time_write_s": round(t2 - t1, 3),
        "phase_time_total_s": round(t2 - t0, 3),
        "results": written,
    }

    manifest = build_manifest("duckdb", cli, {
        "duckdb_version": duckdb.__version__,
        "csv_path": csv_path,
        "counts": {
            "rows_matched": result["rows_matched"],
            "rows_with_skills": result["rows_with_skills"],
            "n_skills_1": result["n_skills_1"],
            "n_skills_2": result["n_skills_2"],
            "n_skills_3": result["n_skills_3"],
        },
        "sql_local_path": f"{LOCAL_OUT_DIR}/query.sql",
        "timings": {
            "query_s": result["phase_time_query_s"],
            "write_s": result["phase_time_write_s"],
            "total_s": result["phase_time_total_s"],
        },
    })
    result["manifest"] = write_manifest(cli, "duckdb", manifest, MANIFEST_DIR)
    return result


if __name__ == "__main__":
    import json
    stats = run()
    print(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
