"""DOOM (2016): mods as zips in Mods/, DOOMModLoader run after changes."""
import asyncio
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
import zipfile

from test_backend import main

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import experimental_games as eg  # noqa: E402
import generic_loaders as gl  # noqa: E402


class DoomTests(unittest.TestCase):
    def test_profile_and_asset(self):
        g = {"nexusDomain": "doom", "processName": "DOOMx64.exe"}
        self.assertTrue(eg.apply_doom_profile(g, main._doom_framework()))
        self.assertEqual((g["modsSubdir"], g["toolApply"], g["flatModExtensions"]), ("Mods", "doommodloader", [".zip"]))
        self.assertEqual(g["framework"]["loaderId"], "doommodloader")
        rel = [{"tag_name": "v1.1", "assets": [{"name": "DOOMModLoader-Linux-x64.zip"},
                                               {"name": "DOOMModLoader-Windows-x64.zip", "browser_download_url": "u"}]}]
        self.assertEqual(gl.pick_asset(rel, gl.LOADERS["doommodloader"], True)[1], "DOOMModLoader-Windows-x64.zip")

    def test_zip_mod(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, "Brutal", "generated", "decls"))
            open(os.path.join(d, "Brutal", "generated", "decls", "a.decl"), "w").close()
            out = main._doom_zip_mod(d, "Brutal Doom")
            self.assertEqual(len(out), 1)
            with zipfile.ZipFile(out[0]) as z:
                self.assertEqual(z.namelist(), ["generated/decls/a.decl"])
            inner = tempfile.mkdtemp()
            open(os.path.join(inner, "Mod.zip"), "w").close()
            open(os.path.join(inner, "readme.txt"), "w").close()
            self.assertEqual([os.path.basename(p) for p in main._doom_zip_mod(inner, "x")], ["Mod.zip"])
            shutil.rmtree(inner)
            prog = tempfile.mkdtemp()
            open(os.path.join(prog, "dinput8.dll"), "w").close()
            self.assertEqual(main._doom_zip_mod(prog, "x"), [])
            shutil.rmtree(prog)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_apply(self):
        root = main._game_dir("DOOM")
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(os.path.join(root, "Mods"))
        game = {"nexusDomain": "doom", "installDirName": "DOOM"}
        r = asyncio.new_event_loop().run_until_complete(main._doom_apply(game))
        self.assertIn("Step 1", r["error"])
        open(os.path.join(root, "DOOMModLoader.exe"), "w").close()
        open(os.path.join(root, "Mods", "a.zip"), "w").close()
        with unittest.mock.patch.object(main, "_doom_run_loader", lambda r: (0, "done")):
            r = asyncio.new_event_loop().run_until_complete(main._doom_apply(game))
        self.assertEqual((r["ok"], r["count"]), (True, 1))
        with unittest.mock.patch.object(main, "_doom_run_loader", lambda r: (1, "ERROR: bad decl\n")):
            r = asyncio.new_event_loop().run_until_complete(main._doom_apply(game))
        self.assertIn("bad decl", r["error"])
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
