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


class HealTests(ExePatchTests):
    def test_steam_restore_is_undone(self):
        import unittest.mock
        self._xdelta(True)
        with open(os.path.join(self.root, "DFEngine.dll"), "wb") as f:
            f.write(b"J" * (3 << 20))
        open(os.path.join(self.root, "juiced.ini"), "w").close()
        main._sr2_patch_exe(self.root)
        keep = tempfile.mkdtemp()
        game = {"nexusDomain": "saintsrow2", "installDirName": "x"}
        main._save_settings({"experimental_frameworks": {"saintsrow2/0": {"files": []}}})
        with unittest.mock.patch.object(main, "SR2_KEEP", keep), \
                unittest.mock.patch.object(main, "_game_dir", lambda _d: self.root):
            self.assertEqual(main._sr2_heal(game), "")  # learns the Juiced state
            self.assertEqual(main._sr2_heal(game), "")  # nothing changed
            # Steam's verify: its own DFEngine.dll and exe come back.
            with open(os.path.join(self.root, "DFEngine.dll"), "wb") as f:
                f.write(b"vanilla")
            shutil.copyfile(os.path.join(self.root, "sr2_pc_unpatched.exe"),
                            os.path.join(self.root, "SR2_pc.exe"))
            self.assertEqual(main._sr2_heal(game), "DFEngine.dll, SR2_pc.exe")
            self.assertEqual(len(self.read("DFEngine.dll")), 3 << 20)
            self.assertEqual(len(self.read("SR2_pc.exe")), 2 << 20)
            # Juiced's own first-run edit of the exe is not "Steam's exe".
            with open(os.path.join(self.root, "SR2_pc.exe"), "ab") as f:
                f.write(b"laa")
            self.assertEqual(main._sr2_heal(game), "")
            self.assertEqual(self.read("sr2_pc_unpatched.exe"), b"steam")
        shutil.rmtree(keep, ignore_errors=True)

    def test_builder_mods_refused(self):
        self.assertTrue(eg.sr2_builder(["GOTR/MY_CUSTOM_PATCH/preload_anim.tbl"]))
        self.assertTrue(eg.sr2_builder(["GOTR/optional_mod_stuff/x.xtbl"]))
        self.assertFalse(eg.sr2_builder(["Mod Files/x.xtbl"]))
        g = {"nexusDomain": "saintsrow2"}
        eg.apply_sr2_profile(g, {})
        self.assertEqual(eg.classify_mod(["G/MY_CUSTOM_PATCH/a.xtbl", "G/b.xtbl"], g, set(), {}, False, {}),
                         "program")



class GotRTests(unittest.TestCase):
    B = "Gentlemen_of_the_Row_Saints_Row_2_Super_Mod_v1.9.2/"
    FILES = [B + "Create_Custom_GotR_v1.9.2.bat", B + "readme.txt",
             B + "MY_CUSTOM_PATCH/preload_anim.tbl",
             B + "optional_mod_stuff/preload.tbl", B + "optional_mod_stuff/preload_anim.tbl",
             B + "optional_mod_stuff/modified/weapons.xtbl",
             B + "optional_mod_stuff/modified/sub/cnpc_x.cvtf",
             B + "optional_mod_stuff/modified/notes.txt",
             B + "optional_mod_stuff/optional_mods/Classic HUD/hud.xtbl",
             B + "optional_mod_stuff/optional_mods/Classic HUD/readme.txt",
             B + "tools/sr2_chunk.exe"]

    def test_plan(self):
        self.assertEqual(eg.gotr_base(self.FILES), self.B)
        self.assertEqual(eg.gotr_options(self.FILES), [self.B + "optional_mod_stuff/optional_mods/Classic HUD"])
        dst = {d: s for s, d in eg.gotr_plan(self.FILES)}
        self.assertEqual(sorted(dst), ["mods/GotR/cnpc_x.cvtf", "mods/GotR/preload.tbl",
                                       "mods/GotR/preload_anim.tbl", "mods/GotR/weapons.xtbl"])
        self.assertEqual(dst["mods/GotR/preload_anim.tbl"], self.B + "optional_mod_stuff/preload_anim.tbl")
        opt = eg.gotr_plan(self.FILES, [self.B + "optional_mod_stuff/optional_mods/Classic HUD"])
        self.assertIn((self.B + "optional_mod_stuff/optional_mods/Classic HUD/hud.xtbl",
                       "mods/GotR/Optional/hud.xtbl"), opt)
        self.assertIsNone(eg.gotr_base(["Mod Files/a.xtbl"]))
        g = {"nexusDomain": "saintsrow2"}
        eg.apply_sr2_profile(g, {})
        self.assertEqual(eg.classify_mod(self.FILES, g, set(), {}, False, {}), "mods_folder")

    def test_loose(self):
        base = "mods\nmods/JUICED - Credits\n"
        once = eg.loose_with_gotr(base)
        self.assertEqual(once, base + "mods/GotR/Optional\nmods/GotR\n")
        self.assertEqual(eg.loose_with_gotr(once), once)
        self.assertEqual(eg.loose_without_gotr(once), base)

    def test_install_and_uninstall(self):
        root = tempfile.mkdtemp()
        scratch = tempfile.mkdtemp()
        try:
            with open(os.path.join(root, "loose.txt"), "w") as f:
                f.write("mods\n")
            for rel in self.FILES:
                p = os.path.join(scratch, *rel.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w") as f:
                    f.write(rel)
            main._save_settings({"installed": {"saintsrow2": {
                "Nude": {"name": "Nude", "mode": "files", "target": ".", "files": ["patch.vpp_pc"]}}}})
            r = main._sr2_install_gotr(scratch, self.FILES, root, "saintsrow2", {"name": "Gentlemen of the Row"})
            self.assertFalse(r["ok"])
            self.assertIn("Nude", r["error"])
            main._save_settings({})
            os.makedirs(scratch, exist_ok=True)
            for rel in self.FILES:
                p = os.path.join(scratch, *rel.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w") as f:
                    f.write(rel)
            r = main._sr2_install_gotr(scratch, self.FILES, root, "saintsrow2", {"name": "Gentlemen of the Row"})
            self.assertTrue(r["ok"], r)
            self.assertTrue(os.path.isfile(os.path.join(root, "mods", "GotR", "weapons.xtbl")))
            self.assertTrue(os.path.isdir(os.path.join(root, "mods", "GotR", "Optional")))
            self.assertTrue(os.path.isfile(os.path.join(root, "gotr.txt")))
            with open(os.path.join(root, "loose.txt")) as f:
                self.assertIn("mods/GotR\n", f.read())
            settings = main._load_settings()
            self.assertTrue(main._remove_files_record("saintsrow2", r["folder"], root, settings))
            self.assertFalse(os.path.exists(os.path.join(root, "mods", "GotR")))
            self.assertFalse(os.path.exists(os.path.join(root, "gotr.txt")))
            with open(os.path.join(root, "loose.txt")) as f:
                self.assertEqual(f.read(), "mods\n")
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
