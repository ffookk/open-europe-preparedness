"""Generate fictional browser inputs and independently verify downloaded artifacts."""
import copy
import datetime as dt
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.catalog import Catalog
from scripts.catalog_html import render_html
from scripts.maintenance import compare_snapshots, make_snapshot, verify_report, verify_snapshot
from scripts.maintenance_html import render_report

DAY = dt.date(2024, 1, 5)


def document(records):
    return {"schema_version": 1, "records": records}


def generate():
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
    expected = {"report": report, "before": before, "after": after,
                "underscore": document([a]), "space": document([b, d]), "fresh": document([b])}
    pages = {"catalog_html": render_html(Catalog([after["dataset"]], as_of=DAY)),
             "maintenance_html": render_report(report)}
    return pages, expected


def verify(downloads):
    _, expected = generate()
    for page in ("catalog", "maintenance"):
        for selection in ("underscore", "space", "all"):
            actual = downloads[page + "-" + selection + ".json"]
            wanted = expected["after"]["dataset"] if selection == "all" else expected[selection]
            assert actual == wanted, "Downloaded records or provenance differ."
            Catalog([actual], as_of=DAY)
    fresh = downloads["catalog-fresh.json"]
    assert fresh == expected["fresh"], "Fixed-cutoff date selection differs."
    Catalog([fresh], as_of=DAY)
    report = downloads["report.json"]
    assert verify_report(report) == expected["report"], "Full report differs."
    for name in ("before", "after"):
        snapshot = downloads[name + ".json"]
        assert verify_snapshot(snapshot) == expected[name], "Full snapshot differs."
    packet = downloads["removed.json"]
    removed = next(row for row in expected["report"]["changes"] if row["change"] == "removed")
    original = expected["before"]["dataset"]["records"][2]
    assert packet["source_report_sha256"] == report["report_sha256"], "Selection report reference differs."
    assert packet["entries"] == [{"id": original["id"], "change": "removed", "field_changes": removed["field_changes"],
                                  "before": original, "after": None, "review_reasons": []}], "Removed evidence differs."


if __name__ == "__main__":
    try:
        assert len(sys.argv) == 1, "Command-line inputs are unsupported."
        text = sys.stdin.read(2 * 1024 * 1024 + 1)
        assert len(text) <= 2 * 1024 * 1024, "Request exceeds the fixture protocol limit."
        request = json.loads(text)
        if request == {"mode": "generate"}:
            result, _ = generate()
        else:
            assert set(request) == {"mode", "downloads"} and request["mode"] == "verify"
            verify(request["downloads"])
            result = {"verified_exports": 11}
        print(json.dumps(result))
    except Exception:
        print("Fictional browser fixture or artifact verification failed.", file=sys.stderr)
        raise SystemExit(1) from None
