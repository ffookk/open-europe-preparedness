"""Fictional proposals exercise content binding, replay and private file boundaries."""
import copy
import datetime as dt
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from scripts import maintenance as m
from scripts import resolution as r
from scripts.catalog import CatalogError

ROOT = Path(__file__).resolve().parents[1]
DAY = dt.date(2024, 1, 5)
LATER = dt.date(2024, 1, 6)
MARKER = "FICTIONAL_PRIVATE_VALUE"


def record(name="a", pending=False):
    value = json.loads((ROOT / "examples/synthetic.json").read_text())["records"][0]
    value.update(id="synthetic-" + name, title="Fictional record " + name)
    if pending:
        value.update(verification_status="pending", last_verified_at=None)
        value["sources"][0].update(accessed_at=None, locator=None, supports=None)
    return value


def source(*records, cutoff=DAY):
    return m.make_snapshot({"schema_version": 1, "records": list(records)}, as_of=cutoff)


def complete(snapshot, action="keep", scope="all"):
    packet = r.prepare_packet(snapshot, scope=scope)
    for decision in packet["decisions"]:
        decision.update(action=action, rationale="Fictional proposal reason; no source research.")
    return packet


def rehash(value, key):
    value[key] = m.fingerprint({name: item for name, item in value.items() if name != key})


def invoke(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = r.main(args)
    return status, out.getvalue(), err.getvalue()


class PreparationTests(unittest.TestCase):
    def test_default_scope_selects_only_queue_and_retains_complete_evidence(self):
        snapshot = source(record("a"), record("b", pending=True))
        packet = r.prepare_packet(snapshot)
        self.assertEqual([item["id"] for item in packet["decisions"]], ["synthetic-b"])
        target = packet["basis"]["targets"][0]
        self.assertEqual(target["before"], snapshot["dataset"]["records"][1])
        self.assertIn("pending_review", {reason["code"] for reason in target["reasons"]})
        self.assertEqual(packet["decisions"][0]["action"], "pending")
        self.assertIsNone(packet["decisions"][0]["proposed_record"])
        with self.assertRaises(CatalogError):
            r.resolve_packet(snapshot, packet, as_of=DAY)

    def test_all_scope_includes_clear_records_and_is_order_independent(self):
        first = r.prepare_packet(source(record("b"), record("a")), scope="all")
        second = r.prepare_packet(source(record("a"), record("b")), scope="all")
        self.assertEqual(m.canonical(first), m.canonical(second))
        self.assertEqual(first["basis"]["targets"][0]["reasons"], [])
        self.assertEqual(len(first["decisions"]), 2)

    def test_age_boundaries_and_fixed_queue_cutoff(self):
        snapshot = source(record())
        self.assertEqual(r.prepare_packet(snapshot, max_review_age=2, max_source_age=2)["decisions"], [])
        stale = r.prepare_packet(snapshot, max_review_age=1, max_source_age=1)
        self.assertEqual(len(stale["decisions"]), 1)
        self.assertEqual(stale["basis"]["review_queue"]["as_of"], DAY.isoformat())
        self.assertTrue(all(reason["age_days"] == 2 for reason in stale["basis"]["targets"][0]["reasons"]))
        later = r.prepare_packet(snapshot, as_of=LATER, max_review_age=2)
        self.assertEqual(len(later["decisions"]), 1)

    def test_invalid_dates_ages_scopes_and_source_are_rejected(self):
        snapshot = source(record())
        options = [{"as_of": dt.date(2024, 1, 4)}, {"as_of": "2024-01-05"},
                   {"as_of": dt.datetime(2024, 1, 5)}, {"scope": MARKER}, {"scope": []},
                   {"max_review_age": True}, {"max_review_age": -1},
                   {"max_source_age": 3652059}, {"max_source_age": 1.0}]
        for option in options:
            with self.subTest(option=option), self.assertRaises(CatalogError):
                r.prepare_packet(snapshot, **option)
        snapshot["dataset"]["records"][0]["claim"] = MARKER
        with self.assertRaises(CatalogError):
            r.prepare_packet(snapshot)

    def test_preparation_never_mutates_or_aliases_source(self):
        snapshot = source(record("a", pending=True))
        original = copy.deepcopy(snapshot)
        packet = r.prepare_packet(snapshot)
        packet["basis"]["targets"][0]["before"]["limitations"].append(MARKER)
        packet["basis"]["targets"][0]["reasons"].clear()
        self.assertEqual(snapshot, original)


class ResolutionTests(unittest.TestCase):
    def test_keep_remove_replace_and_untouched_records_are_exact(self):
        snapshot = source(record("a", True), record("b", True), record("c", True), record("d"))
        packet = complete(snapshot, scope="queued")
        packet["decisions"][1]["action"] = "remove"
        proposal = copy.deepcopy(snapshot["dataset"]["records"][2])
        proposal["claim"] = "[SYNTHETIC] An explicit fictional correction, still pending."
        packet["decisions"][2].update(action="replace", proposed_record=proposal)
        result = r.resolve_packet(snapshot, packet, as_of=LATER)
        self.assertEqual(result["decision_counts"], {"keep": 1, "remove": 1, "replace": 1, "untouched": 1})
        comparison = result["comparison"]
        self.assertEqual(comparison["counts"], {"added": 0, "removed": 1, "changed": 1, "unchanged": 2})
        expected = [snapshot["dataset"]["records"][0], proposal, snapshot["dataset"]["records"][3]]
        self.assertEqual(comparison["after_snapshot"]["dataset"]["records"], expected)
        self.assertEqual(comparison["before_snapshot"], snapshot)
        self.assertEqual(comparison["changes"][2]["field_changes"][0]["path"], "/claim")
        self.assertIsNone(result["decision_summary"][1]["after_sha256"])
        self.assertEqual(r.verify_resolution(result), result)

    def test_explicit_keep_does_not_resolve_queue_or_promote_status(self):
        snapshot = source(record("a", True))
        result = r.resolve_packet(snapshot, complete(snapshot), as_of=DAY)
        self.assertEqual(result["comparison"]["after_snapshot"], snapshot)
        self.assertEqual(result["comparison"]["review_queue"]["queued_count"], 1)
        self.assertEqual(result["comparison"]["after_snapshot"]["dataset"]["records"][0]["verification_status"], "pending")

    def test_identical_replacement_is_explicit_noop(self):
        snapshot = source(record())
        packet = complete(snapshot)
        packet["decisions"][0].update(action="replace", proposed_record=copy.deepcopy(record()))
        result = r.resolve_packet(snapshot, packet, as_of=DAY)
        self.assertEqual(result["decision_counts"]["replace"], 1)
        self.assertEqual(result["comparison"]["counts"]["unchanged"], 1)
        self.assertEqual(result["comparison"]["after_snapshot"], snapshot)

    def test_empty_queue_preserves_every_record_and_empty_source_is_supported(self):
        for snapshot in (source(record()), source()):
            result = r.resolve_packet(snapshot, r.prepare_packet(snapshot), as_of=DAY)
            self.assertEqual(result["comparison"]["after_snapshot"], snapshot)
            self.assertEqual(result["decision_summary"], [])
            self.assertEqual(result["decision_counts"]["untouched"], snapshot["record_count"])

    def test_remove_all_allows_snapshot_but_refuses_empty_dataset_export(self):
        snapshot = source(record())
        result = r.resolve_packet(snapshot, complete(snapshot, action="remove"), as_of=DAY)
        self.assertEqual(r.export_resolution(result, kind="snapshot")["record_count"], 0)
        self.assertEqual(m.verify_report(r.export_resolution(result, kind="comparison"))["counts"]["removed"], 1)
        with self.assertRaises(CatalogError):
            r.export_resolution(result, kind="dataset")

    def test_result_is_deterministic_and_decision_order_is_normalized(self):
        snapshot = source(record("a"), record("b"))
        packet = complete(snapshot)
        first = r.resolve_packet(snapshot, packet, as_of=DAY)
        packet["decisions"].reverse()
        second = r.resolve_packet(snapshot, packet, as_of=DAY)
        self.assertEqual(m.canonical(first), m.canonical(second))
        self.assertEqual(first["decisions_sha256"], m.fingerprint(first["packet"]["decisions"]))

    def test_resolving_and_exporting_cannot_mutate_callers(self):
        snapshot = source(record()); packet = complete(snapshot)
        proposal = copy.deepcopy(record()); proposal["claim"] = "Fictional explicit revision."
        packet["decisions"][0].update(action="replace", proposed_record=proposal)
        original_source, original_packet = copy.deepcopy(snapshot), copy.deepcopy(packet)
        result = r.resolve_packet(snapshot, packet, as_of=LATER)
        exported = r.export_resolution(result, kind="dataset")
        exported["records"][0]["claim"] = MARKER
        result["comparison"]["before_snapshot"]["dataset"]["records"][0]["claim"] = MARKER
        self.assertEqual(snapshot, original_source)
        self.assertEqual(packet, original_packet)
        self.assertNotEqual(result["comparison"]["after_snapshot"]["dataset"]["records"][0]["claim"], MARKER)

    def test_candidate_date_must_follow_preparation_not_just_snapshot(self):
        snapshot = source(record()); packet = r.prepare_packet(snapshot, as_of=LATER)
        for cutoff in (DAY, "2024-01-06", dt.datetime(2024, 1, 6), None):
            with self.subTest(cutoff=cutoff), self.assertRaises(CatalogError):
                r.resolve_packet(snapshot, packet, as_of=cutoff)
        result = r.resolve_packet(snapshot, packet, as_of=LATER)
        self.assertEqual(result["comparison"]["after_snapshot"]["validation_as_of"], LATER.isoformat())

    def test_replacement_dates_are_validated_and_unknown_dates_preserved(self):
        snapshot = source(record("a", True)); packet = complete(snapshot)
        proposed = record("a")
        proposed["last_verified_at"] = "2024-01-06"
        proposed["sources"][0]["accessed_at"] = "2024-01-06"
        packet["decisions"][0].update(action="replace", proposed_record=proposed)
        with self.assertRaises(CatalogError):
            r.resolve_packet(snapshot, packet, as_of=DAY)
        result = r.resolve_packet(snapshot, packet, as_of=LATER)
        after = result["comparison"]["after_snapshot"]["dataset"]["records"][0]
        self.assertEqual(after, proposed)
        self.assertIsNone(after["dates"]["adopted_at"])
        self.assertTrue(result["comparison"]["changes"][0]["verification_status_changed"])
        self.assertFalse(result["comparison"]["changes"][0]["policy_stage_changed"])

    def test_changed_source_even_with_recomputed_hashes_is_stale_for_packet(self):
        snapshot = source(record()); packet = complete(snapshot)
        changed = record(); changed["claim"] = "Fictional changed source."
        for stale in (source(changed), source(record(), cutoff=LATER), source(record(), record("b"))):
            with self.subTest(stale=stale["record_count"]), self.assertRaises(CatalogError):
                r.resolve_packet(stale, packet, as_of=LATER)

    def test_immutable_basis_tampering_rejected_even_after_rehash(self):
        snapshot = source(record("a", True)); original = complete(snapshot)
        changes = [lambda p: p["basis"].update(source_dataset_sha256="0" * 64),
                   lambda p: p["basis"].update(source_snapshot_sha256="0" * 64),
                   lambda p: p["basis"]["targets"][0]["before"].update(claim=MARKER),
                   lambda p: p["basis"]["targets"][0].update(record_sha256="0" * 64),
                   lambda p: p["basis"]["targets"][0]["reasons"].clear(),
                   lambda p: p["basis"]["review_queue"].update(queued_count=99),
                   lambda p: p["basis"].update(extra=MARKER),
                   lambda p: p["basis"]["review_queue"].update(extra=MARKER)]
        for change in changes:
            packet = copy.deepcopy(original); change(packet); rehash(packet["basis"], "basis_sha256")
            with self.subTest(change=changes.index(change)), self.assertRaises(CatalogError):
                r.resolve_packet(snapshot, packet, as_of=DAY)

    def test_missing_duplicate_unknown_unselected_and_renamed_ids_rejected(self):
        snapshot = source(record("a", True), record("b", True), record("c"))
        original = complete(snapshot, scope="queued")
        changes = [lambda p: p["decisions"].pop(),
                   lambda p: p["decisions"].append(copy.deepcopy(p["decisions"][0])),
                   lambda p: p["decisions"][1].update(id="synthetic-a"),
                   lambda p: p["decisions"][0].update(id="synthetic-unknown"),
                   lambda p: p["decisions"][0].update(id="synthetic-c"),
                   lambda p: p["decisions"][0].update(id=[]),
                   lambda p: p["decisions"][0].update(action="replace", proposed_record=record("renamed"))]
        for change in changes:
            packet = copy.deepcopy(original); change(packet)
            with self.subTest(change=changes.index(change)), self.assertRaises(CatalogError):
                r.resolve_packet(snapshot, packet, as_of=DAY)

    def test_actions_closed_fields_rationale_and_proposal_shapes(self):
        snapshot = source(record()); original = complete(snapshot)
        invalid = [{"action": "add"}, {"action": "approve"}, {"action": []}, {"action": "pending"},
                   {"rationale": " "}, {"rationale": "a" * 2001}, {"rationale": None},
                   {"proposed_record": record()}, {"action": "remove", "proposed_record": record()},
                   {"action": "replace", "proposed_record": None}, {"extra": MARKER}]
        for update in invalid:
            packet = copy.deepcopy(original); packet["decisions"][0].update(update)
            with self.subTest(update=update), self.assertRaises(CatalogError):
                r.resolve_packet(snapshot, packet, as_of=DAY)
        for update in ({"schema_version": True}, {"schema_version": 1.0}, {"artifact_type": MARKER},
                       {"resolution_policy": MARKER}, {"limitations": []}, {"extra": MARKER}):
            packet = copy.deepcopy(original); packet.update(update)
            with self.subTest(update=update), self.assertRaises(CatalogError):
                r.resolve_packet(snapshot, packet, as_of=DAY)

    def test_invalid_resulting_records_rejected_without_raw_diagnostics(self):
        snapshot = source(record()); original = complete(snapshot)
        changes = [lambda p: p.pop("claim"), lambda p: p.update(verification_status=MARKER),
                   lambda p: p.update(policy_stage=MARKER), lambda p: p.update(extra=MARKER),
                   lambda p: p.update(sources=[]), lambda p: p.update(last_verified_at="2099-01-01"),
                   lambda p: p["sources"][0].update(url="https://example.invalid/?token=" + MARKER)]
        for change in changes:
            packet = copy.deepcopy(original); proposed = record(); change(proposed)
            packet["decisions"][0].update(action="replace", proposed_record=proposed)
            with self.subTest(change=changes.index(change)), self.assertRaises(CatalogError) as caught:
                r.resolve_packet(snapshot, packet, as_of=DAY)
            self.assertNotIn(MARKER, str(caught.exception))

    def test_rationale_changes_are_proposals_and_bound_in_final_artifact(self):
        snapshot = source(record()); packet = complete(snapshot)
        first = r.resolve_packet(snapshot, packet, as_of=DAY)
        packet["decisions"][0]["rationale"] = "Another explicitly supplied fictional reason."
        second = r.resolve_packet(snapshot, packet, as_of=DAY)
        self.assertEqual(first["comparison"], second["comparison"])
        self.assertNotEqual(first["decisions_sha256"], second["decisions_sha256"])
        self.assertNotEqual(first["resolution_sha256"], second["resolution_sha256"])


class ReplayTests(unittest.TestCase):
    def setUp(self):
        snapshot = source(record())
        self.result = r.resolve_packet(snapshot, complete(snapshot), as_of=DAY)

    def test_every_export_preserves_exact_reverifiable_content(self):
        comparison = self.result["comparison"]
        self.assertEqual(r.export_resolution(self.result, kind="snapshot"), comparison["after_snapshot"])
        self.assertEqual(r.export_resolution(self.result, kind="dataset"), comparison["after_snapshot"]["dataset"])
        self.assertEqual(r.export_resolution(self.result, kind="comparison"), comparison)
        with self.assertRaises(CatalogError):
            r.export_resolution(self.result, kind=MARKER)

    def test_outer_rehash_does_not_hide_modified_summary_or_proposal(self):
        changes = [lambda v: v["decision_counts"].update(keep=7),
                   lambda v: v["decision_summary"][0].update(after_sha256="0" * 64),
                   lambda v: v["packet"]["decisions"][0].update(rationale=MARKER),
                   lambda v: v["comparison"]["after_snapshot"]["dataset"]["records"][0].update(claim=MARKER),
                   lambda v: v["comparison"]["review_queue"].update(queued_count=1),
                   lambda v: v["comparison"].update(extra=MARKER),
                   lambda v: v.update(decisions_sha256="0" * 64),
                   lambda v: v.update(candidate_as_of="2024-01-06"),
                   lambda v: v.update(schema_version=True), lambda v: v.update(limitations=[]),
                   lambda v: v.update(extra=MARKER)]
        for change in changes:
            result = copy.deepcopy(self.result); change(result); rehash(result, "resolution_sha256")
            with self.subTest(change=changes.index(change)), self.assertRaises(CatalogError):
                r.verify_resolution(result)

    def test_malformed_and_reordered_embedded_context_rejected(self):
        for comparison in (None, [], {}, {"before_snapshot": None}):
            result = copy.deepcopy(self.result); result["comparison"] = comparison
            with self.subTest(comparison=comparison), self.assertRaises(CatalogError):
                r.verify_resolution(result)
        result = copy.deepcopy(self.result)
        result["comparison"]["counts"]["unchanged"] = 1.0
        rehash(result, "resolution_sha256")
        with self.assertRaises(CatalogError):
            r.verify_resolution(result)

    def test_new_snapshot_and_comparison_feed_existing_maintenance_workflow(self):
        from scripts.maintenance_html import render_report
        snapshot = r.export_resolution(self.result, kind="snapshot")
        self.assertEqual(m.verify_snapshot(snapshot), snapshot)
        review = m.review_snapshot(snapshot, as_of=LATER)
        self.assertEqual(m.verify_report(review), review)
        html = render_report(r.export_resolution(self.result, kind="comparison"))
        self.assertIn("catalog_comparison", html)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.snapshot = source(record())
        self.packet = complete(self.snapshot)
        self.source_path = self.directory / "source.json"
        self.packet_path = self.directory / "packet.json"
        self.source_path.write_bytes(m.encode_artifact(self.snapshot))
        self.packet_path.write_bytes(m.encode_artifact(self.packet))

    def command(self, name, output=None):
        args = [name, "--source", str(self.source_path), "--packet", str(self.packet_path), "--as-of", DAY.isoformat()]
        if output is not None:
            args += ["--output", str(output)]
        return args

    def test_end_to_end_all_commands_use_single_private_artifacts(self):
        draft = self.directory / "private" / "draft.json"
        code, out, err = invoke(["prepare", "--source", str(self.source_path), "--scope", "all", "--output", str(draft)])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(m.read_artifact(draft)["decisions"][0]["action"], "pending")
        self.assertEqual(draft.stat().st_mode & 0o777, 0o600)
        self.assertEqual(draft.parent.stat().st_mode & 0o777, 0o700)
        before = {p: p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        code, out, err = invoke(self.command("check"))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("keep=1 remove=0 replace=0 untouched=0", out)
        self.assertIn("No files written", out)
        self.assertEqual(before, {p: p.read_bytes() for p in self.directory.rglob("*") if p.is_file()})
        bundle = self.directory / "private" / "result.json"
        self.assertEqual(invoke(self.command("resolve", bundle))[0], 0)
        self.assertEqual(bundle.stat().st_mode & 0o777, 0o600)
        for kind in ("dataset", "snapshot", "comparison"):
            target = self.directory / (kind + ".json")
            self.assertEqual(invoke(["export", str(bundle), "--kind", kind, "--output", str(target)])[0], 0)
            self.assertEqual(m.read_artifact(target), r.export_resolution(m.read_artifact(bundle), kind=kind))
        self.assertEqual(m.read_artifact(self.source_path), self.snapshot)
        self.assertEqual(m.read_artifact(self.packet_path), self.packet)
        self.assertEqual(list(self.directory.rglob(".maintenance-*")), [])

    def test_invalid_proposal_never_creates_parent_or_output(self):
        self.packet["decisions"][0]["action"] = "pending"
        self.packet_path.write_bytes(m.encode_artifact(self.packet))
        output = self.directory / "not-created" / "result.json"
        self.assertEqual(invoke(self.command("resolve", output))[0], 1)
        self.assertFalse(output.parent.exists())

    def test_overwrite_source_packet_existing_and_hardlinks_refused(self):
        existing = self.directory / "existing.json"; existing.write_text("keep unchanged")
        link = self.directory / "hardlink.json"; os.link(existing, link)
        for output in (self.source_path, self.packet_path, existing, link):
            before = output.read_bytes()
            self.assertEqual(invoke(self.command("resolve", output))[0], 1)
            self.assertEqual(output.read_bytes(), before)

    def test_symlink_targets_parents_and_parent_traversal_refused(self):
        link = self.directory / "link.json"; link.symlink_to(self.source_path)
        directory_link = self.directory / "directory-link"; directory_link.symlink_to(self.directory, target_is_directory=True)
        for output in (link, directory_link / "new.json", self.directory / "new" / ".." / "result.json"):
            with self.subTest(output=output.name):
                self.assertEqual(invoke(self.command("resolve", output))[0], 1)
        self.assertEqual(m.read_artifact(self.source_path), self.snapshot)
        self.assertFalse((self.directory / "new.json").exists())

    def test_atomic_failure_leaves_no_partial_destination(self):
        output = self.directory / "result.json"
        with patch("scripts.private_files.os.fsync", side_effect=OSError(MARKER)):
            code, out, err = invoke(self.command("resolve", output))
        self.assertEqual(code, 1)
        self.assertNotIn(MARKER, out + err)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.directory.glob(".maintenance-*")), [])

    def test_atomic_race_preserves_a_newly_existing_destination(self):
        output = self.directory / "result.json"
        real_link = os.link
        def collide(src, dst, **kwargs):
            output.write_text("concurrent content")
            return real_link(src, dst, **kwargs)
        with patch("scripts.private_files.os.link", side_effect=collide):
            self.assertEqual(invoke(self.command("resolve", output))[0], 1)
        self.assertEqual(output.read_text(), "concurrent content")
        self.assertEqual(list(self.directory.glob(".maintenance-*")), [])

    def test_parse_errors_and_validation_diagnostics_never_echo_values_or_paths(self):
        private_path = self.directory / MARKER
        cases = [["check", "--source", str(private_path), "--packet", str(self.packet_path), "--as-of", DAY.isoformat()],
                 ["check", "--source", str(self.source_path), "--packet", str(self.packet_path), "--as-of", MARKER],
                 ["prepare", "--source", str(self.source_path), "--scope", MARKER],
                 ["export", str(private_path), "--kind", "dataset", "--output", str(private_path)]]
        for args in cases:
            code, out, err = invoke(args)
            self.assertIn(code, (1, 2))
            self.assertNotIn(MARKER, out + err)
            self.assertNotIn(str(self.directory), out + err)
        self.packet["decisions"][0].update(rationale=MARKER, action="replace", proposed_record={"id": "synthetic-a", "claim": MARKER})
        self.packet_path.write_bytes(m.encode_artifact(self.packet))
        code, out, err = invoke(self.command("check"))
        self.assertEqual(code, 1)
        self.assertNotIn(MARKER, out + err)

    def test_duplicate_json_keys_nonfinite_and_oversize_artifacts_refused(self):
        for raw in (b'{"secret": 1, "secret": 2}', b'{"value": NaN}', b'\xff', b'[]'):
            self.packet_path.write_bytes(raw)
            self.assertEqual(invoke(self.command("check"))[0], 1)
        self.packet_path.write_bytes(m.encode_artifact(self.packet))
        with patch.object(m, "MAX_ARTIFACT_BYTES", 20):
            self.assertEqual(invoke(self.command("check"))[0], 1)
        with patch.object(r, "MAX_DECISIONS", 0):
            self.assertEqual(invoke(self.command("check"))[0], 1)

    def test_output_size_checked_before_directory_creation(self):
        output = self.directory / "absent" / "result.json"
        # Both input artifacts fit but the full review bundle does not.
        limit = max(len(m.encode_artifact(self.snapshot)), len(m.encode_artifact(self.packet))) + 1
        with patch.object(m, "MAX_ARTIFACT_BYTES", limit):
            self.assertEqual(invoke(self.command("resolve", output))[0], 1)
        self.assertFalse(output.parent.exists())

    def test_nested_malformed_packets_have_fixed_errors_in_real_cli(self):
        changes = [lambda p: p.update(basis=None),
                   lambda p: p["basis"].update(review_queue=[]),
                   lambda p: p["basis"]["review_queue"].update(as_of={"secret": MARKER}),
                   lambda p: p["basis"]["review_queue"].update(max_review_age=[]),
                   lambda p: p["basis"].update(targets=None),
                   lambda p: p.update(decisions={"secret": MARKER}),
                   lambda p: p["decisions"].__setitem__(0, []),
                   lambda p: p["decisions"][0].update(action={"secret": MARKER})]
        for change in changes:
            packet = copy.deepcopy(self.packet); change(packet)
            self.packet_path.write_bytes(m.encode_artifact(packet))
            process = subprocess.run([sys.executable, "-m", "scripts.resolution", *self.command("check")],
                                     cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 1)
            self.assertNotIn("Traceback", process.stderr)
            self.assertNotIn(MARKER, process.stdout + process.stderr)
            self.assertNotIn(str(self.directory), process.stdout + process.stderr)

    def test_interrupt_returns_130_without_traceback_or_success_claim(self):
        for operation in ("read_artifact", "write_private_bytes"):
            with patch("scripts.resolution." + operation, side_effect=KeyboardInterrupt):
                code, out, err = invoke(self.command("resolve", self.directory / "result.json"))
            self.assertEqual(code, 130)
            self.assertEqual(out, "")
            self.assertIn("Resolution interrupted", err)
            self.assertNotIn("Traceback", err)
            self.assertNotIn(str(self.directory), err)

    def test_offline_processing_does_not_open_network_sockets(self):
        with patch("socket.socket", side_effect=AssertionError("No network allowed")):
            self.assertEqual(invoke(self.command("check"))[0], 0)


if __name__ == "__main__":
    unittest.main()
