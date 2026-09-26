"""Reduced summaries use fictional records and never imply anonymous data."""
import copy
import io
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from scripts import maintenance as m, resolution as r
from scripts.catalog import CatalogError
from test_resolution import DAY, LATER, complete, record, source


def summary(bundle):
    return r.export_resolution(bundle, kind="summary")


def bundle_for(*records, scope="all", cutoff=DAY):
    snapshot = source(*records)
    return r.resolve_packet(snapshot, complete(snapshot, scope=scope), as_of=cutoff)


class SummaryTests(unittest.TestCase):
    def test_mixed_decisions_have_independently_expected_counts(self):
        snapshot = source(record("a", True), record("b", True), record("c", True), record("d"))
        packet = complete(snapshot, scope="queued")
        packet["decisions"][1]["action"] = "remove"
        proposed = record("c")
        proposed["policy_stage"] = "announced"
        packet["decisions"][2].update(action="replace", proposed_record=proposed)
        report = summary(r.resolve_packet(snapshot, packet, as_of=DAY))
        self.assertEqual(report["record_counts"], {"before": 4, "after": 3})
        self.assertEqual(report["record_types"], {"before": {"real": 0, "synthetic": 4}, "after": {"real": 0, "synthetic": 3}})
        self.assertEqual(report["decision_counts"], {"keep": 1, "remove": 1, "replace": 1, "untouched": 1})
        self.assertEqual(report["change_counts"], {"added": 0, "removed": 1, "changed": 1, "unchanged": 2})
        self.assertEqual(report["transition_counts"], {"policy_stage": 1, "verification_status": 1})
        self.assertFalse(report["queue_cutoff_changed"])
        expected_before = {reason: 0 for reason in m.REASONS}
        expected_after = dict(expected_before)
        for reason in ("pending_review", "not_verified", "review_date_missing", "source_access_missing", "source_locator_missing", "source_support_missing"):
            expected_before[reason] = 3
            expected_after[reason] = 1
        self.assertEqual(report["review_queue"], {"before": {"queued_records": 3, "reason_counts": expected_before}, "after": {"queued_records": 1, "reason_counts": expected_after}})

    def test_keep_does_not_imply_review_and_identical_replace_is_not_a_change(self):
        snapshot = source(record("a", True), record("b", True))
        packet = complete(snapshot)
        packet["decisions"][1].update(action="replace", proposed_record=record("b", True))
        report = summary(r.resolve_packet(snapshot, packet, as_of=DAY))
        self.assertEqual(report["decision_counts"], {"keep": 1, "remove": 0, "replace": 1, "untouched": 0})
        self.assertEqual(report["change_counts"]["unchanged"], 2)
        self.assertEqual(report["transition_counts"], {"policy_stage": 0, "verification_status": 0})
        self.assertEqual(report["review_queue"]["after"]["queued_records"], 2)

    def test_empty_noop_and_remove_all_are_supported_without_dataset_export(self):
        empty = summary(bundle_for())
        self.assertEqual(empty["record_counts"], {"before": 0, "after": 0})
        self.assertTrue(all(value == 0 for value in empty["decision_counts"].values()))
        snapshot = source(record())
        removed = r.resolve_packet(snapshot, complete(snapshot, action="remove"), as_of=DAY)
        report = summary(removed)
        self.assertEqual(report["record_counts"], {"before": 1, "after": 0})
        self.assertEqual(report["change_counts"]["removed"], 1)
        self.assertEqual(report["transition_counts"], {"policy_stage": 0, "verification_status": 0})
        with self.assertRaises(CatalogError):
            r.export_resolution(removed, kind="dataset")

    def test_record_types_count_stored_labels_not_independent_authenticity(self):
        labelled = record("fictional-label")
        labelled.update(id="fictional-real-label", record_type="real")
        # This is a fictional format test; this URL is never fetched.
        labelled["sources"][0]["url"] = "https://www.iana.org/fictional-format-fixture"
        report = summary(bundle_for(labelled, record()))
        self.assertEqual(report["record_types"], {"before": {"real": 1, "synthetic": 1}, "after": {"real": 1, "synthetic": 1}})

    def test_cutoff_change_explains_new_reasons_without_record_changes(self):
        snapshot = source(record())
        packet = r.prepare_packet(snapshot, max_review_age=2, max_source_age=2)
        report = summary(r.resolve_packet(snapshot, packet, as_of=LATER))
        self.assertTrue(report["queue_cutoff_changed"])
        self.assertEqual(report["review_queue"]["before"]["queued_records"], 0)
        self.assertEqual(report["review_queue"]["after"]["queued_records"], 1)
        self.assertEqual(report["review_queue"]["after"]["reason_counts"]["review_stale"], 1)
        self.assertEqual(report["review_queue"]["after"]["reason_counts"]["source_access_stale"], 1)
        self.assertEqual(report["change_counts"]["changed"], 0)
        self.assertEqual(report["decision_counts"]["untouched"], 1)
        prepared_later = r.prepare_packet(snapshot, as_of=LATER)
        same_queue_cutoff = summary(r.resolve_packet(snapshot, prepared_later, as_of=LATER))
        self.assertFalse(same_queue_cutoff["queue_cutoff_changed"])

    def test_reason_occurrences_overlap_and_are_not_record_totals(self):
        item = record("a", True)
        item["sources"].append(copy.deepcopy(item["sources"][0]))
        report = summary(bundle_for(item))
        queue = report["review_queue"]["after"]
        self.assertEqual(queue["queued_records"], 1)
        self.assertEqual(queue["reason_counts"]["source_locator_missing"], 2)
        self.assertEqual(queue["reason_counts"]["pending_review"], 1)
        self.assertGreater(sum(queue["reason_counts"].values()), queue["queued_records"])

    def test_closed_schema_contains_only_fixed_strings_counts_and_one_boolean(self):
        report = summary(bundle_for(record("a", True)))
        self.assertEqual(set(report), {"schema_version", "artifact_type", "summary_policy", "record_counts", "record_types", "decision_counts", "change_counts", "transition_counts", "review_queue", "queue_cutoff_changed", "limitations"})
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["artifact_type"], "catalog_resolution_summary")
        self.assertEqual(report["summary_policy"], "catalog_resolution_summary_v1")
        allowed = {"real", "synthetic", "before", "after", "keep", "remove", "replace", "untouched", "added", "removed", "changed", "unchanged", "policy_stage", "verification_status", "queued_records", "reason_counts", *m.REASONS}
        for key in ("record_counts", "record_types", "decision_counts", "change_counts", "transition_counts", "review_queue"):
            pending = [report[key]]
            while pending:
                item = pending.pop()
                if isinstance(item, dict):
                    self.assertLessEqual(set(item), allowed)
                    pending.extend(item.values())
                else:
                    self.assertIs(type(item), int)
                    self.assertGreaterEqual(item, 0)
        self.assertIs(type(report["queue_cutoff_changed"]), bool)
        self.assertEqual(report["limitations"], r.SUMMARY_LIMITATIONS)
        self.assertEqual(m.read_artifact(self.write_temporary(report)), report)

    def write_temporary(self, document):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "summary.json"
        path.write_bytes(m.encode_artifact(document))
        return path

    def test_all_flexible_record_fields_rationale_ids_dates_and_digests_are_omitted(self):
        marker = "FICTIONAL_PRIVATE_CANARY"
        item = record("private-canary")
        for field in ("jurisdiction", "title", "claim", "scope", "verification_note"):
            item[field] = marker + " " + field
        for field in ("publisher", "title", "locator", "supports"):
            item["sources"][0][field] = marker + " " + field
        item["sources"][0]["url"] = "https://example.invalid/" + marker
        item["limitations"] = [marker + " limitation"]
        item["change_history"][0]["summary"] = marker + " history"
        snapshot = source(item)
        packet = complete(snapshot)
        packet["decisions"][0]["rationale"] = marker + " rationale"
        proposed = copy.deepcopy(item)
        proposed["claim"] += " changed"
        packet["decisions"][0].update(action="replace", proposed_record=proposed)
        bundle = r.resolve_packet(snapshot, packet, as_of=DAY)
        text = m.canonical(summary(bundle)).decode()
        for forbidden in (marker, item["id"], "https://", "2024-", snapshot["dataset_sha256"], snapshot["snapshot_sha256"], bundle["resolution_sha256"], bundle["decisions_sha256"], "/claim"):
            self.assertNotIn(forbidden, text)
        self.assertNotRegex(text, r"\b[0-9a-f]{64}\b")

    def test_different_private_contents_with_same_counts_deliberately_share_summary(self):
        first = record("first-private-id")
        second = record("different-private-id")
        second["claim"] = "Different fictional private statement."
        second["verification_note"] = "Different fictional review declaration."
        left, right = bundle_for(first), bundle_for(second)
        self.assertNotEqual(left["resolution_sha256"], right["resolution_sha256"])
        self.assertEqual(m.canonical(summary(left)), m.canonical(summary(right)))
        with self.assertRaises(CatalogError):
            r.verify_resolution(summary(left))

    def test_full_replay_rejects_tampering_even_in_fields_summary_would_omit(self):
        original = bundle_for(record())
        mutations = [lambda v: v["packet"]["decisions"][0].update(rationale="Changed private rationale."),
                     lambda v: v["comparison"]["after_snapshot"]["dataset"]["records"][0].update(title="Changed private title."),
                     lambda v: v["decision_counts"].update(keep=True),
                     lambda v: v["decision_counts"].update(keep=1.0),
                     lambda v: v["decision_counts"].update(keep=10001),
                     lambda v: v["comparison"]["counts"].update(changed=-1),
                     lambda v: v["comparison"]["changes"][0].update(policy_stage_changed=1),
                     lambda v: v["comparison"]["review_queue"].update(queued_count=10001),
                     lambda v: v["comparison"]["review_queue"]["reason_counts"].update(extra=0)]
        for mutate in mutations:
            altered = copy.deepcopy(original); mutate(altered)
            altered["resolution_sha256"] = m.fingerprint({key: value for key, value in altered.items() if key != "resolution_sha256"})
            with self.subTest(mutation=mutations.index(mutate)), self.assertRaises(CatalogError):
                summary(altered)
        for malformed in (None, [], True, {}, {"comparison": None}):
            with self.subTest(malformed=malformed), self.assertRaises(CatalogError):
                summary(malformed)

    def test_projection_does_not_mutate_or_alias_verified_source(self):
        original = bundle_for(record())
        frozen = m.canonical(original)
        exported = summary(original)
        exported["decision_counts"]["keep"] = 99
        exported["review_queue"]["before"]["reason_counts"].clear()
        exported["limitations"].clear()
        self.assertEqual(m.canonical(original), frozen)
        self.assertEqual(summary(original)["decision_counts"]["keep"], 1)


class SummaryCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.bundle = bundle_for(record())
        self.input = self.directory / "bundle.json"
        self.input.write_bytes(m.encode_artifact(self.bundle))
        self.output = self.directory / "private" / "summary.json"

    def invoke(self, output=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = r.main(["export", str(self.input), "--kind", "summary", "--output", str(self.output if output is None else output)])
        return code, out.getvalue(), err.getvalue()

    def test_private_cli_roundtrip_no_clobber_and_symlink_rejection(self):
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(m.read_artifact(self.output), summary(self.bundle))
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.output.parent.stat().st_mode & 0o777, 0o700)
        before = self.output.read_bytes()
        self.assertEqual(self.invoke()[0], 1)
        self.assertEqual(self.output.read_bytes(), before)
        self.assertEqual(self.invoke(self.input)[0], 1)
        self.assertEqual(m.read_artifact(self.input), self.bundle)
        alias = self.directory / "alias"; alias.symlink_to(self.output.parent, target_is_directory=True)
        self.assertEqual(self.invoke(alias / "other.json")[0], 1)
        self.assertFalse((self.output.parent / "other.json").exists())

    def test_malformed_tampered_or_oversized_source_never_creates_output(self):
        invalid = copy.deepcopy(self.bundle)
        invalid["packet"]["decisions"][0]["rationale"] = "FICTIONAL_PRIVATE_CANARY"
        for value in (invalid, None, {"FICTIONAL_PRIVATE_CANARY": 1}):
            self.input.write_bytes(m.encode_artifact(value))
            code, out, err = self.invoke()
            self.assertEqual(code, 1)
            self.assertNotIn("FICTIONAL_PRIVATE_CANARY", out + err)
            self.assertNotIn(str(self.directory), out + err)
            self.assertFalse(self.output.parent.exists())
        self.input.write_bytes(m.encode_artifact(self.bundle))
        with patch.object(m, "MAX_ARTIFACT_BYTES", len(self.input.read_bytes()) - 1):
            self.assertEqual(self.invoke()[0], 1)
        self.assertFalse(self.output.parent.exists())


if __name__ == "__main__":
    unittest.main()
