"""Maintenance exports preserve complete artifacts while keeping record text inert."""
import copy
import json
import unittest

from scripts.catalog import CatalogError
from scripts.catalog_html import digest
from scripts.maintenance import compare_snapshots, review_snapshot, verify_report, verify_snapshot
from scripts.maintenance_html import CSS, SCRIPT, render_report
from test_catalog_html import InspectHTML
from test_maintenance import pair, record, snapshot


class MaintenanceHTMLTests(unittest.TestCase):
    def test_complete_snapshots_queue_and_report_fingerprints_survive_json_roundtrip(self):
        report = compare_snapshots(*pair())
        parsed = InspectHTML(render_report(report))
        restored = json.loads(parsed.scripts[0][1])["report"]
        # Browser stringify preserves this format: text/nulls and bounded integers only.
        downloaded = json.loads(json.dumps(restored, ensure_ascii=False))
        self.assertEqual(verify_report(downloaded), report)
        self.assertEqual(verify_snapshot(downloaded["before_snapshot"]), report["before_snapshot"])
        self.assertEqual(verify_snapshot(downloaded["after_snapshot"]), report["after_snapshot"])
        self.assertEqual(downloaded["review_queue"]["entries"], report["review_queue"]["entries"])

    def test_hostile_before_after_source_and_limit_text_cannot_create_active_html(self):
        attack = '</script><img src=x onerror=alert("fictional")><script>alert(1)</script>&'
        original = record("a"); original["title"] = attack
        original["sources"][0]["title"] = attack
        before = snapshot(original)
        original["claim"] = attack; original["limitations"] = [attack]
        report = compare_snapshots(before, snapshot(original))
        parsed = InspectHTML(render_report(report))
        self.assertEqual(len(parsed.scripts), 2)
        self.assertEqual(parsed.scripts[1][1], SCRIPT)
        self.assertFalse(any(tag == "img" or any(key.startswith("on") for key in attrs) for tag,attrs in parsed.tags))
        self.assertEqual(json.loads(parsed.scripts[0][1])["report"]["after_snapshot"]["dataset"]["records"][0]["claim"], attack)

    def test_exact_asset_hashes_and_no_external_resources(self):
        parsed = InspectHTML(render_report(compare_snapshots(*pair())))
        self.assertEqual(parsed.styles[0][1], CSS)
        self.assertIn("script-src 'sha256-" + digest(SCRIPT) + "'", parsed.csp)
        self.assertIn("style-src 'sha256-" + digest(CSS) + "'", parsed.csp)
        self.assertIn("connect-src 'none'", parsed.csp)
        self.assertNotIn("unsafe-inline", parsed.csp)
        self.assertFalse(any(any(key in attrs for key in ("src", "href", "action")) for _,attrs in parsed.tags))

    def test_tampered_stored_report_is_rejected_before_html_generation(self):
        report = compare_snapshots(*pair()); report["changes"][0]["field_changes"] = []
        with self.assertRaises(CatalogError): render_report(report)

    def test_review_only_and_empty_reports_are_supported(self):
        for report in (review_snapshot(snapshot()), review_snapshot(pair()[1]), compare_snapshots(snapshot(), snapshot())):
            parsed = InspectHTML(render_report(report))
            self.assertEqual(verify_report(json.loads(parsed.scripts[0][1])["report"]), report)

    def test_accessible_controls_and_safe_fixed_download_names(self):
        parsed = InspectHTML(render_report(compare_snapshots(*pair())))
        labels = {attrs.get("for") for tag,attrs in parsed.tags if tag == "label"}
        for tag, attrs in parsed.tags:
            if tag in ("input", "select"): self.assertIn(attrs["id"], labels)
        self.assertTrue(any(attrs.get("role") == "alert" for _,attrs in parsed.tags))
        self.assertTrue(any(attrs.get("role") == "status" for _,attrs in parsed.tags))
        self.assertTrue(any(tag == "noscript" for tag,_ in parsed.tags))
        for name in ("maintenance-report.json", "maintenance-selection.json", "catalog-before-snapshot.json", "catalog-after-snapshot.json"):
            self.assertIn('"' + name + '"', SCRIPT)
        self.assertNotIn("innerHTML", SCRIPT)
        self.assertNotIn("localStorage", SCRIPT)
        self.assertNotIn("sessionStorage", SCRIPT)
        self.assertNotIn("fetch(", SCRIPT)
        self.assertNotIn("Date.now", SCRIPT)


if __name__ == "__main__":
    unittest.main()
