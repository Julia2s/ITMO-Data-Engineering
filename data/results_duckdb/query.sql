WITH vacancies AS (
    SELECT row_number() OVER () AS rid, vacancy_id, role, name, key_skills
    FROM read_csv('s3://hh-lake/raw/vacancies.csv', header=false, names=['source', 'vacancy_id', 'status', 'snapshot_date', 'published_at', 'area', 'employer_id', 'employer_inn', 'employer_ogrn', 'employer_name', 'name', 'role', 'sphere', 'salary_from', 'salary_to', 'currency', 'gross', 'experience', 'schedule', 'employment', 'key_skills', 'description', 'url'], all_varchar=true, max_line_size=20000000, ignore_errors=true)
    WHERE TRIM(COALESCE(role, '')) = 'DevOps-инженер'
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
