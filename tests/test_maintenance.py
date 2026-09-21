"""Synthetic maintenance workflows; content fingerprints are not signatures."""
import copy
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from scripts.catalog import CatalogError
from scripts import maintenance as m
from scripts.private_files import preflight_outputs, write_private_bytes

ROOT = Path(__file__).resolve().parents[1]
DAY = dt.date(2024, 1, 5)


def record(name):
    result = json.loads((ROOT / "examples/synthetic.json").read_text())["records"][0]
    result.update(id="synthetic-" + name, title="Fictional record " + name)
    return result


def snapshot(*records, cutoff=DAY):
    return m.make_snapshot({"schema_version": 1, "records": list(records)}, as_of=cutoff)


def pair():
    a, b, c = record("a"), record("b"), record("c")
    before = snapshot(a, b, c)
    a.update(policy_stage="announced", verification_status="disputed", claim="Fictional revised claim with unresolved evidence.")
    a["sources"][0]["supports"] = "Fictional support changed."
    a["limitations"].append("Additional fictional uncertainty.")
    d = record("d")
    d.update(verification_status="pending", last_verified_at=None)
    for key in ("accessed_at", "published_at", "locator", "supports"):
        d["sources"][0][key] = None
    return before, snapshot(a, b, d, cutoff=dt.date(2024, 1, 6))


def invoke(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = m.main(args)
    return code, out.getvalue(), err.getvalue()


class SnapshotTests(unittest.TestCase):
    def test_hashes_are_deterministic_and_input_order_independent(self):
        a, b = record("a"), record("b")
        first, second = snapshot(a, b), snapshot(b, a)
        self.assertEqual(m.canonical(first), m.canonical(second))
        self.assertEqual(m.verify_snapshot(first), first)
        self.assertEqual(first["record_hashes"][0]["sha256"], m.fingerprint(a))
        self.assertEqual(first["dataset"]["records"][0], a)

    def test_cutoff_is_bound_but_separate_from_data_identity(self):
        first = snapshot(record("a"))
        second = snapshot(record("a"), cutoff=dt.date(2024, 1, 6))
        self.assertEqual(first["dataset_sha256"], second["dataset_sha256"])
        self.assertNotEqual(first["snapshot_sha256"], second["snapshot_sha256"])
        report = m.compare_snapshots(first, second)
        self.assertEqual(report["counts"], {"added": 0, "removed": 0, "changed": 0, "unchanged": 1})
        self.assertEqual(report["snapshot_metadata_changes"], [{"field": "validation_as_of", "before": "2024-01-05", "after": "2024-01-06"}])

    def test_tampered_metadata_values_types_order_and_evidence_are_rejected(self):
        original = snapshot(record("a"), record("b"))
        changes = [lambda s: s.update(record_count=True), lambda s: s.update(record_count=2.0),
                   lambda s: s.update(snapshot_policy="unknown"), lambda s: s.update(snapshot_sha256="0"*64),
                   lambda s: s.update(validation_as_of="2024-01-06"), lambda s: s["record_hashes"].reverse(),
                   lambda s: s["dataset"]["records"].reverse(), lambda s: s["limitations"].clear(),
                   lambda s: s["dataset"]["records"][0].update(claim="Changed fictional claim."),
                   lambda s: s.update(extra="PRIVATE_MARKER")]
        for change in changes:
            item = copy.deepcopy(original); change(item)
            with self.subTest(change=changes.index(change)), self.assertRaises(CatalogError):
                m.verify_snapshot(item)

    def test_rehashed_invalid_metadata_does_not_bypass_recomputation(self):
        item = snapshot(record("a"))
        item["record_count"] = 9
        item["snapshot_sha256"] = m.fingerprint({k:v for k,v in item.items() if k != "snapshot_sha256"})
        with self.assertRaises(CatalogError):
            m.verify_snapshot(item)

    def test_explicit_empty_collection_is_valid_snapshot_only(self):
        item = snapshot()
        self.assertEqual(item["record_count"], 0)
        self.assertEqual(m.verify_snapshot(item), item)
        self.assertEqual(m.compare_snapshots(snapshot(record("a")), item)["counts"]["removed"], 1)
        self.assertEqual(m.compare_snapshots(item, snapshot(record("a")))["counts"]["added"], 1)

    def test_schema_and_duplicate_ids_are_still_enforced(self):
        for document in ({"schema_version": True, "records": []}, {"schema_version": 1, "records": {}},
                         {"schema_version": 1, "records": [record("a"), record("a")]},
                         {"schema_version": 1, "records": [record("a")], "extra": None}):
            with self.assertRaises(CatalogError):
                m.make_snapshot(document, as_of=DAY)
        with self.assertRaises(CatalogError):
            snapshot(record("a"), cutoff=dt.date(2024, 1, 2))

    def test_returns_do_not_mutate_input_records(self):
        original = record("a"); item = snapshot(original)
        item["dataset"]["records"][0]["claim"] = "Changed independently."
        self.assertNotEqual(original["claim"], item["dataset"]["records"][0]["claim"])


class DiffTests(unittest.TestCase):
    def test_classifications_and_independent_status_transitions(self):
        before, after = pair(); result = m.compare_snapshots(before, after)
        self.assertEqual(result["counts"], {"added": 1, "removed": 1, "changed": 1, "unchanged": 1})
        row = result["changes"][0]
        self.assertTrue(row["policy_stage_changed"])
        self.assertTrue(row["verification_status_changed"])
        paths = {change["path"] for change in row["field_changes"]}
        self.assertTrue({"/claim", "/policy_stage", "/verification_status", "/sources/0/supports", "/limitations/2"} <= paths)
        self.assertEqual(m.verify_report(result), result)

    def test_full_added_and_removed_records_have_leaf_changes(self):
        result = m.compare_snapshots(*pair())
        for row in result["changes"]:
            if row["change"] in ("added", "removed"):
                self.assertTrue(any(change["path"] == "/sources/0/url" for change in row["field_changes"]))
                self.assertTrue(all(change["after_present"] == (row["change"] == "added") for change in row["field_changes"]))
                self.assertFalse(row["policy_stage_changed"])

    def test_absent_null_and_empty_containers_remain_distinct(self):
        for value in (None, [], {}):
            added = m.field_changes({}, {"field": value})
            removed = m.field_changes({"field": value}, {})
            self.assertEqual(len(added), 1)
            self.assertFalse(added[0]["before_present"])
            self.assertTrue(added[0]["after_present"])
            self.assertEqual(added[0]["after"], value)
            self.assertTrue(removed[0]["before_present"])
            self.assertFalse(removed[0]["after_present"])
        self.assertEqual(m.field_changes({"field": None}, {"field": None}), [])

    def test_json_pointer_escaping_and_ordered_lists(self):
        result = m.field_changes({"a/b~": ["old", None]}, {"a/b~": [None, "new"]})
        self.assertEqual([item["path"] for item in result], ["/a~1b~0/0", "/a~1b~0/1"])
        self.assertEqual(m.field_changes({}, {}), [])

    def test_comparison_rejects_summary_tampering_even_with_new_hash(self):
        report = m.compare_snapshots(*pair())
        changes = [lambda r: r["counts"].update(unchanged=9), lambda r: r["changes"].pop(),
                   lambda r: r["changes"][0].update(policy_stage_changed=False),
                   lambda r: r["review_queue"]["reason_counts"].update(pending_review=9),
                   lambda r: r["snapshot_metadata_changes"].clear(), lambda r: r["limitations"].clear()]
        for change in changes:
            item = copy.deepcopy(report); change(item)
            item["report_sha256"] = m.fingerprint({k:v for k,v in item.items() if k != "report_sha256"})
            with self.subTest(change=changes.index(change)), self.assertRaises(CatalogError):
                m.verify_report(item)

    def test_snapshot_evidence_change_with_forged_summary_is_rejected(self):
        item = m.compare_snapshots(*pair())
        item["before_snapshot"]["dataset"]["records"][0]["sources"][0]["supports"] = "Tampered fictional support."
        with self.assertRaises(CatalogError):
            m.verify_report(item)

    def test_identical_empty_and_reversed_comparisons(self):
        before, after = pair()
        forward, backward = m.compare_snapshots(before, after), m.compare_snapshots(after, before)
        self.assertEqual(forward["counts"]["added"], backward["counts"]["removed"])
        identical = m.compare_snapshots(before, before)
        self.assertEqual(identical["counts"]["unchanged"], 3)
        empty = m.compare_snapshots(snapshot(), snapshot())
        self.assertEqual(sum(empty["counts"].values()), 0)
        self.assertEqual(empty["review_queue"]["entries"], [])


class QueueTests(unittest.TestCase):
    def test_review_and_access_thresholds_are_inclusive(self):
        item = snapshot(record("a"))
        equal = m.review_queue(item, as_of=DAY, max_review_age=2, max_source_age=2)
        self.assertEqual(equal["entries"], [])
        stale = m.review_queue(item, as_of=DAY, max_review_age=1, max_source_age=1)
        self.assertEqual({r["code"] for r in stale["entries"][0]["reasons"]}, {"review_stale", "source_access_stale"})
        self.assertTrue(all(r["age_days"] == 2 and r["limit_days"] == 1 for r in stale["entries"][0]["reasons"]))

    def test_zero_age_and_leap_day_boundary(self):
        item = record("a"); item["last_verified_at"] = "2024-02-29"; item["sources"][0]["accessed_at"] = "2024-02-29"
        snap = snapshot(item, cutoff=dt.date(2024, 2, 29))
        self.assertEqual(m.review_queue(snap, as_of=dt.date(2024, 2, 29), max_review_age=0, max_source_age=0)["entries"], [])
        self.assertEqual(m.review_queue(snap, as_of=dt.date(2024, 3, 1), max_review_age=0)["entries"][0]["reasons"][0]["age_days"], 1)

    def test_pending_unknown_and_not_verified_reasons_are_independent(self):
        item = m.review_snapshot(pair()[1]); queue = item["review_queue"]
        pending = next(entry for entry in queue["entries"] if entry["id"] == "synthetic-d")
        self.assertEqual({r["code"] for r in pending["reasons"]}, {"pending_review", "not_verified", "review_date_missing", "source_access_missing", "source_publication_missing", "source_locator_missing", "source_support_missing"})
        self.assertTrue(all(r["age_days"] is None for r in pending["reasons"]))
        self.assertEqual(queue["reason_counts"]["not_verified"], 2)
        self.assertEqual(queue["queued_count"], 2)
        self.assertEqual(m.verify_report(item), item)

    def test_source_reasons_preserve_indices_and_can_overlap(self):
        item = record("a"); item["sources"].append(copy.deepcopy(item["sources"][0]))
        queue = m.review_queue(snapshot(item), as_of=DAY, max_review_age=10, max_source_age=0)
        self.assertEqual(queue["queued_count"], 1)
        self.assertEqual(queue["reason_counts"]["source_access_stale"], 2)
        self.assertEqual([r["path"] for r in queue["entries"][0]["reasons"]], ["/sources/0/accessed_at", "/sources/1/accessed_at"])

    def test_policy_stage_never_drives_triage(self):
        item = record("a"); before = m.review_queue(snapshot(item), as_of=DAY)
        item["policy_stage"] = "unknown"
        self.assertEqual(m.review_queue(snapshot(item), as_of=DAY), before)

    def test_cutoffs_and_threshold_types_are_validated(self):
        for options in ({"as_of": dt.date(2024, 1, 4)}, {"as_of": "2024-01-05"}, {"as_of": DAY, "max_review_age": True}, {"as_of": DAY, "max_source_age": -1}):
            with self.assertRaises(CatalogError):
                m.review_queue(snapshot(record("a")), **options)


class ArtifactIOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def save(self, name, value):
        path = self.root / name; path.write_bytes(m.encode_artifact(value)); return path

    def test_complete_cli_snapshot_compare_review_and_report_workflow(self):
        before, after = pair()
        a, b = self.save("before.json", before), self.save("after.json", after)
        output, html = self.root / "comparison.json", self.root / "comparison.html"
        args = ["compare", "--before", str(a), "--after", str(b), "--output", str(output), "--html", str(html)]
        self.assertEqual(invoke(args)[0], 0)
        self.assertEqual(m.verify_report(m.read_artifact(output)), m.compare_snapshots(before, after))
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertTrue(html.read_text().startswith("<!doctype html>"))
        self.assertEqual(invoke(["report", str(output), "--output", str(self.root / "again.html")])[0], 0)
        self.assertEqual(invoke(["review", str(b), "--output", str(self.root / "queue.json")])[0], 0)
        empty = self.root / "empty.json"
        self.assertEqual(invoke(["snapshot", "--empty", "--as-of", "2024-01-05", "--output", str(empty)])[0], 0)
        self.assertEqual(m.verify_snapshot(m.read_artifact(empty))["record_count"], 0)
        full = self.root / "full.json"
        self.assertEqual(invoke(["snapshot", str(ROOT / "examples/synthetic.json"), "--as-of", "2024-01-05", "--output", str(full)])[0], 0)
        self.assertEqual(m.verify_snapshot(m.read_artifact(full))["record_count"], 1)

    def test_preflight_all_destinations_prevents_partial_output(self):
        source = self.save("snapshot.json", snapshot(record("a")))
        output, html = self.root / "new.json", self.root / "existing.html"
        html.write_text("Existing fictional artifact.")
        self.assertEqual(invoke(["review", str(source), "--output", str(output), "--html", str(html)])[0], 1)
        self.assertFalse(output.exists())
        self.assertEqual(html.read_text(), "Existing fictional artifact.")
        self.assertEqual(invoke(["review", str(source), "--output", str(source)])[0], 1)
        self.assertEqual(m.verify_snapshot(m.read_artifact(source))["record_count"], 1)

    def test_bad_arguments_and_inputs_do_not_echo_sensitive_values(self):
        marker = "PRIVATE_MARKER_DO_NOT_ECHO"
        for args in (["review", marker], ["snapshot", "--empty", "--as-of", marker], ["review", marker, "--max-source-age", marker],
                     ["snapshot", "--empty", "--as-of", "2023-02-29"], ["review", marker, "--unknown", marker]):
            code, out, err = invoke(args)
            self.assertIn(code, (1, 2)); self.assertEqual(out, ""); self.assertNotIn(marker, err); self.assertNotIn("Traceback", err)

    def test_strict_decoding_limits_and_nonfinite_numbers(self):
        path = self.root / "bad.json"
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e400}', b'{"a":12345678}', b'\xff', b'{bad'):
            path.write_bytes(raw)
            with self.assertRaises(CatalogError): m.read_artifact(path)
        path.write_bytes(b" " * 11)
        with patch.object(m, "MAX_ARTIFACT_BYTES", 10), self.assertRaises(CatalogError): m.read_artifact(path)
        with patch.object(m, "MAX_ARTIFACT_BYTES", 10), self.assertRaises(CatalogError): m.encode_artifact(snapshot())

    def test_failed_validation_creates_no_outputs(self):
        source = self.save("invalid.json", {"schema_version": 1})
        output = self.root / "new" / "report.json"
        self.assertEqual(invoke(["review", str(source), "--output", str(output)])[0], 1)
        self.assertFalse(output.parent.exists())

    def test_private_writer_collision_alias_and_permissions(self):
        target = self.root / "new" / "artifact.json"; write_private_bytes(b"fixture", target)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
        with self.assertRaises(CatalogError): write_private_bytes(b"replace", target)
        alias = self.root / "alias"; alias.symlink_to(target.parent, target_is_directory=True)
        with self.assertRaises(CatalogError): write_private_bytes(b"fixture", alias / "output.json")
        collision = self.root / ".maintenance-fixed.tmp"; collision.write_text("Keep this.")
        with patch("scripts.private_files.secrets.token_hex", return_value="fixed"), self.assertRaises(CatalogError):
            write_private_bytes(b"new", self.root / "fresh.json")
        self.assertEqual(collision.read_text(), "Keep this.")
        self.assertEqual(target.read_bytes(), b"fixture")

    def test_preflight_rejects_duplicate_overlapping_and_symlink_targets(self):
        path = self.root / "new"
        for outputs in ([path, path], [path, path / "nested"], [path / ".." / "outside"]):
            with self.assertRaises(CatalogError): preflight_outputs(outputs)
        link = self.root / "alias"; link.symlink_to(self.root / "missing")
        with self.assertRaises(CatalogError): preflight_outputs([link])

    def test_held_directory_does_not_follow_replacement_alias(self):
        parent = self.root / "parent"; parent.mkdir()
        other = self.root / "other"; other.mkdir()
        moved = self.root / "moved"; original = os.link
        def replacing_link(source, target, **kwargs):
            parent.rename(moved); parent.symlink_to(other, target_is_directory=True)
            return original(source, target, **kwargs)
        with patch("scripts.private_files.os.link", side_effect=replacing_link):
            write_private_bytes(b"fixture", parent / "out.json")
        self.assertEqual((moved / "out.json").read_bytes(), b"fixture")
        self.assertEqual(list(other.iterdir()), [])

    def test_cleanup_failure_diagnostic_is_fixed(self):
        with patch("scripts.private_files.os.unlink", side_effect=OSError("PRIVATE_MARKER")):
            with self.assertRaisesRegex(CatalogError, "^Unable to finish private artifact cleanup[.]$"):
                write_private_bytes(b"fixture", self.root / "output.json")


if __name__ == "__main__":
    unittest.main()
