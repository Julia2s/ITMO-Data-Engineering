from __future__ import annotations

import csv
import io
import os
import shutil
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Isolate the test S3 stand-in before importing common (env is read at import).
_TMP = tempfile.mkdtemp(prefix="hh3_tests_")
os.environ["S3_BACKEND"] = "local"
os.environ["LOCAL_FS_ROOT"] = _TMP
os.environ["VARIANT_FILTER_MODE"] = "role"

import common  # noqa: E402
from common import LocalFSClient, ReadStats, VACANCY_FIELDS  # noqa: E402

# `iter_byte_chunks` lives in mapreduce_v2; import after common is configured.
import mapreduce_v1  # noqa: E402
import mapreduce_v2  # noqa: E402
import duckdb_skills  # noqa: E402

iter_byte_chunks = mapreduce_v2.iter_byte_chunks


def make_row(**overrides) -> str:
    values = {field: "" for field in VACANCY_FIELDS}
    values.update({
        "source": "hh",
        "status": "active",
        "snapshot_date": "2024-06-01",
        "published_at": "2024-05-01",
        "area": "Москва",
        "employer_id": "1",
        "employer_name": "ООО Тест",
        "name": "DevOps инженер",
        "role": "DevOps-инженер",
        "sphere": "IT",
        "currency": "RUR",
        "gross": "true",
        "experience": "От 1 года до 3 лет",
        "schedule": "Полный день",
        "employment": "Полная занятость",
        "key_skills": "Linux;Docker",
        "description": "test",
        "url": "https://example.com/1",
    })
    values.update(overrides)
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerow([values[f] for f in VACANCY_FIELDS])
    return buf.getvalue().rstrip("\n")


ROWS = [
    make_row(vacancy_id="1", salary_from="100000", salary_to="150000",
             key_skills="Linux;Docker;Kubernetes"),
    make_row(vacancy_id="2", name="Java разработчик", role="Java-разработчик",
             key_skills="Java;Spring"),
    make_row(vacancy_id="3", salary_from="1000", salary_to="2000",
             currency="USD", gross="false", key_skills=""),
    make_row(vacancy_id="4", salary_from="200000", key_skills="Linux;Kubernetes;Terraform;Ansible"),
    make_row(vacancy_id="5", salary_from="90000", key_skills="linux;Linux;DOCKER"),
    make_row(vacancy_id="6", name="Senior DevOps Engineer", role="Программист",
             key_skills="Kubernetes;Helm"),
    make_row(vacancy_id="7", salary_from="300000", name="SRE",
             key_skills=";".join(f"skill{i:02d}" for i in range(25))),
]

MALFORMED = ",".join(["x"] * 22)  # 22 columns instead of 23


def write_object(cli, key: str, lines: list[str]) -> int:
    data = ("\n".join(lines) + "\n").encode("utf-8")
    cli.put_object(key, data)
    return len(data)


class TestParsing(unittest.TestCase):
    def test_vacancy_fields(self):
        self.assertEqual(len(VACANCY_FIELDS), 23)
        self.assertEqual(VACANCY_FIELDS[0], "source")
        self.assertEqual(VACANCY_FIELDS[11], "role")
        self.assertEqual(VACANCY_FIELDS[20], "key_skills")

    def test_parse_valid_row(self):
        row, reason = common.parse_vacancy_line(ROWS[0])
        self.assertIsNone(reason)
        self.assertEqual(row["vacancy_id"], "1")
        self.assertEqual(row["role"], "DevOps-инженер")

    def test_parse_blank_and_malformed(self):
        self.assertEqual(common.parse_vacancy_line(""), (None, "blank"))
        self.assertEqual(common.parse_vacancy_line("   "), (None, "blank"))
        self.assertEqual(common.parse_vacancy_line(MALFORMED), (None, "malformed"))

    def test_parse_header_is_skipped(self):
        header = ",".join(VACANCY_FIELDS)
        self.assertEqual(common.parse_vacancy_line(header), (None, "header"))

    def test_skills_normalised_and_deduplicated(self):
        self.assertEqual(
            common.parse_skills("Linux;Docker;Kubernetes"),
            ["linux", "docker", "kubernetes"],
        )
        self.assertEqual(common.parse_skills("Linux;Linux;  docker "), ["linux", "docker"])
        self.assertEqual(common.parse_skills(""), [])

    def test_salary_normalisation(self):
        s = common.salary_to_rub
        self.assertEqual(s({"salary_from": "100", "salary_to": "200", "currency": "RUR"}), 150)
        self.assertEqual(s({"salary_from": "100", "currency": "RUR"}), 100)
        self.assertEqual(s({"salary_to": "200", "currency": "RUR", "gross": "true"}), 174)
        self.assertAlmostEqual(s({"salary_from": "100", "currency": "USD"}), 9000)
        self.assertIsNone(s({"currency": "RUR"}))
        self.assertIsNone(s({"salary_from": "abc", "currency": "RUR"}))
        self.assertIsNone(s({"salary_from": "100", "currency": "BYR"}))


class TestVariantFilter(unittest.TestCase):
    def test_modes(self):
        devops = {"role": "DevOps-инженер", "name": "Инженер"}
        named = {"role": "Программист", "name": "Senior DevOps Engineer"}
        other = {"role": "Java-разработчик", "name": "Java Developer"}
        self.assertTrue(common.matches_variant(devops, "role"))
        self.assertFalse(common.matches_variant(named, "role"))
        self.assertTrue(common.matches_variant(named, "role_or_name"))
        self.assertTrue(common.matches_variant(named, "name"))
        self.assertTrue(common.matches_variant(devops, "role_or_name"))
        self.assertFalse(common.matches_variant(other, "role_or_name"))
        self.assertFalse(common.matches_variant(other, "name"))


class TestTolerantReader(unittest.TestCase):
    def setUp(self):
        self.cli = LocalFSClient()
        self.key = "tests/reader.csv"
        self.lines = ["", *ROWS, MALFORMED, ""]
        write_object(self.cli, self.key, self.lines)

    def test_skips_blank_malformed_and_counts(self):
        stats = ReadStats()
        rows = list(common.iter_vacancy_rows(self.cli, stats, key=self.key, chunk_bytes=64))
        self.assertEqual(len(rows), len(ROWS))
        self.assertEqual(stats.rows_parsed, len(ROWS))
        self.assertEqual(stats.skipped_malformed, 1)
        self.assertGreaterEqual(stats.skipped_blank, 2)
        self.assertEqual([r["vacancy_id"] for r in rows],
                         [str(i) for i in range(1, len(ROWS) + 1)])

    def test_utf8_split_across_chunks(self):
        key = "tests/utf8.csv"
        # 3-byte Cyrillic characters guarantee chunk boundaries inside a character.
        long_line = make_row(vacancy_id="utf", key_skills="Навык;" * 50)
        write_object(self.cli, key, ["", long_line, ROWS[0], ""])
        for chunk in (1, 2, 3, 5, 7, 13):
            rows = list(common.iter_vacancy_rows(self.cli, key=key, chunk_bytes=chunk))
            self.assertEqual([r["vacancy_id"] for r in rows], ["utf", "1"], f"chunk={chunk}")


class TestChunking(unittest.TestCase):
    def setUp(self):
        self.cli = LocalFSClient()
        self.key = "tests/chunks.csv"

    def test_no_duplicates_and_no_lost_lines(self):
        lines = [f"line-{i}" for i in range(200)]
        lines[57] = "long-" + "x" * 5000
        size = write_object(self.cli, self.key, lines)
        for chunk_bytes in (1, 7, 64, 511, 1024, 8192):
            chunks = list(iter_byte_chunks(self.cli, self.key, size, chunk_bytes=chunk_bytes))
            decoded: list[str] = []
            for data, _is_last in chunks:
                decoded.extend(mapreduce_v2.decode_lines(data))
            self.assertEqual(decoded, lines, f"chunk_bytes={chunk_bytes}")

    def test_single_line_longer_than_chunk(self):
        key = "tests/one-long-line.csv"
        line = "y" * 10000
        size = write_object(self.cli, key, [line])
        chunks = list(iter_byte_chunks(self.cli, key, size, chunk_bytes=64))
        decoded = [d for data, _ in chunks for d in mapreduce_v2.decode_lines(data)]
        self.assertEqual(decoded, [line])


class TestMapReduceEquivalence(unittest.TestCase):
    """v1 naive vs v2 chunked vs DuckDB must agree on a synthetic fixture."""

    def setUp(self):
        self.cli = LocalFSClient()
        self.key = "tests/equiv.csv"
        self.size = write_object(self.cli, self.key, ["", *ROWS, MALFORMED, ""])

    def _v1(self) -> dict[int, Counter]:
        rows = list(common.iter_vacancy_rows(self.cli, key=self.key))
        return mapreduce_v1.reducer_naive(mapreduce_v1.mapper_naive(rows))

    def _v2(self) -> dict[int, Counter]:
        counters = {k: Counter() for k in mapreduce_v2.STACK_SIZES}
        for data, _ in iter_byte_chunks(self.cli, self.key, self.size, chunk_bytes=97):
            chunk_counters, _stats = mapreduce_v2.map_chunk(mapreduce_v2.decode_lines(data))
            for k in counters:
                counters[k].update(chunk_counters[k])
        return counters

    def test_v2_matches_v1(self):
        self.assertEqual(self._v1(), self._v2())

    def test_non_empty_and_expected_top_skill(self):
        counters = self._v2()
        self.assertGreater(sum(counters[1].values()), 0)
        self.assertEqual(counters[1].most_common(1)[0][0], ("linux",))
        # vacancy 7 has 25 skills -> C(25,3) = 2300 triples from that row alone
        self.assertGreaterEqual(sum(counters[3].values()), 2300)
        self.assertGreaterEqual(counters[3][("skill00", "skill01", "skill02")], 1)

    def test_duckdb_matches_python(self):
        import duckdb

        path = self.cli._path(self.key).replace("\\", "/")
        sql = duckdb_skills.build_sql(path)
        rows = duckdb.execute(sql).fetchall()
        meta = {r[1]: int(r[2]) for r in rows if int(r[0]) == 0}
        self.assertGreater(meta["n_matched"], 0)
        self.assertGreater(meta["n_with_skills"], 0)

        sql_counters: dict[int, Counter] = {k: Counter() for k in (1, 2, 3)}
        for k, s1, s2, s3, freq in rows:
            k = int(k)
            if k == 0:
                continue
            combo = tuple(x for x in (s1, s2, s3) if x)
            sql_counters[k][combo] += int(freq)
        self.assertEqual(self._v2(), sql_counters)

    def tearDown(self):
        pass


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
