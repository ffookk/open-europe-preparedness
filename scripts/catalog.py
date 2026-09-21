"""Query validated policy records locally; results preserve evidence and uncertainty."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .validate_records import DATE_KEYS, STAGES, STATUSES, TOPICS, reject_duplicate_keys, validate_document

FACET_FIELDS = ("jurisdiction", "topic", "policy_stage", "verification_status", "record_type")
DATE_FIELDS = ("last_verified_at", *sorted(DATE_KEYS))
SORT_FIELDS = ("id", "title", *FACET_FIELDS, *DATE_FIELDS)
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_FILES = 16
MAX_RECORDS = 10000
NOTICE = ("Structure was checked, not policy truth. Policy stage and evidence review status "
          "are independent. Synthetic records are fictional; source review is not human certification.")


class CatalogError(ValueError):
    """A fixed, input-free error safe to display on the command line."""


class ArgumentError(CatalogError):
    """Invalid command arguments."""


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentError("Invalid command arguments. Use --help for usage.")


def parse_date(value: str) -> dt.date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("A calendar date in YYYY-MM-DD format is required.")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError("A calendar date in YYYY-MM-DD format is required.") from None


def parse_number(value: str) -> int:
    if not re.fullmatch(r"[0-9]{1,7}", value):
        raise ValueError("A nonnegative integer is required.")
    return int(value)


def sort_key(value: str) -> bytes:
    """Use a locale-independent order also reproducible by JavaScript."""
    return value.lower().encode("utf-16-be", "surrogatepass")


def date_value(record: dict, field: str) -> str | None:
    return record[field] if field == "last_verified_at" else record["dates"][field]


def searchable_text(record: dict) -> str:
    """Search all stored string values, including provenance and limitations."""
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    return "\n".join(strings(record)).lower()


@dataclass(frozen=True)
class Query:
    jurisdiction: tuple[str, ...] = ()
    topic: tuple[str, ...] = ()
    policy_stage: tuple[str, ...] = ()
    verification_status: tuple[str, ...] = ()
    record_type: tuple[str, ...] = ()
    text: str = ""
    date_field: str = "last_verified_at"
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    date_presence: str = "any"
    max_review_age: int | None = None
    sort: str = "title"
    descending: bool = False
    offset: int = 0
    limit: int = 25

    def validate(self):
        choices = {"topic": TOPICS, "policy_stage": STAGES, "verification_status": STATUSES,
                   "record_type": {"real", "synthetic"}}
        for field in FACET_FIELDS:
            values = getattr(self, field)
            if not isinstance(values, (tuple, list)) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise CatalogError("Filters must contain nonempty strings.")
            if field in choices and any(v not in choices[field] for v in values):
                raise CatalogError("A categorical filter is outside the supported vocabulary.")
        if not isinstance(self.text, str) or len(self.text) > 1000:
            raise CatalogError("Search text must contain at most 1000 characters.")
        if self.date_field not in DATE_FIELDS or self.sort not in SORT_FIELDS or self.date_presence not in ("any", "known", "unknown"):
            raise CatalogError("A date or sorting option is not supported.")
        if any(v is not None and type(v) is not dt.date for v in (self.date_from, self.date_to)):
            raise CatalogError("Date bounds must be date objects.")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise CatalogError("The start date must not follow the end date.")
        if self.date_presence == "unknown" and (self.date_from or self.date_to):
            raise CatalogError("Unknown dates cannot be combined with a date range.")
        if self.max_review_age is not None and (type(self.max_review_age) is not int or not 0 <= self.max_review_age <= 3652058):
            raise CatalogError("Review age must be a nonnegative number of calendar days within the supported range.")
        if type(self.offset) is not int or not 0 <= self.offset <= MAX_RECORDS:
            raise CatalogError("Offset must be between 0 and 10000.")
        if type(self.limit) is not int or not 1 <= self.limit <= 1000:
            raise CatalogError("Limit must be between 1 and 1000.")
        if type(self.descending) is not bool:
            raise CatalogError("Descending order must be a boolean.")


class Catalog:
    def __init__(self, documents: list[dict], *, as_of: dt.date | None = None):
        if as_of is not None and type(as_of) is not dt.date:
            raise CatalogError("The validation cutoff must be a date object.")
        self.as_of = as_of if as_of is not None else dt.datetime.now(dt.timezone.utc).date()
        if not isinstance(documents, list) or not 1 <= len(documents) <= MAX_FILES:
            raise CatalogError("Provide between 1 and 16 input documents.")
        seen: set[str] = set()
        records = []
        try:
            for document in documents:
                if validate_document(document, seen=seen, as_of=self.as_of):
                    raise CatalogError("Catalog validation failed. Use the validator for structural diagnostics.")
                records.extend(document["records"])
                if len(records) > MAX_RECORDS:
                    raise CatalogError("The catalog exceeds the 10000-record limit.")
        except (RecursionError, TypeError, OverflowError):
            raise CatalogError("Catalog validation failed.") from None
        self._records = copy.deepcopy(records)

    @property
    def records(self) -> list[dict]:
        return copy.deepcopy(self._records)

    def select(self, query: Query) -> list[dict]:
        query.validate()
        selected = []
        for record in self._records:
            if any(getattr(query, f) and record[f].lower() not in {v.lower() for v in getattr(query, f)} for f in FACET_FIELDS):
                continue
            if query.text.lower() not in searchable_text(record):
                continue
            value = date_value(record, query.date_field)
            if query.date_presence == "known" and value is None or query.date_presence == "unknown" and value is not None:
                continue
            if query.date_from or query.date_to:
                if value is None or query.date_from and value < query.date_from.isoformat() or query.date_to and value > query.date_to.isoformat():
                    continue
            if query.max_review_age is not None:
                reviewed = record["last_verified_at"]
                if reviewed is None or (self.as_of - dt.date.fromisoformat(reviewed)).days > query.max_review_age:
                    continue
            selected.append(record)
        selected.sort(key=lambda r: r["id"])
        def value(record):
            return date_value(record, query.sort) if query.sort in DATE_FIELDS else record[query.sort]
        known = [r for r in selected if value(r) is not None]
        unknown = [r for r in selected if value(r) is None]
        known.sort(key=lambda r: sort_key(value(r)), reverse=query.descending)
        return copy.deepcopy(known + unknown)

    def query(self, query: Query) -> dict:
        matched = self.select(query)
        page = matched[query.offset:query.offset + query.limit]
        return {"catalog_as_of": self.as_of.isoformat(), "total_count": len(self._records),
                "matched_count": len(matched), "returned_count": len(page),
                "offset": query.offset, "limit": query.limit,
                "facets": facets(matched), "records": page, "notice": NOTICE}


def facets(records: list[dict]) -> dict:
    return {field: dict(sorted(Counter(r[field] for r in records).items(), key=lambda pair: (sort_key(pair[0]), pair[0])))
            for field in FACET_FIELDS}


def dataset(records: list[dict]) -> dict:
    if not records:
        raise CatalogError("A schema dataset export requires at least one selected record.")
    return {"schema_version": 1, "records": copy.deepcopy(records)}


def load_catalog(paths: list[str], *, as_of: dt.date | None = None) -> Catalog:
    if not 1 <= len(paths) <= MAX_FILES:
        raise CatalogError("Provide between 1 and 16 input files.")
    documents = []
    def reject_constant(_):
        raise ValueError("Nonfinite JSON numbers are unsupported.")
    for path in paths:
        try:
            with Path(path).open("rb") as source:
                raw = source.read(MAX_FILE_BYTES + 1)
            if len(raw) > MAX_FILE_BYTES:
                raise CatalogError("An input exceeds the 8 MiB file limit.")
            documents.append(json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                                        parse_constant=reject_constant))
        except (OSError, ValueError, RecursionError) as error:
            if isinstance(error, CatalogError):
                raise
            raise CatalogError("Unable to read an input as strict UTF-8 JSON.") from None
    return Catalog(documents, as_of=as_of)


def build_parser() -> argparse.ArgumentParser:
    parser = SafeParser(description="Explore policy records offline without changing their evidence status.")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=SafeParser)
    query = commands.add_parser("query", help="Filter validated records and emit JSON, including original record text.")
    query.add_argument("files", nargs="+", help="UTF-8 schema datasets; all inputs are validated together.")
    query.add_argument("--as-of", type=parse_date, help="Inclusive review/access date ceiling; defaults to the UTC day.")
    for flag, field, choices in (("jurisdiction", "jurisdiction", None), ("topic", "topic", sorted(TOPICS)),
                                 ("stage", "policy_stage", sorted(STAGES)), ("status", "verification_status", sorted(STATUSES)),
                                 ("record-type", "record_type", ["real", "synthetic"])):
        query.add_argument("--" + flag, dest=field, action="append", choices=choices, default=[])
    query.add_argument("--text", default="", help="Case-insensitive substring across all stored string values.")
    query.add_argument("--date-field", choices=DATE_FIELDS, default="last_verified_at")
    query.add_argument("--date-from", type=parse_date)
    query.add_argument("--date-to", type=parse_date)
    query.add_argument("--date-presence", choices=("any", "known", "unknown"), default="any")
    query.add_argument("--max-review-age", type=parse_number, help="Inclusive age in calendar days at the cutoff; excludes unknown reviews.")
    query.add_argument("--sort", choices=SORT_FIELDS, default="title")
    query.add_argument("--descending", action="store_true")
    query.add_argument("--offset", type=parse_number, default=0)
    query.add_argument("--limit", type=parse_number, default=25)
    query.add_argument("--dataset", action="store_true", help="Export this page as a complete schema dataset, preserving provenance.")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        query = Query(**{field: getattr(args, field) for field in Query.__dataclass_fields__})
        query.validate()
        catalog = load_catalog(args.files, as_of=args.as_of)
        result = catalog.query(query)
        output = dataset(result["records"]) if args.dataset else result
        print(json.dumps(output, indent=2, ensure_ascii=True, allow_nan=False))
        return 0
    except ArgumentError as error:
        print(str(error), file=sys.stderr)
        return 2
    except CatalogError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, UnicodeError):
        print("Unable to write catalog output.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
