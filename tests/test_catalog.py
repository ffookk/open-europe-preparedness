"""Behavioral tests use fictional records and fixed cutoff dates."""
import copy
import datetime as dt
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.catalog import Catalog, CatalogError, Query, dataset, load_catalog, main
from scripts.validate_records import validate_document

ROOT = Path(__file__).resolve().parents[1]
DAY = dt.date(2024, 1, 5)


def record(suffix="a", **changes):
    result = json.loads((ROOT / "examples/synthetic.json").read_text())["records"][0]
    result.update(id="synthetic-" + suffix, title="Example " + suffix, jurisdiction="Example area", **changes)
    return result


def document(*records):
    return {"schema_version": 1, "records": list(records)}


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.a = record("a")
        self.b = record("b", policy_stage="announced", topic="civil_protection")
        self.b["jurisdiction"] = "Second area"
        self.b["last_verified_at"] = "2024-01-05"
        self.c = record("c", verification_status="pending", last_verified_at=None)
        self.c["dates"]["announced_at"] = None
        self.catalog = Catalog([document(self.c, self.b), document(self.a)], as_of=DAY)

    def test_combined_filters_and_repeatable_or(self):
        self.assertEqual([r["id"] for r in self.catalog.select(Query(policy_stage=("proposed", "announced"), topic=("civil_protection",)))], ["synthetic-b"])
        self.assertEqual(len(self.catalog.select(Query(jurisdiction=("EXAMPLE AREA",)))), 2)
        self.assertEqual(self.catalog.select(Query(record_type=("real",))), [])

    def test_text_search_includes_evidence_and_limits(self):
        for text in ("FICTIONAL SECTION", "never include", "Example Authority"):
            self.assertEqual(len(self.catalog.select(Query(text=text))), 3)
        self.assertEqual(self.catalog.select(Query(text="absent phrase")), [])

    def test_inclusive_date_edges_and_unknowns(self):
        q = Query(date_from=dt.date(2024, 1, 3), date_to=dt.date(2024, 1, 3))
        self.assertEqual([r["id"] for r in self.catalog.select(q)], ["synthetic-a"])
        self.assertEqual(len(self.catalog.select(Query(date_presence="unknown"))), 1)
        self.assertEqual(len(self.catalog.select(Query(date_presence="known"))), 2)
        self.assertEqual(len(self.catalog.select(Query(date_field="target_at", date_from=dt.date(2025, 1, 1)))), 3)
        self.assertEqual(len(self.catalog.select(Query(date_field="announced_at", date_to=DAY))), 2)

    def test_age_uses_one_fixed_cutoff_and_excludes_unknowns(self):
        self.assertEqual([r["id"] for r in self.catalog.select(Query(max_review_age=0))], ["synthetic-b"])
        self.assertEqual(len(self.catalog.select(Query(max_review_age=2))), 2)
        self.assertEqual(len(self.catalog.select(Query(max_review_age=1))), 1)

    def test_sort_ties_null_last_and_pagination_facets(self):
        self.assertEqual([r["id"] for r in self.catalog.select(Query(sort="last_verified_at", descending=True))], ["synthetic-b", "synthetic-a", "synthetic-c"])
        self.assertEqual([r["id"] for r in self.catalog.select(Query(sort="topic", descending=True))], ["synthetic-a", "synthetic-c", "synthetic-b"])
        result = self.catalog.query(Query(offset=1, limit=1))
        self.assertEqual((result["total_count"], result["matched_count"], result["returned_count"]), (3, 3, 1))
        self.assertEqual(result["records"][0]["id"], "synthetic-b")
        self.assertEqual(result["facets"]["verification_status"], {"pending": 1, "verified": 2})
        self.assertEqual(self.catalog.query(Query(offset=9))["records"], [])

    def test_exports_preserve_every_original_field_and_are_isolated(self):
        exported = dataset(self.catalog.query(Query(text="synthetic-a"))["records"])
        self.assertEqual(exported, document(self.a))
        self.assertEqual(validate_document(exported, as_of=DAY), [])
        exported["records"][0]["limitations"] = []
        self.assertTrue(self.catalog.records[2]["limitations"])
        with self.assertRaises(CatalogError):
            dataset([])

    def test_cross_file_ids_and_structural_errors_fail_closed(self):
        for docs in ([document(self.a), document(self.a)], [document()], [{"schema_version": 1, "records": "bad"}]):
            with self.assertRaises(CatalogError):
                Catalog(docs, as_of=DAY)
        modified = copy.deepcopy(self.a)
        modified["last_verified_at"] = "2024-01-06"
        with self.assertRaises(CatalogError):
            Catalog([document(modified)], as_of=DAY)
        modified["last_verified_at"] = "2024-01-05"
        modified["sources"][0]["accessed_at"] = "2024-01-06"
        with self.assertRaises(CatalogError):
            Catalog([document(modified)], as_of=DAY)

    def test_default_utc_cutoff_and_input_mutation_do_not_change_catalog(self):
        self.assertEqual(Catalog([document(self.a)]).as_of, dt.datetime.now(dt.timezone.utc).date())
        self.a["title"] = "Changed externally"
        self.assertEqual(self.catalog.select(Query())[0]["title"], "Example a")

    def test_invalid_query_options(self):
        for q in (Query(limit=0), Query(offset=-1), Query(max_review_age=True), Query(sort="unsupported"),
                  Query(date_from="2024-01-01"), Query(date_from=DAY, date_to=dt.date(2024, 1, 1)),
                  Query(date_presence="unknown", date_to=DAY), Query(topic=("unsupported",)), Query(text="x" * 1001)):
            with self.subTest(query=q), self.assertRaises(CatalogError):
                self.catalog.query(q)


class CatalogCLITests(unittest.TestCase):
    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_cli_dataset_and_wrapper(self):
        fixture = str(ROOT / "examples/synthetic.json")
        code, out, err = self.invoke(["query", fixture, "--as-of", "2024-01-03", "--max-review-age", "0"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["matched_count"], 1)
        code, out, err = self.invoke(["query", fixture, "--dataset"])
        self.assertEqual(json.loads(out), json.loads(Path(fixture).read_text()))
        self.assertEqual(self.invoke(["query", fixture, "--dataset", "--text", "no match"])[0], 1)

    def test_module_entry_point(self):
        result = subprocess.run([sys.executable, "-m", "scripts.catalog", "query", "examples/synthetic.json"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["returned_count"], 1)

    def test_argument_errors_never_echo_user_values_or_paths(self):
        marker = "PRIVATE_MARKER_DO_NOT_ECHO"
        for args in (["query", marker], ["query", marker, "--as-of", marker], ["query", marker, "--limit", marker],
                     ["query", marker, "--as-of", "2024-1-03"], ["query", marker, "--as-of", "2023-02-29"],
                     ["query", marker, "--unknown-option", marker], ["query", marker, "--status", marker]):
            code, out, err = self.invoke(args)
            self.assertIn(code, (1, 2))
            self.assertEqual(out, "")
            self.assertNotIn(marker, err)
            self.assertNotIn("Traceback", err)

    def test_strict_json_and_bounded_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            for raw in (b'{"records":[],"records":[]}', b'{"schema_version":NaN}', b'\xff', b'{invalid'):
                path.write_bytes(raw)
                with self.assertRaises(CatalogError):
                    load_catalog([str(path)])
            path.write_text(json.dumps(document(record())))
            with patch("scripts.catalog.MAX_FILE_BYTES", 10), self.assertRaises(CatalogError):
                load_catalog([str(path)])
            self.assertEqual(len(load_catalog([str(path)]).records), 1)


if __name__ == "__main__":
    unittest.main()
