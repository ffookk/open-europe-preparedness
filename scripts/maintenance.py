"""Reproducible local catalog snapshots, structural diffs and evidence-review triage."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys

from .catalog import (ArgumentError, Catalog, CatalogError, SafeParser, load_catalog,
                      parse_date, parse_number, reject_duplicate_keys)
from .private_files import preflight_outputs, write_private_bytes

VERSION = 1
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
SNAPSHOT_POLICY = "catalog_snapshot_v1"
COMPARISON_POLICY = "catalog_diff_v1"
REVIEW_POLICY = "evidence_triage_v1"
REASONS = (
    "pending_review", "not_verified", "review_date_missing", "review_stale",
    "source_access_missing", "source_access_stale", "source_publication_missing",
    "source_locator_missing", "source_support_missing",
)
SNAPSHOT_LIMITATIONS = [
    "Content hashes identify consistency, not authenticity, authorship or factual truth.",
    "The validation cutoff is a structural context, not a historical policy snapshot or source review.",
    "Original claims, source evidence, uncertainty and review status are preserved without new research.",
]
REPORT_LIMITATIONS = [
    "Added and removed mean present or absent in these supplied snapshots, never adopted or repealed.",
    "Policy stage and evidence verification status are independent fields and changes remain separate.",
    "The review queue is structural triage, not source truth, legal advice or automatic certification.",
    "Dates and thresholds use fixed calendar days; unknown evidence dates are not inferred.",
    "Hashes check consistency only. A person can replace content and recompute every hash; no signature is verified.",
    "The full report embeds complete snapshot contents, including records hidden by filters.",
]
SELECTION_LIMITATIONS = [
    "This filtered packet is a review aid, not a verified full snapshot or a schema dataset.",
    "It preserves selected before/after records and evidence, but cannot establish authenticity or policy truth.",
    "Prepare corrections for independent human review; no source record has been changed automatically.",
]
_MISSING = object()


def canonical(value) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise CatalogError("Artifact cannot be represented as strict JSON.") from None


def fingerprint(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _date(value) -> dt.date:
    try:
        return parse_date(value)
    except (ValueError, TypeError):
        raise CatalogError("A fixed calendar date in YYYY-MM-DD format is required.") from None


def _keys(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise CatalogError("Artifact fields do not match the supported format.")


def _hashed(payload, key):
    return dict(payload, **{key: fingerprint(payload)})


def make_snapshot(document: dict, *, as_of: dt.date) -> dict:
    """Snapshot an exact schema collection; explicit empty collections are supported."""
    if type(as_of) is not dt.date:
        raise CatalogError("A fixed validation cutoff is required.")
    _keys(document, ("schema_version", "records"))
    if type(document["schema_version"]) is not int or document["schema_version"] != VERSION:
        raise CatalogError("Unsupported dataset schema version.")
    if document["records"] == []:
        records = []
    else:
        records = Catalog([document], as_of=as_of).records
    records.sort(key=lambda record: record["id"])
    normalized = {"schema_version": VERSION, "records": records}
    return _hashed({
        "schema_version": VERSION, "artifact_type": "catalog_snapshot", "snapshot_policy": SNAPSHOT_POLICY,
        "validation_as_of": as_of.isoformat(), "record_count": len(records),
        "dataset_sha256": fingerprint(normalized), "dataset": normalized,
        "record_hashes": [{"id": record["id"], "sha256": fingerprint(record)} for record in records],
        "limitations": list(SNAPSHOT_LIMITATIONS),
    }, "snapshot_sha256")


def verify_snapshot(snapshot: dict) -> dict:
    _keys(snapshot, ("schema_version", "artifact_type", "snapshot_policy", "validation_as_of", "record_count",
                     "dataset_sha256", "dataset", "record_hashes", "limitations", "snapshot_sha256"))
    expected = make_snapshot(snapshot["dataset"], as_of=_date(snapshot["validation_as_of"]))
    if canonical(snapshot) != canonical(expected):
        raise CatalogError("Snapshot metadata, ordering or fingerprints do not match recomputation.")
    return expected


def field_changes(before, after, path="") -> list[dict]:
    """Diff all leaves; JSON Pointer paths preserve ordered-list positions and nulls."""
    if (before is _MISSING and after in ({}, [])) or (after is _MISSING and before in ({}, [])):
        return [{"path": path, "before_present": before is not _MISSING, "after_present": after is not _MISSING,
                 "before": None if before is _MISSING else copy.deepcopy(before),
                 "after": None if after is _MISSING else copy.deepcopy(after)}]
    if before is not _MISSING and after is not _MISSING and canonical(before) == canonical(after):
        return []
    if (isinstance(before, dict) or before is _MISSING) and (isinstance(after, dict) or after is _MISSING):
        old = {} if before is _MISSING else before
        new = {} if after is _MISSING else after
        result = []
        for key in sorted(old.keys() | new.keys()):
            pointer = key.replace("~", "~0").replace("/", "~1")
            result.extend(field_changes(old.get(key, _MISSING), new.get(key, _MISSING), path + "/" + pointer))
        return result
    if (isinstance(before, list) or before is _MISSING) and (isinstance(after, list) or after is _MISSING):
        old = [] if before is _MISSING else before
        new = [] if after is _MISSING else after
        result = []
        for index in range(max(len(old), len(new))):
            result.extend(field_changes(old[index] if index < len(old) else _MISSING,
                                        new[index] if index < len(new) else _MISSING, path + "/" + str(index)))
        return result
    return [{"path": path, "before_present": before is not _MISSING, "after_present": after is not _MISSING,
             "before": None if before is _MISSING else copy.deepcopy(before),
             "after": None if after is _MISSING else copy.deepcopy(after)}]


def review_queue(snapshot: dict, *, as_of: dt.date, max_review_age=180, max_source_age=180) -> dict:
    checked = verify_snapshot(snapshot)
    if type(as_of) is not dt.date or as_of < _date(checked["validation_as_of"]):
        raise CatalogError("The triage cutoff must be on or after the snapshot validation cutoff.")
    for value in (max_review_age, max_source_age):
        if type(value) is not int or not 0 <= value <= 3652058:
            raise CatalogError("Age limits must be whole calendar days between 0 and 3652058.")
    entries = []
    counts = dict.fromkeys(REASONS, 0)
    for record in checked["dataset"]["records"]:
        reasons = []
        def add(code, path, *, age=None, limit=None):
            reasons.append({"code": code, "path": path, "age_days": age, "limit_days": limit})
            counts[code] += 1
        status = record["verification_status"]
        if status == "pending":
            add("pending_review", "/verification_status")
        if status != "verified":
            add("not_verified", "/verification_status")
        if record["last_verified_at"] is None:
            add("review_date_missing", "/last_verified_at")
        else:
            age = (as_of - _date(record["last_verified_at"])).days
            if age > max_review_age:
                add("review_stale", "/last_verified_at", age=age, limit=max_review_age)
        for index, source in enumerate(record["sources"]):
            prefix = "/sources/" + str(index)
            if source["accessed_at"] is None:
                add("source_access_missing", prefix + "/accessed_at")
            else:
                age = (as_of - _date(source["accessed_at"])).days
                if age > max_source_age:
                    add("source_access_stale", prefix + "/accessed_at", age=age, limit=max_source_age)
            for field, code in (("published_at", "source_publication_missing"), ("locator", "source_locator_missing"), ("supports", "source_support_missing")):
                if source[field] is None:
                    add(code, prefix + "/" + field)
        if reasons:
            reasons.sort(key=lambda item: (item["code"], item["path"]))
            entries.append({"id": record["id"], "record_sha256": fingerprint(record), "reasons": reasons})
    return {"review_policy": REVIEW_POLICY, "as_of": as_of.isoformat(), "max_review_age": max_review_age,
            "max_source_age": max_source_age, "catalog_count": checked["record_count"],
            "queued_count": len(entries), "reason_counts": counts, "entries": entries}


def compare_snapshots(before: dict, after: dict, *, as_of: dt.date | None = None,
                      max_review_age=180, max_source_age=180) -> dict:
    old = verify_snapshot(before)
    new = verify_snapshot(after)
    old_records = {r["id"]: r for r in old["dataset"]["records"]}
    new_records = {r["id"]: r for r in new["dataset"]["records"]}
    changes = []
    counts = dict.fromkeys(("added", "removed", "changed", "unchanged"), 0)
    for identifier in sorted(old_records.keys() | new_records.keys()):
        left, right = old_records.get(identifier, _MISSING), new_records.get(identifier, _MISSING)
        fields = field_changes(left, right)
        state = "added" if left is _MISSING else "removed" if right is _MISSING else "changed" if fields else "unchanged"
        counts[state] += 1
        changes.append({"id": identifier, "change": state, "field_changes": fields,
                        "policy_stage_changed": state == "changed" and left["policy_stage"] != right["policy_stage"],
                        "verification_status_changed": state == "changed" and left["verification_status"] != right["verification_status"],
                        "before_sha256": None if left is _MISSING else fingerprint(left),
                        "after_sha256": None if right is _MISSING else fingerprint(right)})
    cutoff = _date(new["validation_as_of"]) if as_of is None else as_of
    queue = review_queue(new, as_of=cutoff, max_review_age=max_review_age, max_source_age=max_source_age)
    metadata = [{"field": field, "before": old[field], "after": new[field]} for field in ("validation_as_of", "record_count") if old[field] != new[field]]
    return _hashed({"schema_version": VERSION, "artifact_type": "catalog_comparison", "comparison_policy": COMPARISON_POLICY,
                    "before_snapshot": old, "after_snapshot": new, "snapshot_metadata_changes": metadata,
                    "counts": counts, "changes": changes, "review_queue": queue,
                    "limitations": list(REPORT_LIMITATIONS)}, "report_sha256")


def review_snapshot(snapshot: dict, *, as_of: dt.date | None = None, max_review_age=180, max_source_age=180) -> dict:
    checked = verify_snapshot(snapshot)
    cutoff = _date(checked["validation_as_of"]) if as_of is None else as_of
    return _hashed({"schema_version": VERSION, "artifact_type": "catalog_review", "snapshot": checked,
                    "review_queue": review_queue(checked, as_of=cutoff, max_review_age=max_review_age, max_source_age=max_source_age),
                    "limitations": list(REPORT_LIMITATIONS)}, "report_sha256")


def verify_report(report: dict) -> dict:
    if not isinstance(report, dict):
        raise CatalogError("A maintenance report object is required.")
    kind = report.get("artifact_type")
    if kind == "catalog_comparison":
        _keys(report, ("schema_version", "artifact_type", "comparison_policy", "before_snapshot", "after_snapshot",
                       "snapshot_metadata_changes", "counts", "changes", "review_queue", "limitations", "report_sha256"))
    elif kind == "catalog_review":
        _keys(report, ("schema_version", "artifact_type", "snapshot", "review_queue", "limitations", "report_sha256"))
    else:
        raise CatalogError("Unsupported maintenance report type.")
    queue = report["review_queue"]
    _keys(queue, ("review_policy", "as_of", "max_review_age", "max_source_age", "catalog_count", "queued_count", "reason_counts", "entries"))
    options = dict(as_of=_date(queue["as_of"]), max_review_age=queue["max_review_age"], max_source_age=queue["max_source_age"])
    expected = compare_snapshots(report["before_snapshot"], report["after_snapshot"], **options) if kind == "catalog_comparison" else review_snapshot(report["snapshot"], **options)
    if canonical(report) != canonical(expected):
        raise CatalogError("Report metadata, changes, queue or fingerprints do not match recomputation.")
    return expected


def read_artifact(path) -> dict:
    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError
        return parsed
    def constant(_):
        raise ValueError
    def integer(value):
        if len(value.lstrip("-")) > 7:
            raise ValueError
        return int(value)
    try:
        # Preserve read-only links to regular inputs, but never wait for a FIFO
        # writer. Inspect the opened descriptor before reading any payload.
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(Path(path), flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise CatalogError("Artifact input must be a regular JSON file.")
            if metadata.st_size > MAX_ARTIFACT_BYTES:
                raise CatalogError("An artifact exceeds the 32 MiB input limit.")
            with os.fdopen(descriptor, "rb") as source:
                descriptor = None  # The stream now owns and closes the descriptor.
                raw = source.read(MAX_ARTIFACT_BYTES + 1)
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise CatalogError("An artifact exceeds the 32 MiB input limit.")
        return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys, parse_float=number, parse_int=integer, parse_constant=constant)
    except CatalogError:
        raise
    except (OSError, TypeError, ValueError, RecursionError, UnicodeError):
        raise CatalogError("Unable to read an artifact as bounded strict UTF-8 JSON.") from None


def encode_artifact(value) -> bytes:
    result = canonical(value) + b"\n"
    if len(result) > MAX_ARTIFACT_BYTES:
        raise CatalogError("An artifact exceeds the 32 MiB output limit.")
    return result


def build_parser():
    parser = SafeParser(description="Maintain catalog snapshots offline without changing source facts.")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=SafeParser)
    snapshot = commands.add_parser("snapshot", help="Create a content-bound complete catalog snapshot.")
    snapshot.add_argument("files", nargs="*")
    snapshot.add_argument("--empty", action="store_true", help="Explicitly create an empty collection; no input files allowed.")
    snapshot.add_argument("--as-of", type=parse_date, required=True)
    snapshot.add_argument("--output", default="private-output/catalog-snapshot.json")
    compare = commands.add_parser("compare", help="Verify two snapshots and compare complete records.")
    compare.add_argument("--before", required=True)
    compare.add_argument("--after", required=True)
    review = commands.add_parser("review", help="Verify a snapshot and build a structural review queue.")
    review.add_argument("snapshot")
    for command in (compare, review):
        command.add_argument("--as-of", type=parse_date, help="Triage day; defaults to the after/current snapshot cutoff.")
        command.add_argument("--max-review-age", type=parse_number, default=180)
        command.add_argument("--max-source-age", type=parse_number, default=180)
        command.add_argument("--output", default="private-output/change-review.json" if command is compare else "private-output/review-queue.json")
        command.add_argument("--html", help="Also create a new self-contained HTML maintenance report.")
    report = commands.add_parser("report", help="Reverify a saved comparison or review artifact and create offline HTML.")
    report.add_argument("artifact")
    report.add_argument("--output", default="private-output/maintenance.html")
    return parser


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "snapshot":
            if args.empty == bool(args.files):
                raise CatalogError("Provide input files or explicitly choose an empty snapshot.")
            records = [] if args.empty else load_catalog(args.files, as_of=args.as_of).records
            result = make_snapshot({"schema_version": VERSION, "records": records}, as_of=args.as_of)
        elif args.command in ("compare", "review"):
            options = dict(as_of=args.as_of, max_review_age=args.max_review_age, max_source_age=args.max_source_age)
            if args.command == "compare":
                result = compare_snapshots(read_artifact(args.before), read_artifact(args.after), **options)
            else:
                result = review_snapshot(read_artifact(args.snapshot), **options)
        else:
            result = verify_report(read_artifact(args.artifact))
        outputs = []
        if args.command != "report":
            outputs.append((args.output, encode_artifact(result)))
        html_path = args.output if args.command == "report" else getattr(args, "html", None)
        if html_path is not None:
            from .maintenance_html import render_report
            rendered = render_report(result).encode("utf-8")
            if len(rendered) > MAX_ARTIFACT_BYTES:
                raise CatalogError("The HTML report exceeds the 32 MiB output limit.")
            outputs.append((html_path, rendered))
        preflight_outputs([path for path, _ in outputs])
        for path, content in outputs:
            write_private_bytes(content, path)
        print("Created private maintenance output. Structural checks do not establish policy truth or authenticity.")
        return 0
    except ArgumentError as error:
        print(str(error), file=sys.stderr)
        return 2
    except CatalogError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, UnicodeError, RecursionError):
        print("Unable to complete maintenance output.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
