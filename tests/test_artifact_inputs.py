"""Artifact loaders reject nonregular inputs before reading private bytes."""
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import maintenance as m
from scripts.catalog import CatalogError

ROOT = Path(__file__).resolve().parents[1]


class ArtifactInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_regular_json_and_exact_byte_boundary_remain_supported(self):
        path = self.directory / "fictional.json"
        payload = b'{"fictional":true}\n'
        path.write_bytes(payload)
        with patch.object(m, "MAX_ARTIFACT_BYTES", len(payload)):
            self.assertEqual(m.read_artifact(path), {"fictional": True})
            self.assertEqual(m.read_artifact(str(path)), {"fictional": True})
        with patch.object(m, "MAX_ARTIFACT_BYTES", len(payload) - 1), self.assertRaises(CatalogError):
            m.read_artifact(path)

    def test_bounded_read_still_rejects_growth_after_metadata_check(self):
        path = self.directory / "fictional.json"
        path.write_bytes(b'{"fictional":true}\n')
        metadata = path.stat()
        smaller = type("FileState", (), {"st_mode": metadata.st_mode, "st_size": 0})()
        with patch.object(m, "MAX_ARTIFACT_BYTES", 5), patch.object(m.os, "fstat", return_value=smaller):
            with self.assertRaises(CatalogError) as failed:
                m.read_artifact(path)
        self.assertEqual(str(failed.exception), "An artifact exceeds the 32 MiB input limit.")

    def test_opened_file_descriptor_is_closed_after_parse_failure(self):
        path = self.directory / "PRIVATE_MALFORMED.json"
        path.write_bytes(b'{"PRIVATE_CANARY":')
        opened = []
        original = os.open
        def capture(*args, **kwargs):
            descriptor = original(*args, **kwargs)
            opened.append(descriptor)
            return descriptor
        with patch.object(os, "open", side_effect=capture), self.assertRaises(CatalogError) as failed:
            m.read_artifact(path)
        self.assertNotIn("PRIVATE_", str(failed.exception))
        self.assertEqual(len(opened), 1)
        with self.assertRaises(OSError) as closed:
            os.fstat(opened[0])
        self.assertEqual(closed.exception.errno, errno.EBADF)


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NONBLOCK"), "POSIX regular-file input checks")
class NonregularArtifactInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def invoke(self, source, module):
        output = self.directory / "private-output" / "result.json"
        command = (["export", str(source), "--kind", "summary"] if module == "scripts.resolution"
                   else ["review", str(source)])
        try:
            result = subprocess.run([sys.executable, "-m", module, *command, "--output", str(output)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired:
            raise AssertionError("Artifact input blocked instead of rejecting a nonregular file.") from None
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("PRIVATE_", result.stderr)
        self.assertNotIn(str(self.directory), result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertLess(len(result.stderr), 200)
        self.assertFalse(output.parent.exists())

    def test_fifo_without_writer_fails_in_both_cli_consumers(self):
        fifo = self.directory / "PRIVATE_PIPE.json"
        os.mkfifo(fifo)
        for module in ("scripts.resolution", "scripts.maintenance"):
            with self.subTest(module=module):
                self.invoke(fifo, module)

    def test_link_to_fifo_is_rejected_without_waiting_for_a_writer(self):
        fifo = self.directory / "PRIVATE_PIPE.json"
        os.mkfifo(fifo)
        alias = self.directory / "PRIVATE_PIPE_ALIAS.json"
        alias.symlink_to(fifo)
        self.invoke(alias, "scripts.resolution")

    def test_directories_and_character_devices_are_rejected_before_read(self):
        for path in (self.directory, Path(os.devnull)):
            with self.subTest(kind="directory" if path == self.directory else "device"):
                with self.assertRaises(CatalogError) as failed:
                    m.read_artifact(path)
                self.assertEqual(str(failed.exception), "Artifact input must be a regular JSON file.")
                self.invoke(path, "scripts.resolution")

    def test_links_to_regular_inputs_keep_existing_read_only_behavior(self):
        source = self.directory / "regular.json"
        source.write_bytes(b'{"fictional":"content"}\n')
        alias = self.directory / "alias.json"
        hardlink = self.directory / "hardlink.json"
        parent_alias = self.directory / "parent-alias"
        alias.symlink_to(source)
        os.link(source, hardlink)
        parent_alias.symlink_to(self.directory, target_is_directory=True)
        original = source.read_bytes()
        for path in (source, alias, hardlink, parent_alias / source.name):
            self.assertEqual(m.read_artifact(path), {"fictional": "content"})
        self.assertEqual(source.read_bytes(), original)

    def test_descriptor_is_closed_after_nonregular_rejection(self):
        opened = []
        original = os.open
        def capture(*args, **kwargs):
            descriptor = original(*args, **kwargs)
            opened.append(descriptor)
            return descriptor
        with patch.object(os, "open", side_effect=capture), self.assertRaises(CatalogError):
            m.read_artifact(self.directory)
        self.assertEqual(len(opened), 1)
        with self.assertRaises(OSError) as closed:
            os.fstat(opened[0])
        self.assertEqual(closed.exception.errno, errno.EBADF)

    def test_opened_descriptor_is_checked_before_payload_read(self):
        path = self.directory / "fictional.json"
        path.write_bytes(b'{"fictional":true}\n')
        with patch.object(m.os, "fstat", return_value=type("FileState", (), {"st_mode": 0})()), \
                patch.object(m.os, "fdopen", side_effect=AssertionError("Nonregular payload must not be read")), \
                self.assertRaises(CatalogError):
            m.read_artifact(path)


if __name__ == "__main__":
    unittest.main()
