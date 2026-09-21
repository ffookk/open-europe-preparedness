"""Offline export tests cover inert hostile content and no-clobber file creation."""
import datetime as dt
import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from scripts.catalog import Catalog, CatalogError, main
from scripts.catalog_html import CSS, SCRIPT, digest, render_html, write_html
from scripts.validate_records import validate_document

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT / "examples/synthetic.json").read_text())


class InspectHTML(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tags, self.scripts, self.styles, self.csp = [], [], [], None
        self.current = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy":
            self.csp = attrs["content"]
        if tag in ("script", "style"):
            self.current = [attrs, ""]
            (self.scripts if tag == "script" else self.styles).append(self.current)

    def handle_data(self, data):
        if self.current is not None:
            self.current[1] += data

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.current = None


class HTMLContentTests(unittest.TestCase):
    def setUp(self):
        self.document = fixture()
        self.catalog = Catalog([self.document], as_of=dt.date(2024, 1, 3))

    def test_payload_preserves_full_dataset_and_exact_cutoff(self):
        parsed = InspectHTML(render_html(self.catalog))
        payload = json.loads(parsed.scripts[0][1])
        self.assertEqual(payload, {"as_of": "2024-01-03", "records": self.document["records"]})
        self.assertEqual(validate_document({"schema_version": 1, "records": payload["records"]}, as_of=self.catalog.as_of), [])
        self.assertIn("2024-01-03", render_html(self.catalog))

    def test_script_and_style_hashes_match_exact_emitted_bytes(self):
        parsed = InspectHTML(render_html(self.catalog))
        self.assertEqual(len(parsed.scripts), 2)
        self.assertEqual(parsed.scripts[1][1], SCRIPT)
        self.assertEqual(parsed.styles[0][1], CSS)
        self.assertIn("script-src 'sha256-" + digest(parsed.scripts[1][1]) + "'", parsed.csp)
        self.assertIn("style-src 'sha256-" + digest(parsed.styles[0][1]) + "'", parsed.csp)
        self.assertIn("default-src 'none'", parsed.csp)
        self.assertIn("connect-src 'none'", parsed.csp)
        self.assertNotIn("unsafe-inline", parsed.csp)
        self.assertNotIn("unsafe-eval", parsed.csp)

    def test_hostile_text_cannot_create_tags_or_change_the_script(self):
        attack = '</script><script>alert("fixture")</script><img src=x onerror=alert(1)>&'
        for field in ("title", "claim", "verification_note"):
            self.document["records"][0][field] = attack
        self.document["records"][0]["limitations"] = [attack]
        self.document["records"][0]["sources"][0]["title"] = attack
        parsed = InspectHTML(render_html(Catalog([self.document], as_of=self.catalog.as_of)))
        self.assertEqual(len(parsed.scripts), 2)
        self.assertEqual(parsed.scripts[1][1], SCRIPT)
        self.assertFalse(any(tag == "img" or any(key.startswith("on") for key in attrs) for tag, attrs in parsed.tags))
        self.assertEqual(json.loads(parsed.scripts[0][1])["records"][0]["claim"], attack)
        self.assertIn("\\u003c/script\\u003e", parsed.scripts[0][1])

    def test_static_document_has_no_external_resource_and_labels_controls(self):
        parsed = InspectHTML(render_html(self.catalog))
        self.assertFalse(any(any(key in attrs for key in ("src", "href", "action")) for _, attrs in parsed.tags))
        labels = {attrs.get("for") for tag, attrs in parsed.tags if tag == "label"}
        for tag, attrs in parsed.tags:
            if tag in ("input", "select") and attrs.get("type") != "checkbox":
                self.assertIn(attrs["id"], labels)
        self.assertTrue(any(attrs.get("role") == "alert" for _, attrs in parsed.tags))
        self.assertTrue(any(attrs.get("role") == "status" for _, attrs in parsed.tags))
        self.assertTrue(any(tag == "noscript" for tag, _ in parsed.tags))

    def test_fixed_executable_does_not_depend_on_record_text_or_clock(self):
        other = fixture()
        other["records"][0]["title"] = "A different example"
        parsed = InspectHTML(render_html(Catalog([other], as_of=dt.date(2025, 1, 1))))
        self.assertEqual(parsed.scripts[1][1], SCRIPT)
        self.assertNotIn("Date.now", SCRIPT)
        self.assertNotIn("innerHTML", SCRIPT)
        self.assertNotIn("localStorage", SCRIPT)
        self.assertNotIn("fetch(", SCRIPT)


@unittest.skipUnless(os.name == "posix", "POSIX safe output behavior")
class HTMLFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()
        self.catalog = Catalog([fixture()], as_of=dt.date(2024, 1, 3))

    def tearDown(self):
        self.directory.cleanup()

    def test_new_file_is_complete_private_and_nested_directories_are_created(self):
        output = self.root / "new" / "nested" / "catalog.html"
        write_html(self.catalog, output)
        self.assertEqual(output.read_text(), render_html(self.catalog))
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(output.parent.stat().st_mode), 0o700)
        self.assertFalse(list(output.parent.glob(".catalog-*.tmp")))

    def test_existing_file_input_and_hardlink_are_never_overwritten(self):
        source = self.root / "source.json"
        source.write_text(json.dumps(fixture()))
        original = source.read_bytes()
        hardlink = self.root / "existing.html"
        os.link(source, hardlink)
        for output in (source, hardlink):
            with self.assertRaises(CatalogError):
                write_html(self.catalog, output)
            self.assertEqual(output.read_bytes(), original)
        self.assertFalse(list(self.root.glob(".catalog-*.tmp")))

    def test_symlink_file_and_parent_directory_are_refused(self):
        target = self.root / "target"
        target.mkdir()
        linked_directory = self.root / "directory-link"
        linked_directory.symlink_to(target, target_is_directory=True)
        linked_file = self.root / "file-link"
        linked_file.symlink_to(target / "missing.html")
        for output in (linked_directory / "catalog.html", linked_file):
            with self.assertRaises(CatalogError):
                write_html(self.catalog, output)
        self.assertEqual(list(target.iterdir()), [])
        self.assertTrue(linked_file.is_symlink())

    def test_temporary_name_collision_does_not_remove_existing_file(self):
        existing = self.root / ".catalog-fixed.tmp"
        existing.write_text("Preserve this existing fixture.")
        with patch("scripts.catalog_html.secrets.token_hex", return_value="fixed"), self.assertRaises(CatalogError):
            write_html(self.catalog, self.root / "catalog.html")
        self.assertEqual(existing.read_text(), "Preserve this existing fixture.")

    def test_failed_atomic_link_leaves_no_output_or_temp_file(self):
        with patch("scripts.catalog_html.os.link", side_effect=OSError), self.assertRaises(CatalogError):
            write_html(self.catalog, self.root / "catalog.html")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cleanup_failure_uses_fixed_diagnostic(self):
        with patch("scripts.catalog_html.os.unlink", side_effect=OSError("PRIVATE_MARKER_DO_NOT_ECHO")):
            with self.assertRaisesRegex(CatalogError, r"^Unable to finish HTML output cleanup\.$"):
                write_html(self.catalog, self.root / "catalog.html")
        self.assertTrue((self.root / "catalog.html").is_file())

    def test_parent_traversal_is_refused(self):
        with self.assertRaises(CatalogError):
            write_html(self.catalog, self.root / "child" / ".." / "catalog.html")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cli_no_clobber_and_redacted_errors(self):
        output = self.root / "PRIVATE_MARKER_DO_NOT_ECHO.html"
        args = ["html", str(ROOT / "examples/synthetic.json"), "--as-of", "2024-01-03", "--output", str(output)]
        for expected in (0, 1):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(main(args), expected)
            self.assertNotIn("PRIVATE_MARKER", out.getvalue() + err.getvalue())
        parsed = InspectHTML(output.read_text())
        self.assertEqual(json.loads(parsed.scripts[0][1])["as_of"], "2024-01-03")

    def test_invalid_data_does_not_create_output(self):
        source = self.root / "input.json"
        source.write_text('{"records":[]}')
        output = self.root / "new" / "catalog.html"
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["html", str(source), "--output", str(output)]), 1)
        self.assertFalse(output.parent.exists())


if __name__ == "__main__":
    unittest.main()
