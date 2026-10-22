"""Final Fantasy IX (Memoria), GTA III archives, Forza paths."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import experimental_games as eg  # noqa: E402
import gta_img  # noqa: E402
import memoria  # noqa: E402


class MemoriaTests(unittest.TestCase):
    def test_folders(self):
        self.assertEqual(memoria.mod_folders(["PSXHUD/ModDescription.xml", "PSXHUD/StreamingAssets/x.bundle",
                                              "PSXHUD/Memoria.ini"]), ["PSXHUD"])
        self.assertEqual(memoria.mod_folders(["DKR_Alt/DragonKnightRising/FF9_Data/embeddedasset/text/a.mes"]),
                         ["DKR_Alt/DragonKnightRising"])
        self.assertEqual(memoria.mod_folders(["BlackCat/ModDescription.xml",
                                              "BlackCat/AlternateFantasy/StreamingAssets/Data/x.csv"]), ["BlackCat"])
        feats = memoria.mod_folders([f"Sh1nRa/Features/{n}/StreamingAssets/a.png" for n in ("A", "B")])
        self.assertEqual(feats, ["Sh1nRa/Features/A", "Sh1nRa/Features/B"])
        self.assertEqual(memoria.mod_folders(["StreamingAssets/x.bin"]), [""])
        self.assertEqual(memoria.plan(["StreamingAssets/x.bin"], "Mine"), [("StreamingAssets/x.bin", "Mine/StreamingAssets/x.bin")])

    def test_ini(self):
        text = "[Mod]\n\t; comment\nFolderNames = \"UserMod\", \"Old\"\nPriorities = \n\n[Font]\nEnabled = 0\n"
        out = memoria.set_folder_names(text, ["New", "PSXHUD"], {"New", "PSXHUD", "Old"})
        self.assertIn('FolderNames = "New", "PSXHUD", "UserMod"', out)
        self.assertIn("[Font]", out)
        self.assertIn("FolderNames", memoria.set_folder_names("", ["A"], {"A"}))

    def test_classify(self):
        g = {"nexusDomain": "finalfantasy9", "installDirName": "FINAL FANTASY IX"}
        memoria.apply_ff9_profile(g)
        self.assertEqual(g["toolApply"], "memoria")
        self.assertEqual(eg.classify_mod(["PSXHUD/ModDescription.xml", "PSXHUD/StreamingAssets/a.bundle"],
                                         g, set(), {}, False, {}), "tool_managed")
        self.assertTrue(memoria.patch_ok("V Done"))
        self.assertFalse(memoria.patch_ok("X The patching could only complete 40%"))


class GtaImgTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "models"))
        self.orig = {"gta3": [("a.dff", b"A" * 3000), ("b.txd", b"B" * 100)], "txd": [("b.txd", b"b" * 50)]}
        for base, items in self.orig.items():
            img, entries, sec = b"", [], 0
            for n, data in items:
                pad = (-len(data)) % 2048
                img += data + b"\0" * pad
                size = (len(data) + pad) // 2048
                entries.append([sec, size, n])
                sec += size
            with open(os.path.join(self.root, "models", base + ".img"), "wb") as f:
                f.write(img)
            with open(os.path.join(self.root, "models", base + ".dir"), "wb") as f:
                f.write(gta_img.build_dir(entries))

    def tearDown(self):
        shutil.rmtree(self.root)

    def entry(self, base, name):
        with open(os.path.join(self.root, "models", base + ".dir"), "rb") as f:
            for o, s, n in gta_img.parse_dir(f.read()):
                if n == name:
                    with open(os.path.join(self.root, "models", base + ".img"), "rb") as g:
                        g.seek(o * 2048)
                        return g.read(s * 2048).rstrip(b"\0")
        return None

    def test_rebuild_and_restore(self):
        self.assertEqual(gta_img.names(self.root), {"a.dff": "models/gta3.img", "b.txd": "models/gta3.img"})
        mod = os.path.join(self.root, "mod_b.txd")
        with open(mod, "wb") as f:
            f.write(b"NEW" * 10)
        new = os.path.join(self.root, "c.dff")
        with open(new, "wb") as f:
            f.write(b"C")
        size0 = os.path.getsize(os.path.join(self.root, "models", "gta3.img"))
        st = gta_img.rebuild(self.root, {}, [("b.txd", mod), ("c.dff", new)])
        self.assertEqual(self.entry("gta3", "b.txd"), b"NEW" * 10)
        self.assertEqual(self.entry("txd", "b.txd"), b"NEW" * 10)  # both archives
        self.assertEqual(self.entry("gta3", "c.dff"), b"C")
        self.assertEqual(self.entry("gta3", "a.dff"), b"A" * 3000)
        st = gta_img.rebuild(self.root, st, [])  # mod removed
        self.assertEqual(self.entry("gta3", "b.txd"), b"B" * 100)
        self.assertIsNone(self.entry("gta3", "c.dff"))
        self.assertEqual(os.path.getsize(os.path.join(self.root, "models", "gta3.img")), size0)

    def test_planner_routes_into_archive(self):
        idx = eg.index_game_files(self.root)
        self.assertEqual(idx["a.dff"], ["models/gta3.img::a.dff"])
        g = {"nexusDomain": "gta3", "installDirName": "GTA", "processName": "gta3.exe"}
        gta_img.apply_gta_profile(g)
        files = ["[III] Upscale/a.dff", "[III] Upscale/readme.txt"]
        p = eg.plan_root_install(files, {"models", "gta3.exe"}, eg.index_game_dirs(self.root), "Mods", "",
                                 idx, "", "GTA")
        self.assertEqual(p, [("[III] Upscale/a.dff", "models/gta3.img::a.dff")])
        self.assertEqual(eg.classify_mod(files, g, {"models"}, eg.index_game_dirs(self.root), False, idx),
                         "game_folder")
        cs = eg.plan_root_install(["health100.cs", "health100.txt"], {"models"}, {}, "Mods", "", idx, "", "")
        self.assertEqual(cs, [("health100.cs", "cleo/health100.cs")])
        self.assertEqual(g["framework"]["with"], ["cleo3"])


class ForzaTests(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(list(eg.alias_paths(["Content/mediapc/Audio/x.xml", "mediapc/Camera/y.ini"],
                                             "forzahorizon6")),
                         ["media/Audio/x.xml", "media/Camera/y.ini"])
        g = {"nexusDomain": "forzahorizon6", "engine": "unknown", "processName": "forzahorizon6.exe"}
        self.assertEqual(eg.classify_mod(["mediapc/Camera/CameraSettings.ini"], g, {"media"},
                                         {"media": ["media"]}, False, {}), "game_folder")


if __name__ == "__main__":
    unittest.main()


class PersonaTests(unittest.TestCase):
    def test_old_and_new_layouts(self):
        import reloaded_ii
        g = {"nexusDomain": "persona4golden", "toolApply": "reloaded", "engine": "reloaded"}
        roots = {"data.cpk", "data_e.cpk", "P4G.exe"}
        self.assertEqual(eg.classify_mod(["ReaperEverywhere/data00004/field/script/dungeon.bf"], g, roots, {},
                                         False, {}), "old_version")
        self.assertEqual(eg.classify_mod(["BGM.xwb"], g, roots, {}, False, {}), "old_version")
        self.assertEqual(eg.classify_mod(["Culprit/tblpatches/SKILL_Patches.tbp", "Culprit/Package.xml"], g, roots,
                                         {}, False, {}), "old_version")
        files = ["My Mod/data_e/init_free/battle/AICALC.TBL", "My Mod/readme.txt"]
        self.assertEqual(eg.classify_mod(files, g, roots, {}, False, {}), "tool_managed")
        self.assertEqual(reloaded_ii.persona_wrap(files, {"data_e.cpk"}),
                         [(files[0], "P5REssentials/CPK/data_e.cpk/init_free/battle/AICALC.TBL")])
        cfg = reloaded_ii.wrapped_mod_config("nexus.x", "X", "", "p4g.exe")
        self.assertEqual(cfg["ModDependencies"], ["p5rpc.modloader"])


class BeatSaberTests(unittest.TestCase):
    def test_songs_and_sabers(self):
        g = {"nexusDomain": "beatsaber", "engine": "unity"}
        eg.apply_beatsaber_profile(g)
        song = ["info.dat", "cover.jpg", "Hard.dat", "song.egg"]
        self.assertEqual(dict(eg.beatsaber_plan(song, "Tenacious D"))["song.egg"],
                         "Beat Saber_Data/CustomLevels/Tenacious D/song.egg")
        pack = [f"Beat Sage_ Call Me/{n}" for n in ("Info.dat", "song.ogg")] + ["Other/info.dat", "Other/a.ogg"]
        dsts = {d for _s, d in eg.beatsaber_plan(pack, "x")}
        self.assertIn("Beat Saber_Data/CustomLevels/Beat Sage_ Call Me/song.ogg", dsts)
        self.assertIn("Beat Saber_Data/CustomLevels/Other/a.ogg", dsts)
        self.assertEqual(eg.beatsaber_plan(["Virtuous Contract & Cruel Oath.saber"], "x"),
                         [("Virtuous Contract & Cruel Oath.saber", "CustomSabers/Virtuous Contract & Cruel Oath.saber")])
        self.assertEqual(eg.classify_mod(["Pack/a.zip", "Pack/b.zip"], g, set(), {}, False, {}), "game_folder")
        self.assertNotIn("framework", g)


class SmallRules(unittest.TestCase):
    def test_dlss_and_ff9_assets(self):
        self.assertEqual(eg.plan_root_install(["nvngx_dlssnr.dll"], {"forzahorizon6.exe"}, {}, "", "", {}, "", ""),
                         [("nvngx_dlssnr.dll", "nvngx_dlssnr.dll")])
        fidx = {"sharedassets2.assets": ["x64/FF9_Data/sharedassets2.assets", "x86/FF9_Data/sharedassets2.assets"]}
        g = {"nexusDomain": "finalfantasy9", "processName": "x64/FF9.exe"}
        self.assertEqual(eg.plan_root_install(["sharedassets2.assets"], {"x64", "x86"}, {}, "", "x64", fidx,
                                              eg.content_root(g), ""),
                         [("sharedassets2.assets", "x64/FF9_Data/sharedassets2.assets")])


class REEngineTests(unittest.TestCase):
    def test_re2(self):
        import re_engine
        g = {"nexusDomain": "residentevil22019"}
        self.assertTrue(re_engine.apply_re_profile(g, True))
        self.assertEqual(re_engine.release_url(g), re_engine.RELEASE + "RE2.zip")
        stm = ["Mod/modinfo.ini", "Mod/screenshot.jpg",
               "Mod/natives/stm/sectionroot/character/player/pl1000/pl1003/a.tex.34"]
        self.assertEqual(re_engine.plan(stm), [(stm[2], "natives/stm/sectionroot/character/player/pl1000/pl1003/a.tex.34")])
        self.assertEqual(eg.classify_mod(stm, g, set(), {}, False, {}), "game_folder")
        x64 = ["natives/x64/objectroot/prefab/character/enemy/em6200.pfb.16", "modinfo.ini"]
        self.assertEqual(eg.classify_mod(x64, g, set(), {}, False, {}), "old_version")
        g11 = {"nexusDomain": "residentevil22019"}
        re_engine.apply_re_profile(g11, False)
        self.assertEqual(eg.classify_mod(x64, g11, set(), {}, False, {}), "game_folder")
        self.assertTrue(re_engine.release_url(g11).endswith("RE2_TDB66.zip"))
        plug = ["reframework/plugins/re2r_ultimate_trainer.dll", "modinfo.ini", "re2r_ut_trainer.png"]
        self.assertEqual(re_engine.plan(plug), [(plug[0], plug[0])])
        dlc = ["920563/re_dlc_000.pak", "natives/stm/x/a.pfb.17", "readme.txt"]
        self.assertEqual(len(re_engine.plan(dlc)), 2)
        self.assertIsNone(re_engine.plan(["Updater.exe", "Data/Data.pkg"]))
        cfg = re_engine.enable_loose_loader("Menu_Open=false\nLooseFileLoader_Enabled=false\n")
        self.assertIn("LooseFileLoader_Enabled=true", cfg)
        self.assertNotIn("Enabled=false", cfg)


class REBuildFlagTests(unittest.TestCase):
    def test_flags_dx11_mods_on_rt(self):
        from test_backend import main
        import re_engine
        g = {"nexusDomain": "residentevil22019", "installDirName": "RE2 test", "appId": 883710}
        re_engine.apply_re_profile(g, True)
        main._save_settings({"experimental_games": {"883710": g}, "installed": {"residentevil22019": {
            "Old": {"mode": "files", "target": ".", "files": ["natives/x64/a.tex.10"]},
            "New": {"mode": "files", "target": ".", "files": ["natives/stm/a.tex.34"]}}}})
        self.assertEqual(main._flag_wrong_build(g), 1)
        recs = main._load_settings()["installed"]["residentevil22019"]
        self.assertIn("dx11_non-rt", recs["Old"]["warning"])
        self.assertNotIn("warning", recs["New"])
