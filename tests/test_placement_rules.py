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


if __name__ == "__main__":
    unittest.main()
