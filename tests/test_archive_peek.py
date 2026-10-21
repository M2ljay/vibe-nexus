"""Reading an archive's contents from its table of contents alone."""
import base64
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import archive_peek as ap  # noqa: E402
import peek_fixtures as fx  # noqa: E402

WANT = ["Mod/Paks/A_P.pak", "Mod/b.lua", "Mod/empty.txt"]


def reader(data):
    return lambda o, n: data[o:o + n]


class PeekTests(unittest.TestCase):
    def test_formats(self):
        for blob in (fx.T_7Z, fx.T2_7Z, fx.T_ZIP):
            data = base64.b64decode(blob)
            self.assertEqual(sorted(ap.listing(reader(data), len(data))), WANT)

    def test_not_archives(self):
        self.assertIsNone(ap.listing(reader(b"Rar!\x1a\x07\x01\x00" + b"\x00" * 100), 108))
        self.assertIsNone(ap.listing(reader(b""), 0))
        data = base64.b64decode(fx.T_7Z)[:40]
        self.assertIsNone(ap.listing(reader(data), len(data)))  # truncated

    def test_never_reads_too_much(self):
        data = base64.b64decode(fx.T_ZIP)
        with mock.patch.object(ap, "MAX_FETCH", 10):
            self.assertIsNone(ap.listing(reader(data), len(data)))


if __name__ == "__main__":
    unittest.main()
