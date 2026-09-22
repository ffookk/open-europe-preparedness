"""Generate fictional browser inputs and independently verify downloaded artifacts."""
import copy
import datetime as dt
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.catalog import Catalog
from scripts.catalog_html import write_html
from scripts.maintenance import compare_snapshots, make_snapshot, verify_report, verify_snapshot
from scripts.maintenance_html import render_report
from scripts.private_files import write_private_bytes

DAY = dt.date(2024, 1, 5)


def document(records):
    return {"schema_version": 1, "records": records}


def generate(directory):
    template = json.loads((ROOT / "examples/synthetic.json").read_text(encoding="utf-8"))["records"][0]

    def record(letter, jurisdiction, publisher):
        item = copy.deepcopy(template)
        item.update(id="synthetic-" + letter, title="Fictional record " + letter,
                    jurisdiction=jurisdiction, claim="Fictional inert text " + letter)
        item["sources"][0]["publisher"] = publisher
        return item

    a = record("a", "Fictional_Area", "Example_A")
    b = record("b", "Fictional Area", "Example A")
    b["last_verified_at"] = b["sources"][0]["accessed_at"] = DAY.isoformat()
    c = record("c", "Fictional_Area", "Example_A")
    before = make_snapshot(document([a, b, c]), as_of=DAY)
    a.update(policy_stage="announced", verification_status="disputed")
    a["claim"] += '</script><img src=x onerror=alert("fictional")>'
    a["sources"][0]["supports"] = "Fictional revised source support."
    a["limitations"].append("Fictional additional uncertainty.")
    d = record("d", "Fictional Area", "Example A")
    d.update(verification_status="pending", last_verified_at=None)
    d["sources"][0]["accessed_at"] = None
    after = make_snapshot(document([a, b, d]), as_of=DAY)
    report = compare_snapshots(before, after, as_of=DAY, max_review_age=1, max_source_age=1)
    write_html(Catalog([after["dataset"]], as_of=DAY), directory / "catalog.html")
    write_private_bytes(render_report(report).encode("utf-8"), directory / "maintenance.html")
    expected = {"report": report, "before": before, "after": after,
                "underscore": document([a]), "space": document([b, d]), "fresh": document([b])}
    (directory / "expected.json").write_text(json.dumps(expected), encoding="utf-8")


def verify(directory):
    expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
    for page in ("catalog", "maintenance"):
        for selection in ("underscore", "space", "all"):
            actual = json.loads((directory / (page + "-" + selection + ".json")).read_text(encoding="utf-8"))
            wanted = expected["after"]["dataset"] if selection == "all" else expected[selection]
            assert actual == wanted, "Downloaded records or provenance differ."
            Catalog([actual], as_of=DAY)
    fresh = json.loads((directory / "catalog-fresh.json").read_text(encoding="utf-8"))
    assert fresh == expected["fresh"], "Fixed-cutoff date selection differs."
    Catalog([fresh], as_of=DAY)
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    assert verify_report(report) == expected["report"], "Full report differs."
    for name in ("before", "after"):
        snapshot = json.loads((directory / (name + ".json")).read_text(encoding="utf-8"))
        assert verify_snapshot(snapshot) == expected[name], "Full snapshot differs."
    packet = json.loads((directory / "removed.json").read_text(encoding="utf-8"))
    removed = next(row for row in expected["report"]["changes"] if row["change"] == "removed")
    original = expected["before"]["dataset"]["records"][2]
    assert packet["source_report_sha256"] == report["report_sha256"], "Selection report reference differs."
    assert packet["entries"] == [{"id": original["id"], "change": "removed", "field_changes": removed["field_changes"],
                                  "before": original, "after": None, "review_reasons": []}], "Removed evidence differs."


if __name__ == "__main__":
    try:
        mode, target = sys.argv[1:]
        assert mode in ("generate", "verify")
        {"generate": generate, "verify": verify}[mode](Path(target).resolve())
    except Exception:
        print("Fictional browser fixture or artifact verification failed.", file=sys.stderr)
        raise SystemExit(1) from None
