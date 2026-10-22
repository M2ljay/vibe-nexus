"""Installer .exe kinds, silent switches, self-extracting archives."""
import base64
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import archive_peek as ap  # noqa: E402
import installers  # noqa: E402
import peek_fixtures as fx  # noqa: E402

STUB = b"MZ" + b"\x90" * 4000


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def exe(self, name, data):
        p = os.path.join(self.d, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_kinds(self):
        self.assertEqual(installers.kind(self.exe("a.exe", STUB + b"Inno Setup Setup Data (6.2.0)")), "inno")
        self.assertEqual(installers.kind(self.exe("b.exe", STUB + b"\xef\xbe\xad\xdeNullsoftInst")), "nsis")
        seven = base64.b64decode(fx.T_7Z)
        self.assertEqual(installers.kind(self.exe("c.exe", STUB + seven)), "7z")
        self.assertEqual(installers.kind(self.exe("d.exe", STUB + base64.b64decode(fx.RAR5))), "rar")
        self.assertEqual(installers.kind(self.exe("e.exe", STUB + base64.b64decode(fx.T_ZIP))), "zip")
        self.assertEqual(installers.kind(self.exe("f.exe", STUB)), "")
        self.assertEqual(installers.kind("x.msi"), "msi")

    def test_silent_and_auto(self):
        self.assertEqual(installers.silent_args("nsis", "s.exe", "C:\\Games\\HK\\"), ["s.exe", "/S", "/D=C:\\Games\\HK"])
        self.assertIn("/VERYSILENT", installers.silent_args("inno", "s.exe", "C:\\G"))
        self.assertTrue(installers.auto_ok("inno", "The Git Gud Patch", "Full Installer.exe"))
        self.assertFalse(installers.auto_ok("nsis", "BSManager", "BSManager Setup.exe"))
        self.assertFalse(installers.auto_ok("", "Mod", "x.exe"))

    def test_peek_inside_sfx(self):
        for blob in (fx.T_7Z, fx.T_ZIP, fx.RAR5):
            data = STUB + base64.b64decode(blob)
            self.assertTrue(ap.listing(lambda o, n: data[o:o + n], len(data)), blob[:10])


class UnpackSfxTests(unittest.TestCase):
    def test_unpack_zip_and_7z(self):
        from test_backend import main
        d = tempfile.mkdtemp()
        p = os.path.join(d, "mod.exe")
        with open(p, "wb") as f:
            f.write(STUB + base64.b64decode(fx.T_ZIP))
        out = os.path.join(d, "out")
        self.assertTrue(main._unpack_sfx(p, out))
        self.assertTrue(os.path.isfile(os.path.join(out, "Mod", "b.lua")))
        shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
