#!/usr/bin/env python3
"""Validate policy record structure; never determine whether a claim is true."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import ipaddress
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

RECORD_KEYS = {
    "id", "record_type", "jurisdiction", "topic", "title", "claim", "scope",
    "policy_stage", "verification_status", "dates", "sources", "last_verified_at",
    "verification_note", "limitations", "change_history",
}
SOURCE_KEYS = {"url", "publisher", "title", "published_at", "locator", "accessed_at", "supports"}
DATE_KEYS = {"announced_at", "adopted_at", "effective_at", "target_at"}
STAGES = {"unknown", "announced", "proposed", "adopted", "in_force", "implementing", "completed", "withdrawn"}
STATUSES = {"pending", "verified", "disputed", "outdated", "inconclusive"}
TOPICS = {"reserve_service", "treaty_status", "civil_protection", "household_preparedness", "emergency_stockpiles", "other"}
SYNTHETIC_HOSTS = {"example.org", "example.invalid"}


def validate_document(document: object, label: str = "document", seen: set[str] | None = None,
                      *, as_of: dt.date | None = None) -> list[str]:
    """Return structural errors, using one inclusive UTC-day or supplied date ceiling.

    Share `seen` to enforce IDs across files. `as_of` affects review and source
    access dates only; it does not establish historical policy truth.
    """
    errors: list[str] = []
    seen = set() if seen is None else seen
    ceiling = dt.datetime.now(dt.timezone.utc).date() if as_of is None else as_of

    def error(path: str, message: str) -> None:
        errors.append(f"{path}: {message}")

    def keys(value: object, expected: set[str], path: str) -> bool:
        if not isinstance(value, dict):
            error(path, "must be an object")
            return False
        for field in sorted(expected - value.keys()):
            error(path, f"missing field {field}")
        for field in sorted(value.keys() - expected):
            error(path, "unknown field (remove fields outside the schema)")
        return True

    def string(value: object, path: str, nullable: bool = False) -> bool:
        if nullable and value is None:
            return True
        if not isinstance(value, str) or not value.strip():
            error(path, "must be a non-empty string" + (" or null" if nullable else ""))
            return False
        return True

    def choice(value: object, allowed: set[str], path: str) -> None:
        if not isinstance(value, str) or value not in allowed:
            error(path, f"must be one of {', '.join(sorted(allowed))}")

    def date(value: object, path: str, nullable: bool = True) -> dt.date | None:
        if nullable and value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            error(path, "must be a calendar date YYYY-MM-DD" + (" or null" if nullable else ""))
            return None
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            error(path, "must be a valid calendar date")
            return None

    if not keys(document, {"schema_version", "records"}, label):
        return errors
    if type(document.get("schema_version")) is not int or document.get("schema_version") != 1:
        error(label + ".schema_version", "must be integer 1")
    records = document.get("records")
    if not isinstance(records, list) or not records:
        error(label + ".records", "must be a non-empty array")
        return errors
    for index, record in enumerate(records):
        p = f"{label}.records[{index}]"
        if not keys(record, RECORD_KEYS, p):
            continue
        record_id = record.get("id")
        if not isinstance(record_id, str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", record_id):
            error(p + ".id", "must be a lowercase ASCII slug")
        elif record_id in seen:
            error(p + ".id", "duplicate ID across input records")
        else:
            seen.add(record_id)
        kind = record.get("record_type")
        choice(kind, {"real", "synthetic"}, p + ".record_type")
        if isinstance(record_id, str) and (record_id.startswith("synthetic-") != (kind == "synthetic")):
            error(p + ".id", "synthetic records must use the synthetic- prefix; real records must not")
        for field in ("jurisdiction", "title", "claim", "scope", "verification_note"):
            string(record.get(field), p + "." + field)
        choice(record.get("topic"), TOPICS, p + ".topic")
        choice(record.get("policy_stage"), STAGES, p + ".policy_stage")
        status = record.get("verification_status")
        choice(status, STATUSES, p + ".verification_status")
        last = date(record.get("last_verified_at"), p + ".last_verified_at")
        if status == "pending":
            if record.get("last_verified_at") is not None:
                error(p + ".last_verified_at", "pending records must use null")
        elif isinstance(status, str) and status in STATUSES and last is None:
            error(p + ".last_verified_at", "reviewed records require a valid review date")
        if last and last > ceiling:
            error(p + ".last_verified_at", "review date cannot be in the future relative to the validation date")
        dates = record.get("dates")
        if keys(dates, DATE_KEYS, p + ".dates"):
            for field in sorted(DATE_KEYS):
                date(dates.get(field), p + ".dates." + field)
        sources = record.get("sources")
        if not isinstance(sources, list) or not sources:
            error(p + ".sources", "must contain at least one source")
        else:
            for source_index, source in enumerate(sources):
                s = f"{p}.sources[{source_index}]"
                if not keys(source, SOURCE_KEYS, s):
                    continue
                for field in ("url", "publisher", "title"):
                    string(source.get(field), s + "." + field)
                for field in ("locator", "supports"):
                    string(source.get(field), s + "." + field, nullable=status != "verified")
                date(source.get("published_at"), s + ".published_at")
                accessed = date(source.get("accessed_at"), s + ".accessed_at", nullable=status != "verified")
                if accessed and accessed > ceiling:
                    error(s + ".accessed_at", "access date cannot be in the future relative to the validation date")
                if accessed and last and accessed > last:
                    error(s + ".accessed_at", "cannot be later than last_verified_at")
                url = source.get("url")
                if isinstance(url, str):
                    try:
                        parsed = urlsplit(url)
                        host = parsed.hostname
                        # DNS absolute names may end in a dot; classify the canonical host.
                        if host is not None:
                            host = host.rstrip(".")
                        # Accessing port also detects malformed values such as ':abc'.
                        port = parsed.port
                        private_query_fields = {"token", "accesstoken", "refreshtoken", "apikey", "password", "passwd", "secret", "authorization", "auth", "session", "sessionid", "signature", "sig", "xamzsignature", "xamzcredential", "xamzsecuritytoken"}
                        if any(re.sub(r"[-_]", "", key.lower()) in private_query_fields for key, _ in parse_qsl(parsed.query)):
                            raise ValueError("credential-like query field")
                        if host and ("." not in host or host.endswith((".local", ".localhost", ".internal"))):
                            raise ValueError("local source host")
                        if host:
                            try:
                                ipaddress.ip_address(host)
                            except ValueError:
                                pass
                            else:
                                raise ValueError("IP literals are not public document source domains")
                        if parsed.scheme != "https" or not host or parsed.username is not None or parsed.password is not None or port not in (None, 443) or any(c.isspace() for c in url) or "\\" in url:
                            raise ValueError("invalid public source URL")
                        reserved = host.endswith((".invalid", ".example")) or host in {"invalid", "example"} or any(host == domain or host.endswith("." + domain) for domain in ("example.org", "example.com", "example.net"))
                        if kind == "synthetic" and host not in SYNTHETIC_HOSTS:
                            error(s + ".url", "synthetic sources must use example.org or example.invalid")
                        if kind == "real" and reserved:
                            error(s + ".url", "real records cannot use reserved example domains")
                    except ValueError:
                        error(s + ".url", "must use an HTTPS domain URL without credentials, credential-like query fields, local hosts, IP literals, whitespace, or a nonstandard port")
        limitations = record.get("limitations")
        if not isinstance(limitations, list) or not limitations:
            error(p + ".limitations", "must explicitly state at least one evidence limitation")
        else:
            for i, limitation in enumerate(limitations):
                string(limitation, f"{p}.limitations[{i}]")
        history = record.get("change_history")
        if not isinstance(history, list) or not history:
            error(p + ".change_history", "must contain at least one change entry")
        else:
            for i, entry in enumerate(history):
                h = f"{p}.change_history[{i}]"
                if keys(entry, {"date", "summary"}, h):
                    date(entry.get("date"), h + ".date", nullable=False)
                    string(entry.get("summary"), h + ".summary")
    return errors


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            # Never echo the supplied key: it might contain sensitive content.
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def admission_errors(records: list[dict], args: argparse.Namespace, ceiling: dt.date) -> list[str]:
    errors = []
    for index, record in enumerate(records):
        label = f"record-{index + 1}"
        if args.max_access_age is not None and any(value is None or (ceiling - dt.date.fromisoformat(value)).days > args.max_access_age for value in [s["accessed_at"] for s in record["sources"]]):
            errors.append(f"{label}: accessed_at is missing or exceeds the age limit")
        if args.max_review_age is not None and any(value is None or (ceiling - dt.date.fromisoformat(value)).days > args.max_review_age for value in [record["last_verified_at"]]):
            errors.append(f"{label}: last_verified_at is missing or exceeds the age limit")
        if args.unique_sources and len({s["url"] for s in record["sources"]}) != len(record["sources"]):
            errors.append(f"{label}: duplicate source URL within the record")
        if len(source_domains(record)) < args.min_source_domains:
            errors.append(f"{label}: source-domain count is below the required minimum")
        if len(record["sources"]) < args.min_sources:
            errors.append(f"{label}: source count is below the required minimum")
        if args.require_source_support and any(source["supports"] is None for source in record["sources"]):
            errors.append(f"{label}: all source supports values are required")
        if args.require_publication_dates and any(source["published_at"] is None for source in record["sources"]):
            errors.append(f"{label}: all source published_at values are required")
        if args.require_source_dates and any(source["accessed_at"] is None for source in record["sources"]):
            errors.append(f"{label}: all source accessed_at values are required")
        if args.require_source_locators and any(source["locator"] is None for source in record["sources"]):
            errors.append(f"{label}: all source locator values are required")
        if args.require_verified and record["verification_status"] != "verified":
            errors.append(f"{label}: verified records are required")
        if args.require_reviewed and record["verification_status"] == "pending":
            errors.append(f"{label}: completed evidence review is required")
        if args.real_only and record["record_type"] != "real":
            errors.append(f"{label}: real records are required")
    return errors


def source_domains(record: dict) -> set[str]:
    return {urlsplit(source["url"]).hostname.lower().rstrip(".") for source in record["sources"]}


def summarize(records: list[dict]) -> dict:
    sources = [source for record in records for source in record["sources"]]
    return {"source_publication_dates": {"known": sum(s["published_at"] is not None for s in sources), "unknown": sum(s["published_at"] is None for s in sources)},
            "policy_dates": {field: sum(r["dates"][field] is not None for r in records) for field in sorted(DATE_KEYS)},
            "jurisdictions": len({record["jurisdiction"] for record in records}),
            "source_domains": len(set().union(*(source_domains(record) for record in records))),
            "sources": {"total": len(sources), **{field: sum(s[field] is not None for s in sources) for field in ("accessed_at", "locator", "supports")}},
            "topics": {value: sum(r["topic"] == value for r in records) for value in sorted(TOPICS)},
            "policy_stages": {value: sum(r["policy_stage"] == value for r in records) for value in sorted(STAGES)},
            "verification_states": {value: sum(r["verification_status"] == value for r in records) for value in sorted(STATUSES)},
            "records": len(records),
            "record_types": {kind: sum(r["record_type"] == kind for r in records) for kind in ("real", "synthetic")}}


def read_input(path: Path, limit: int | None) -> str:
    size = -1 if limit is None else limit + 1
    if path == Path("-"):
        raw = getattr(sys.stdin, "buffer", sys.stdin).read(size)
    else:
        with path.open("rb") as stream:
            raw = stream.read(size)
    raw = raw.encode("utf-8") if isinstance(raw, str) else raw
    if limit is not None and len(raw) > limit:
        raise ValueError("input byte limit exceeded")
    return raw.decode("utf-8")


def parse_count(value: str) -> int:
    if not re.fullmatch(r"[0-9]{1,9}", value):
        raise argparse.ArgumentTypeError("must be a non-negative integer with at most nine digits")
    return int(value)


def parse_as_of(value: str) -> dt.date:
    """Parse a strict ISO date without including supplied content in errors."""
    message = "must be a valid calendar date in YYYY-MM-DD format"
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise argparse.ArgumentTypeError(message)
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(message) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="policy-record-validator (schema 1)")
    parser.add_argument("files", type=Path, nargs="+", help="JSON record files or one - for stdin; IDs are checked across all inputs")
    parser.add_argument("--as-of", type=parse_as_of, metavar="YYYY-MM-DD",
                        help="inclusive ceiling for review and source access dates (default: current UTC date)")
    parser.add_argument("--summary", action="store_true", help="append safe aggregate counts after successful validation")
    parser.add_argument("--json", action="store_true", help="emit only a JSON aggregate summary on success")
    parser.add_argument("--real-only", action="store_true", help="reject synthetic records")
    parser.add_argument("--require-reviewed", action="store_true", help="completed evidence review is required")
    parser.add_argument("--require-verified", action="store_true", help="verified records are required")
    parser.add_argument("--require-source-locators", action="store_true", help="require every source locator value")
    parser.add_argument("--require-source-dates", action="store_true", help="require every source accessed_at value")
    parser.add_argument("--require-publication-dates", action="store_true", help="require every source published_at value")
    parser.add_argument("--require-source-support", action="store_true", help="require every source supports value")
    parser.add_argument("--min-sources", type=parse_count, default=0, metavar="N", help="minimum citations per record")
    parser.add_argument("--min-source-domains", type=parse_count, default=0, metavar="N", help="minimum distinct source hostnames per record")
    parser.add_argument("--unique-sources", action="store_true", help="reject repeated exact source URLs within each record")
    parser.add_argument("--max-review-age", type=parse_count, metavar="DAYS", help="maximum last_verified_at age; missing dates fail")
    parser.add_argument("--max-access-age", type=parse_count, metavar="DAYS", help="maximum accessed_at age; missing dates fail")
    parser.add_argument("--min-records", type=parse_count, default=0, metavar="N", help="minimum combined record count")
    parser.add_argument("--quiet", action="store_true", help="suppress the default PASS banner; requested summaries remain visible")
    parser.add_argument("--max-input-bytes", type=parse_count, metavar="N", help="maximum UTF-8 bytes per input")
    args = parser.parse_args(argv)
    if args.files.count(Path("-")) > 1:
        parser.error("standard input may be used only once")
    ceiling = dt.datetime.now(dt.timezone.utc).date() if args.as_of is None else args.as_of
    seen: set[str] = set()
    errors = []
    count = 0
    records = []
    for input_index, path in enumerate(args.files, start=1):
        # Even filenames can contain private information; print only input ordinals.
        label = f"input-{input_index}"
        try:
            if path == Path("-") and sys.stdin is None:
                raise ValueError("standard input is unavailable")
            document = json.loads(read_input(path, args.max_input_bytes), object_pairs_hook=reject_duplicate_keys,
                                  parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON number")))
        except (OSError, UnicodeError, ValueError) as exc:
            detail = f"invalid JSON at line {exc.lineno}, column {exc.colno}" if isinstance(exc, json.JSONDecodeError) else "cannot read valid UTF-8 JSON (check file access, duplicate keys, syntax, and any byte limit)"
            errors.append(f"{label}: {detail}")
            continue
        errors.extend(validate_document(document, label, seen, as_of=ceiling))
        if isinstance(document, dict) and isinstance(document.get("records"), list):
            count += len(document["records"])
            records.extend(document["records"])
    if not errors:
        errors.extend(admission_errors(records, args, ceiling))
        if len(records) < args.min_records:
            errors.append("batch: record count is below the required minimum")
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(summarize(records), sort_keys=True))
        return 0
    if not args.quiet:
        print(f"PASS: {count} structurally valid records in {len(args.files)} files. This is not factual verification.")
    if args.summary:
        print("SUMMARY: " + json.dumps(summarize(records), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
