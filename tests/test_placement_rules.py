"""Placement rules from the 2026-10-22 library check (real archive listings)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import experimental_games as eg  # noqa: E402

BATMAN = {"nexusDomain": "batmanarkhamorigins", "installDirName": "Batman Arkham Origins",
          "processName": "SinglePlayer/Binaries/Win32/BatmanOrigins.exe", "engine": "unknown",
          "modsSubdir": "Mods"}
B_ROOTS = {"Mods", "Online", "SinglePlayer"}
B_DIRS = {"singleplayer": ["SinglePlayer"], "online": ["Online"], "dlc": ["SinglePlayer/DLC"],
          "bmgame": ["SinglePlayer/BMGame", "Online/BMGame"],
          "cookedpcconsole": ["SinglePlayer/BMGame/CookedPCConsole", "Online/BMGame/CookedPCConsole"]}
B_FILES = {"bmgame.upk": ["SinglePlayer/BMGame/CookedPCConsole/BmGame.upk",
                          "Online/BMGame/CookedPCConsole/BmGame.upk"],
           "startup.upk": ["SinglePlayer/BMGame/CookedPCConsole/Startup.upk",
                           "Online/BMGame/CookedPCConsole/Startup.upk"],
           "bcchar_batman_sf.upk": ["SinglePlayer/BMGame/CookedPCConsole/BCChar_Batman_SF.upk"]}


def plan(files, game=BATMAN, roots=B_ROOTS, dirs=B_DIRS, fidx=B_FILES):
    return eg.plan_root_install(files, roots, dirs, game.get("modsSubdir", ""),
                                eg.exe_dir_of(game.get("processName") or ""), fidx,
                                eg.content_root(game), game.get("installDirName", ""))


def verdict(files, game=BATMAN, roots=B_ROOTS, dirs=B_DIRS, fidx=B_FILES):
    return eg.classify_mod(files, game, roots, dirs, False, fidx)


class BatmanRules(unittest.TestCase):
    def test_suit_slot_goes_to_dlc(self):
        files = ["BM3_Ice/Batman_MK8/Batman_MK8.int", "BM3_Ice/Batman_MK8/BCChar_Batman_MK8_SF.upk",
                 "BM3_Ice/Batman_MK8/DLC_MK8-BmGame.ini", "BM3_Ice/Batman_MK8/Playable_Batman_MK8_SF.upk"]
        p = dict(plan(files))
        self.assertEqual(p["BM3_Ice/Batman_MK8/DLC_MK8-BmGame.ini"], "SinglePlayer/DLC/Batman_MK8/DLC_MK8-BmGame.ini")
        self.assertEqual(verdict(files), "game_folder")

    def test_pack_of_suits(self):
        files = [f"Batman - {n}/{f}" for n in ("Black 70s Classic Suit", "Blue 70s Suit")
                 for f in ("Batman_X.int", "DLC_X-BmGame.ini", "BCChar_Batman_X_SF.upk")]
        dsts = {d for _s, d in plan(files)}
        self.assertIn("SinglePlayer/DLC/Batman - Blue 70s Suit/DLC_X-BmGame.ini", dsts)

    def test_replacement_with_originals_beside(self):
        files = [f"Remastered Batsuit 2.0/{w}/SinglePlayer/BMGame/CookedPCConsole/BCChar_Batman_SF.upk"
                 for w in ("MOD FILES", "Original Game Files")]
        self.assertEqual(plan(files), [(files[0], "SinglePlayer/BMGame/CookedPCConsole/BCChar_Batman_SF.upk")])

    def test_loose_upks_pick_singleplayer(self):
        self.assertEqual(dict(plan(["BmGame.upk", "Startup.upk"]))["BmGame.upk"],
                         "SinglePlayer/BMGame/CookedPCConsole/BmGame.upk")

    def test_texmod(self):
        self.assertEqual(verdict(["CJ's The Dark Knight Suit v.3.tpf"]), "texmod")

    def test_reshade_with_addon32_and_license(self):
        files = ["AOR/Arkham Origins Reimagined.ini", "AOR/LICENSE", "AOR/ReshadeEffectShaderToggler.addon32",
                 "AOR/reshade-shaders/Shaders/DH/dh_uber_rt.fx", "AOR/reshade-shaders/Textures/x.png"]
        self.assertEqual(verdict(files), "reshade_preset")


class OtherGames(unittest.TestCase):
    def test_vampire_survivors_old_js(self):
        g = {"nexusDomain": "vampiresurvivors", "engine": "unity", "modsSubdir": "Mods"}
        self.assertEqual(verdict(["main.bundle.js"], g, set(), {}, {}), "old_version")

    def test_reshade_preset_named_default(self):
        g = {"nexusDomain": "deadisland", "engine": "unknown"}
        self.assertEqual(verdict(["DefaultPreset.ini", "READ ME.txt"], g, set(), {}, {}), "reshade_preset")
        self.assertTrue(eg.engine_config_ini("DefaultEngine.ini"))

    def test_slot_saves(self):
        g = {"nexusDomain": "theevilwithin", "engine": "unknown"}
        files = ["SLOT0/SLOT0/game_small.png", "SLOT0/SLOT0/inventory.zwei", "SLOT0/SLOT0/game.details", "readme.txt"]
        self.assertEqual(verdict(files, g, set(), {}, {}), "save_file")
        self.assertEqual(verdict(["DIDE/save_0.sav", "DIRDE/save_1.sar", "!!!README!!!.txt"], g, set(), {}, {}),
                         "save_file")

    def test_wrapper_named_like_the_game(self):
        g = {"nexusDomain": "theevilwithin", "engine": "unknown", "installDirName": "TheEvilWithin",
             "processName": "EvilWithin.exe"}
        files = ["readme.txt", "QuickSFV/QuickSFV.EXE", "QuickSFV/x.sfv",
                 "TheEvilWithin/base/bink/cs3019.bk2"]
        self.assertEqual(plan(files, g, {"base"}, {"base": ["base"], "bink": ["base/bink"]}, {}),
                         [("TheEvilWithin/base/bink/cs3019.bk2", "base/bink/cs3019.bk2")])

    def test_derpy_scripts(self):
        g = {"nexusDomain": "bullyscholarshipedition", "engine": "unknown", "processName": "Bully.exe"}
        files = ["_derpy_script_loader/scripts/better_controls/better_controls.lua", "readme.txt"]
        self.assertEqual(plan(files, g, {"Bully.exe"}, {}, {}),
                         [(files[0], files[0])])


class Alternatives(unittest.TestCase):
    def test_slow_slower_slowest(self):
        g = {"nexusDomain": "bullyscholarshipedition", "engine": "unknown", "processName": "Bully.exe"}
        files = [f"Slower Game Clock/{v}/_derpy_script_loader/scripts/{v}Clock.lua" for v in ("Slow", "Slower", "Slowest")]
        files.append("Slower Game Clock/ReadMe.txt")
        self.assertIsNone(plan(files, g, {"Bully.exe"}, {}, {}))
        v = eg.plan_variants(files, {"Bully.exe"}, {}, "", "", {}, "", "")
        self.assertEqual(sorted(v), ["Slow", "Slower", "Slowest"])
        self.assertEqual(v["Slower"], [(files[1], "_derpy_script_loader/scripts/SlowerClock.lua")])
        self.assertEqual(verdict(files, g, {"Bully.exe"}, {}, {}), "game_folder")

    def test_batman_slot_or_replace(self):
        w = "The Batman (Remastered)/"
        files = [w + "Default Suit (Original File Backups)/SinglePlayer/BMGame/CookedPCConsole/BCChar_Batman_SF.upk",
                 w + "fun (unecessary)  tip.txt",
                 w + "New Suit Slot/Batman_TheBat/Batman_TheBat.int",
                 w + "New Suit Slot/Batman_TheBat/DLC_TheBat-BmGame.ini",
                 w + "Replace Default Suit/SinglePlayer/BMGame/CookedPCConsole/BCChar_Batman_SF.upk"]
        args = (files, B_ROOTS, B_DIRS, "Mods", "SinglePlayer/Binaries/Win32", B_FILES, "SinglePlayer", "")
        v = eg.plan_variants(*args)
        self.assertEqual(sorted(v), ["New Suit Slot", "Replace Default Suit"])
        self.assertEqual(verdict(files), "game_folder")


class SmallFixes(unittest.TestCase):
    def test_lone_shader(self):
        self.assertEqual(verdict(["Limbo_Anaglyph_to_SBS_TAB.fx"], {"engine": "unknown"}, set(), {}, {}),
                         "reshade_preset")

    def test_game_text_file(self):
        g = {"nexusDomain": "halflife", "engine": "unknown", "processName": "hl.exe"}
        fidx = {"sentences.txt": ["valve/sound/sentences.txt", "cstrike/sound/sentences.txt"]}
        self.assertEqual(plan(["sentences.txt"], g, {"valve"}, {"valve": ["valve"]}, fidx),
                         [("sentences.txt", "valve/sound/sentences.txt")])

    def test_notes_folder_beside_payload(self):
        g = {"nexusDomain": "danganronpa2goodbyedespair", "engine": "unknown", "processName": "DR2_us.exe"}
        fidx = {"dr2_data_us.wad": ["dr2_data_us.wad"], "dr2_data_keyboard_us.wad": ["dr2_data_keyboard_us.wad"]}
        files = ["dr2_data_keyboard_us.wad", "dr2_data_us.wad", "Hangman/Chapter 1.txt", "Hangman/Chapter 2.txt"]
        self.assertEqual(sorted(d for _s, d in plan(files, g, {"dr2_data_us.wad"}, {}, fidx)),
                         ["dr2_data_keyboard_us.wad", "dr2_data_us.wad"])

    def test_docs_only(self):
        self.assertEqual(verdict(["Remaster 3.0.txt"], {"engine": "unknown"}, set(), {}, {}), "docs_only")


if __name__ == "__main__":
    unittest.main()


class InstallAsks(unittest.TestCase):
    def test_install_offers_alternatives(self):
        import shutil
        import tempfile
        from test_backend import main
        root = main._game_dir("Bully Game")
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root)
        open(os.path.join(root, "Bully.exe"), "wb").close()
        game = {"appId": 91, "nexusDomain": "bullytest", "installDirName": "Bully Game",
                "processName": "Bully.exe", "engine": "unknown", "modsSubdir": "Mods"}
        main._save_settings({"experimental_games": {"91": game}})

        def scratch():
            d = tempfile.mkdtemp()
            for v in ("Slow", "Slower"):
                p = os.path.join(d, "Clock", v, "_derpy_script_loader", "scripts", f"{v}.lua")
                os.makedirs(os.path.dirname(p))
                open(p, "w").close()
            return d
        with self.assertRaises(main.NeedsChoice) as cm:
            main._experimental_root_install(scratch(), root, "Mods", game, "bullytest", 91, {"name": "Clock"})
        self.assertEqual(cm.exception.options, ["Slow", "Slower"])
        key = main._experimental_root_install(scratch(), root, "Mods", game, "bullytest", 91,
                                              {"name": "Clock"}, "Slower")
        self.assertTrue(key)
        self.assertTrue(os.path.isfile(os.path.join(root, "_derpy_script_loader", "scripts", "Slower.lua")))
        self.assertFalse(os.path.exists(os.path.join(root, "_derpy_script_loader", "scripts", "Slow.lua")))
        shutil.rmtree(root, ignore_errors=True)
