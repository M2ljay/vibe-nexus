"""Saints Row 2: loose files into mods/ (Juiced Patch), packfiles beside the game."""
import os
import shutil
import stat
import sys
import tempfile
import unittest

from test_backend import main  # stubs decky/aiohttp and imports main.py

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import experimental_games as eg  # noqa: E402
import generic_loaders as gl  # noqa: E402


class SR2Tests(unittest.TestCase):
    def game(self):
        g = {"nexusDomain": "saintsrow2", "modsSubdir": "Mods", "mergeInto": "x"}
        self.assertTrue(eg.apply_sr2_profile(g, main._sr2_framework()))
        return g

    def test_profile(self):
        g = self.game()
        self.assertEqual(g["modsSubdir"], "mods")
        self.assertNotIn("mergeInto", g)
        self.assertEqual(g["framework"]["loaderId"], "sr2juiced")
        self.assertIn("Juiced Patch", g["framework"]["warning"])
        self.assertFalse(eg.apply_sr2_profile({"nexusDomain": "saintsrow3"}, {}))

    def test_classification(self):
        g = self.game()
        roots = {"SR2_pc.exe", "patch.vpp_pc", "sounds.vpp_pc"}

        def verdict(paths):
            return eg.classify_mod(paths, g, roots, {}, False, {})
        self.assertEqual(verdict(["Mod Files/npc_wong.xtbl", "Mod Files/cnpc_wong.cvtf"]), "mods_folder")
        self.assertEqual(verdict(["Baggy/cmuns_uchild_u.g_peg_pc", "Read Me.txt"]), "mods_folder")
        self.assertEqual(verdict(["V1/Bush/patch.vpp_pc", "V1/Bush/shaders_pc"]), "mods_folder")
        self.assertEqual(verdict(["_1084202402000042003690042321200701.bbsave", "profile.dat"]),
                         "save_file")
        self.assertEqual(verdict(["MY SR2 PRESET.ini"]), "reshade_preset")

    def test_variants(self):
        flat = ["SR2 Visual Overhaul/The Mod/time_of_day.xtbl",
                "SR2 Visual Overhaul/The Mod/weather_time_of_day.xtbl",
                "SR2 Visual Overhaul/Optional/Darker Nights/weather_time_of_day.xtbl"]
        alts = eg.flat_variants(flat)
        self.assertEqual(sorted(alts), ["SR2 Visual Overhaul/Optional/Darker Nights",
                                        "SR2 Visual Overhaul/The Mod"])
        picked = eg.pick_flat_variant(flat, "SR2 Visual Overhaul/Optional/Darker Nights")
        self.assertEqual(picked, ["SR2 Visual Overhaul/Optional/Darker Nights/weather_time_of_day.xtbl",
                                  "SR2 Visual Overhaul/The Mod/time_of_day.xtbl"])
        self.assertEqual(eg.flat_variants(["Mod Files/a.xtbl", "Mod Files/b.cvtf"]), {})

    def test_juiced_asset(self):
        spec = gl.LOADERS["sr2juiced"]
        rel = [{"tag_name": "v8.0.1", "assets": [{"name": "Source.zip"},
                                                 {"name": "SR2_JUICED.zip", "browser_download_url": "u"}]}]
        self.assertEqual(gl.pick_asset(rel, spec, False), ("v8.0.1", "SR2_JUICED.zip", "u"))


class ExePatchTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "patches"))
        with open(os.path.join(self.root, "SR2_pc.exe"), "wb") as f:
            f.write(b"steam")
        open(os.path.join(self.root, "patches", "JuicedSteamXDel.vcdiff"), "wb").close()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _xdelta(self, works):
        p = os.path.join(self.root, "patches", "xdelta3.exe")
        body = ('python3 -c "import sys;open(sys.argv[1],\'wb\').write(b\'P\'*(2<<20))" "$6"\n'
                if works else "exit 1\n")
        with open(p, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)

    def read(self, name):
        with open(os.path.join(self.root, name), "rb") as f:
            return f.read()

    def test_patch_keeps_original_and_restores(self):
        self._xdelta(True)
        self.assertEqual(main._sr2_patch_exe(self.root), "")
        self.assertEqual(self.read("sr2_pc_unpatched.exe"), b"steam")
        self.assertEqual(len(self.read("SR2_pc.exe")), 2 << 20)
        # Again (Step 1 pressed twice): still built from the original.
        self.assertEqual(main._sr2_patch_exe(self.root), "")
        self.assertEqual(self.read("sr2_pc_unpatched.exe"), b"steam")
        self.assertTrue(main._sr2_restore_exe(self.root))
        self.assertEqual(self.read("SR2_pc.exe"), b"steam")

    def test_failed_patch_never_leaves_the_game_without_an_exe(self):
        self._xdelta(False)
        self.assertIn("xdelta", main._sr2_patch_exe(self.root))
        self.assertEqual(self.read("SR2_pc.exe"), b"steam")
        # The state Juiced's own .bat left on 2026-10-21: original renamed, no exe.
        os.remove(os.path.join(self.root, "SR2_pc.exe"))
        main._sr2_patch_exe(self.root)
        self.assertEqual(self.read("SR2_pc.exe"), b"steam")


if __name__ == "__main__":
    unittest.main()
