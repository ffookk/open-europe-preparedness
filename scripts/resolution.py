"""Content-bound, offline proposals that never modify the source catalog."""
from __future__ import annotations

import copy
import datetime as dt
import sys

from .catalog import ArgumentError, CatalogError, SafeParser, parse_date, parse_number
from .maintenance import (
    VERSION, _date, _hashed, _keys, canonical, compare_snapshots, encode_artifact,
    fingerprint, make_snapshot, read_artifact, review_queue, verify_snapshot,
)
from .private_files import preflight_outputs, write_private_bytes

POLICY = "catalog_resolution_v1"
MAX_RATIONALE = 2000
MAX_DECISIONS = 10000
ACTIONS = ("pending", "keep", "remove", "replace")
LIMITATIONS = [
    "This is an offline proposal, not source research, human approval or factual certification.",
    "Hashes bind supplied content, not authenticity. Editable decisions have no signature or authenticated author.",
    "Keep preserves a record without approving it; remove means absence from a candidate, never policy repeal.",
    "Replacement fields are supplied explicitly. No review status, date, evidence or history is promoted automatically.",
    "Full records and rationale remain in private artifacts. These outputs are not redacted or safe to publish automatically.",
]


def _basis(source, *, as_of, scope, max_review_age, max_source_age):
    if not isinstance(scope, str) or scope not in ("queued", "all"):
        raise CatalogError("Resolution scope must be queued or all.")
    queue = review_queue(source, as_of=as_of, max_review_age=max_review_age,
                         max_source_age=max_source_age)
    reasons = {entry["id"]: entry["reasons"] for entry in queue["entries"]}
    targets = [{"id": record["id"], "record_sha256": fingerprint(record),
                "before": copy.deepcopy(record), "reasons": reasons.get(record["id"], [])}
               for record in source["dataset"]["records"]
               if scope == "all" or record["id"] in reasons]
    return _hashed({
        "source_snapshot_sha256": source["snapshot_sha256"],
        "source_dataset_sha256": source["dataset_sha256"],
        "scope": scope, "review_queue": queue, "targets": targets,
    }, "basis_sha256")


def prepare_packet(snapshot, *, as_of=None, scope="queued", max_review_age=180,
                   max_source_age=180):
    """Copy immutable source/triage context and create explicitly unresolved rows."""
    encode_artifact(snapshot)
    source = verify_snapshot(snapshot)
    cutoff = _date(source["validation_as_of"]) if as_of is None else as_of
    basis = _basis(source, as_of=cutoff, scope=scope, max_review_age=max_review_age,
                   max_source_age=max_source_age)
    packet = {
        "schema_version": VERSION, "artifact_type": "catalog_resolution_packet",
        "resolution_policy": POLICY, "basis": basis,
        "decisions": [{"id": target["id"], "action": "pending", "rationale": "",
                       "proposed_record": None} for target in basis["targets"]],
        "limitations": list(LIMITATIONS),
    }
    encode_artifact(packet)
    return packet


def _checked_packet(source, packet):
    encode_artifact(packet)
    _keys(packet, ("schema_version", "artifact_type", "resolution_policy", "basis",
                   "decisions", "limitations"))
    basis = packet["basis"]
    _keys(basis, ("source_snapshot_sha256", "source_dataset_sha256", "scope", "review_queue",
                  "targets", "basis_sha256"))
    queue = basis["review_queue"]
    _keys(queue, ("review_policy", "as_of", "max_review_age", "max_source_age",
                  "catalog_count", "queued_count", "reason_counts", "entries"))
    expected = prepare_packet(source, as_of=_date(queue["as_of"]), scope=basis["scope"],
                              max_review_age=queue["max_review_age"], max_source_age=queue["max_source_age"])
    for field in ("schema_version", "artifact_type", "resolution_policy", "basis", "limitations"):
        if canonical(packet[field]) != canonical(expected[field]):
            raise CatalogError("Resolution source or immutable preparation context does not match recomputation.")
    decisions = packet["decisions"]
    targets = {target["id"] for target in basis["targets"]}
    if not isinstance(decisions, list) or len(decisions) > MAX_DECISIONS or len(decisions) != len(targets):
        raise CatalogError("Every selected record requires exactly one bounded decision.")
    seen = set()
    for decision in decisions:
        _keys(decision, ("id", "action", "rationale", "proposed_record"))
        identifier = decision["id"]
        if not isinstance(identifier, str) or identifier not in targets or identifier in seen:
            raise CatalogError("Decision identifiers must be unique and match the complete selected set.")
        seen.add(identifier)
        action, rationale, proposed = decision["action"], decision["rationale"], decision["proposed_record"]
        if not isinstance(action, str) or action not in ACTIONS:
            raise CatalogError("A decision action is not supported.")
        if action == "pending":
            raise CatalogError("All selected decisions must explicitly choose keep, remove or replace.")
        if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > MAX_RATIONALE:
            raise CatalogError("Each completed decision requires a nonempty rationale of at most 2000 characters.")
        if action == "replace":
            if not isinstance(proposed, dict) or proposed.get("id") != identifier:
                raise CatalogError("A replacement must provide a complete record with the unchanged selected identifier.")
        elif proposed is not None:
            raise CatalogError("Keep and remove decisions must not supply a replacement record.")
    checked = copy.deepcopy(packet)
    checked["decisions"].sort(key=lambda decision: decision["id"])
    return checked


def resolve_packet(snapshot, packet, *, as_of):
    """Validate every decision, then build a new, fully inspectable proposal bundle."""
    encode_artifact(snapshot)
    source = verify_snapshot(snapshot)
    checked = _checked_packet(source, packet)
    queue = checked["basis"]["review_queue"]
    if type(as_of) is not dt.date or as_of < _date(queue["as_of"]):
        raise CatalogError("The candidate cutoff must be on or after the fixed preparation cutoff.")
    records = {record["id"]: record for record in source["dataset"]["records"]}
    decisions = checked["decisions"]
    counts = {"keep": 0, "remove": 0, "replace": 0,
              "untouched": len(records) - len(decisions)}
    for decision in decisions:
        identifier, action = decision["id"], decision["action"]
        counts[action] += 1
        if action == "remove":
            del records[identifier]
        elif action == "replace":
            records[identifier] = copy.deepcopy(decision["proposed_record"])
    candidate = make_snapshot({"schema_version": VERSION, "records": list(records.values())}, as_of=as_of)
    comparison = compare_snapshots(source, candidate, as_of=as_of,
                                   max_review_age=queue["max_review_age"], max_source_age=queue["max_source_age"])
    after_hashes = {entry["id"]: entry["sha256"] for entry in candidate["record_hashes"]}
    before_hashes = {entry["id"]: entry["sha256"] for entry in source["record_hashes"]}
    rows = [{"id": decision["id"], "action": decision["action"],
             "before_sha256": before_hashes[decision["id"]],
             "after_sha256": after_hashes.get(decision["id"])} for decision in decisions]
    result = _hashed({
        "schema_version": VERSION, "artifact_type": "catalog_resolution",
        "resolution_policy": POLICY, "candidate_as_of": as_of.isoformat(),
        "packet": checked, "decisions_sha256": fingerprint(decisions),
        "decision_counts": counts, "decision_summary": rows,
        "comparison": comparison, "limitations": list(LIMITATIONS),
    }, "resolution_sha256")
    encode_artifact(result)
    return result


def verify_resolution(result):
    """Rebuild the whole bundle; an outer hash alone never validates a summary."""
    encode_artifact(result)
    _keys(result, ("schema_version", "artifact_type", "resolution_policy", "candidate_as_of",
                   "packet", "decisions_sha256", "decision_counts", "decision_summary",
                   "comparison", "limitations", "resolution_sha256"))
    comparison = result["comparison"]
    if not isinstance(comparison, dict) or "before_snapshot" not in comparison:
        raise CatalogError("The resolution must contain its complete source comparison.")
    expected = resolve_packet(comparison["before_snapshot"], result["packet"],
                              as_of=_date(result["candidate_as_of"]))
    if canonical(result) != canonical(expected):
        raise CatalogError("Resolution decisions, candidate, summaries or fingerprints do not match recomputation.")
    return expected


def export_resolution(result, *, kind):
    checked = verify_resolution(result)
    comparison = checked["comparison"]
    if kind == "snapshot":
        return comparison["after_snapshot"]
    if kind == "comparison":
        return comparison
    if kind == "dataset":
        dataset = comparison["after_snapshot"]["dataset"]
        if not dataset["records"]:
            raise CatalogError("An empty candidate is a valid snapshot but cannot be exported as a nonempty schema dataset.")
        return dataset
    raise CatalogError("Resolution export kind is not supported.")


def build_parser():
    parser = SafeParser(description="Prepare explicit offline decisions and create a separate candidate catalog.")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=SafeParser)
    prepare = commands.add_parser("prepare", help="Create a content-bound draft with pending decisions.")
    prepare.add_argument("--source", required=True, help="A complete verified maintenance snapshot.")
    prepare.add_argument("--scope", choices=("queued", "all"), default="queued")
    prepare.add_argument("--as-of", type=parse_date, help="Fixed triage cutoff; defaults to the snapshot cutoff.")
    prepare.add_argument("--max-review-age", type=parse_number, default=180)
    prepare.add_argument("--max-source-age", type=parse_number, default=180)
    prepare.add_argument("--output", default="private-output/resolution-packet.json")
    for name, help_text in (("check", "Validate a proposed candidate without writing any artifact."),
                            ("resolve", "Create one private bundle with complete before and after evidence.")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--source", required=True)
        command.add_argument("--packet", required=True)
        command.add_argument("--as-of", type=parse_date, required=True, help="Explicit candidate validation cutoff.")
        if name == "resolve":
            command.add_argument("--output", default="private-output/resolution.json")
    export = commands.add_parser("export", help="Reverify a resolution and export one new candidate artifact.")
    export.add_argument("resolution")
    export.add_argument("--kind", choices=("snapshot", "dataset", "comparison"), required=True)
    export.add_argument("--output", required=True)
    return parser


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
        if args.command == "prepare":
            result = prepare_packet(read_artifact(args.source), as_of=args.as_of, scope=args.scope,
                                    max_review_age=args.max_review_age, max_source_age=args.max_source_age)
        elif args.command in ("check", "resolve"):
            result = resolve_packet(read_artifact(args.source), read_artifact(args.packet), as_of=args.as_of)
            if args.command == "check":
                counts = result["decision_counts"]
                changes = result["comparison"]["counts"]
                print("Candidate structurally valid. keep={keep} remove={remove} replace={replace} untouched={untouched}".format(**counts))
                print("Candidate changes: added={added} removed={removed} changed={changed} unchanged={unchanged}".format(**changes))
                print("No files written. Structural validation does not approve evidence or establish policy truth.")
                return 0
        else:
            result = export_resolution(read_artifact(args.resolution), kind=args.kind)
        content = encode_artifact(result)
        preflight_outputs([args.output])
        write_private_bytes(content, args.output)
        print("Created one private resolution artifact. No source catalog was modified or approved.")
        return 0
    except KeyboardInterrupt:
        print("Resolution interrupted. Inspect the requested output before retrying with a new name.", file=sys.stderr)
        return 130
    except ArgumentError as error:
        print(str(error), file=sys.stderr)
        return 2
    except CatalogError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, UnicodeError, RecursionError):
        print("Unable to complete private resolution output.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
