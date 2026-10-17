import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import experimental_games as eg  # noqa: E402

GAMES = [
    {"name": "Marvel Rivals", "domain_name": "marvelrivals", "mods": 9000},
    {"name": "Marvel's Midnight Suns", "domain_name": "marvelsmidnightsuns", "mods": 1200},
    {"name": "Danganronpa 2: Goodbye Despair", "domain_name": "danganronpa2goodbyedespair", "mods": 40},
    {"name": "Danganronpa: Trigger Happy Havoc", "domain_name": "danganronpatriggerhappyhavoc", "mods": 60},
    {"name": "Halloween", "domain_name": "halloween", "mods": 3},
    {"name": "The Witcher 3: Wild Hunt", "domain_name": "witcher3", "mods": 7000},
    {"name": "bad", "domain_name": "Bad Domain!", "mods": 1},
]


def touch(root, rel, size=0):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * size)


class MatchTests(unittest.TestCase):
    def test_exact_with_marks_and_punctuation(self):
        r = eg.match_games(GAMES, "Marvel’s Midnight Suns™".replace("’", "'"))
        self.assertEqual(r["exact"]["domain"], "marvelsmidnightsuns")

    def test_edition_words_ignored(self):
        r = eg.match_games(GAMES, "The Witcher 3: Wild Hunt - Game of the Year Edition")
        self.assertEqual(r["exact"]["domain"], "witcher3")

    def test_loose_name_is_only_a_candidate(self):
        r = eg.match_games(GAMES, "Danganronpa 2")
        self.assertIsNone(r["exact"])
        self.assertEqual(r["candidates"][0]["domain"], "danganronpa2goodbyedespair")

    def test_invalid_domains_dropped(self):
        r = eg.match_games(GAMES, "bad")
        self.assertIsNone(r["exact"])
        self.assertNotIn("Bad Domain!", [c["domain"] for c in r["candidates"]])

    def test_guess_domains(self):
        self.assertEqual(eg.guess_domains("Marvel's Midnight Suns")[:2],
                         ["marvelsmidnightsuns", "midnightsuns"])


class InspectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_unreal_picks_game_paks_not_engine(self):
        touch(self.root, "Engine/Content/Paks/engine.pak", 10)
        touch(self.root, "MarvelGame/Marvel/Content/Paks/pakchunk0-Windows.pak", 100)
        touch(self.root, "MarvelGame/Marvel/Binaries/Win64/Marvel-Win64-Shipping.exe", 5)
        touch(self.root, "MarvelRivals_Launcher.exe", 50)
        r = eg.inspect_install(self.root)
        self.assertEqual(r["engine"], "unreal")
        self.assertEqual(r["modsSubdir"], "MarvelGame/Marvel/Content/Paks/~mods")
        self.assertEqual(r["processName"], "MarvelGame/Marvel/Binaries/Win64/Marvel-Win64-Shipping.exe")
        self.assertNotIn("ue4ss", r)

    def test_unreal_shipping_exe(self):
        touch(self.root, "Proj/Content/Paks/a.pak", 100)
        touch(self.root, "Proj/Binaries/Win64/Proj-Win64-Shipping.exe", 5)
        touch(self.root, "Proj.exe", 50)
        r = eg.inspect_install(self.root)
        self.assertEqual(r["processName"], "Proj/Binaries/Win64/Proj-Win64-Shipping.exe")

    def test_unreal_with_ue4ss(self):
        touch(self.root, "Proj/Content/Paks/a.pak", 100)
        touch(self.root, "Proj/Binaries/Win64/ue4ss/UE4SS.dll", 1)
        touch(self.root, "Proj/Binaries/Win64/ue4ss/Mods/mods.txt", 1)
        r = eg.inspect_install(self.root)
        self.assertEqual(r["ue4ss"]["modsSubdir"], "Proj/Binaries/Win64/ue4ss/Mods")
        self.assertEqual(r["ue4ss"]["logicModsSubdir"], "Proj/Content/Paks/LogicMods")

    def test_unity_bepinex(self):
        touch(self.root, "Game_Data/globalgamemanagers", 1)
        touch(self.root, "BepInEx/core/BepInEx.dll", 1)
        touch(self.root, "Game.exe", 10)
        r = eg.inspect_install(self.root)
        self.assertEqual(r["modsSubdir"], "BepInEx/plugins")
        self.assertEqual(r["processName"], "Game.exe")

    def test_unity_melonloader_is_flat(self):
        touch(self.root, "Game_Data/globalgamemanagers", 1)
        touch(self.root, "MelonLoader/net6/MelonLoader.dll", 1)
        r = eg.inspect_install(self.root)
        self.assertEqual(r["modsSubdir"], "Mods")
        self.assertEqual(r["flatModExtensions"], [".dll"])

    def test_plain_unity(self):
        touch(self.root, "Game_Data/data.unity3d", 1)
        self.assertEqual(eg.inspect_install(self.root)["engine"], "unity")

    def test_existing_mods_folder_keeps_case(self):
        touch(self.root, "mods/readme.txt", 1)
        touch(self.root, "game.exe", 1)
        touch(self.root, "unins000.exe", 99)
        r = eg.inspect_install(self.root)
        self.assertEqual(r["modsSubdir"], "mods")
        self.assertEqual(r["processName"], "game.exe")

    def test_unknown(self):
        touch(self.root, "game.exe", 1)
        self.assertEqual(eg.inspect_install(self.root)["engine"], "unknown")

    def test_missing(self):
        self.assertEqual(eg.inspect_install(os.path.join(self.root, "nope"))["engine"], "missing")

    def test_appmanifest(self):
        touch(self.root, "x", 0)
        p = os.path.join(self.root, "appmanifest_1.acf")
        with open(p, "w") as f:
            f.write('"AppState"\n{\n\t"appid"\t\t"1"\n\t"name"\t\t"Marvel Rivals"\n'
                    '\t"installdir"\t\t"MarvelRivals"\n}\n')
        self.assertEqual(eg.read_appmanifest(p), {"name": "Marvel Rivals", "installdir": "MarvelRivals"})

    def test_build_game(self):
        g = eg.build_game(5, "Halloween", "Halloween", "halloween", "Halloween",
                          {"engine": "unity", "modsSubdir": "BepInEx/plugins",
                           "processName": "Halloween.exe", "note": "n"})
        self.assertEqual(g["installMode"], "folder")
        self.assertTrue(g["experimental"])
        self.assertEqual(g["modsSubdir"], "BepInEx/plugins")


class FrameworkTests(unittest.TestCase):
    def node(self, mid, *reqs):
        return {"modId": mid, "modRequirements": {"nexusRequirements": {"nodes": [
            {"modId": r, "modName": f"m{r}", "url": f"https://www.nexusmods.com/marvelrivals/mods/{r}"}
            for r in reqs]}}}

    def test_common_requirement(self):
        nodes = [self.node(i, 2940) for i in range(1, 8)] + [self.node(i) for i in range(8, 21)]
        self.assertEqual(eg.pick_common_requirement(nodes, "marvelrivals")["modId"], 2940)

    def test_rare_requirement_ignored(self):
        nodes = [self.node(1, 5), self.node(2, 5)] + [self.node(i) for i in range(3, 21)]
        self.assertIsNone(eg.pick_common_requirement(nodes, "marvelrivals"))

    def test_other_game_requirement_ignored(self):
        n = [{"modId": i, "modRequirements": {"nexusRequirements": {"nodes": [
            {"modId": 9, "modName": "x", "url": "https://www.nexusmods.com/site/mods/9"}]}}} for i in range(10)]
        self.assertIsNone(eg.pick_common_requirement(n, "marvelrivals"))

    def test_bypass_goes_beside_exe(self):
        r = eg.framework_layout(["dsound.dll", "plugins/bypass.asi"], "MarvelGame/Marvel/Binaries/Win64")
        self.assertEqual(r, {"installSubdir": "MarvelGame/Marvel/Binaries/Win64",
                             "detectFile": "MarvelGame/Marvel/Binaries/Win64/dsound.dll"})

    def test_wrapper_flattened(self):
        r = eg.framework_layout(["Bypass v2/dsound.dll", "Bypass v2/plugins/x.asi"], "G/Binaries/Win64")
        self.assertEqual(r["detectFile"], "G/Binaries/Win64/dsound.dll")

    def test_game_root_layout(self):
        r = eg.framework_layout(["MarvelGame/Marvel/Binaries/Win64/dsound.dll"], "MarvelGame/Marvel/Binaries/Win64")
        self.assertEqual(r, {"installSubdir": "", "detectFile": "MarvelGame/Marvel/Binaries/Win64/dsound.dll"})

    def test_plain_mod_is_not_a_framework(self):
        self.assertIsNone(eg.framework_layout(["Mod_P.pak", "Mod_P.utoc"], "G/Binaries/Win64"))

    def test_exe_dir(self):
        self.assertEqual(eg.exe_dir_of("A/B/c.exe"), "A/B")
        self.assertEqual(eg.exe_dir_of("c.exe"), "")


class RootPlanTests(unittest.TestCase):
    ROOT = {"SparkingZERO", "SparkingZERO.exe", "Engine"}
    INDEX = {"sparkingzero": ["SparkingZERO"], "content": ["Engine/Content", "SparkingZERO/Content"],
             "paks": ["Engine/Content/Paks", "SparkingZERO/Content/Paks"],
             "binaries": ["Engine/Binaries", "SparkingZERO/Binaries"],
             "win64": ["Engine/Binaries/Win64", "SparkingZERO/Binaries/Win64"]}
    MODS = "SparkingZERO/Content/Paks/~mods"
    EXE = "SparkingZERO/Binaries/Win64"

    def plan(self, files):
        return eg.plan_root_install(files, self.ROOT, self.INDEX, self.MODS, self.EXE)

    def test_plain_pak_mod_stays_in_mods_folder(self):
        self.assertIsNone(self.plan(["Goku_P.pak", "Goku_P.utoc", "Goku_P.ucas"]))
        self.assertIsNone(self.plan(["Goku/Goku_P.pak"]))

    def test_full_mods_path_left_to_folder_install(self):
        self.assertIsNone(self.plan(["SparkingZERO/Content/Paks/~mods/a.pak"]))

    def test_root_layout_merges(self):
        p = self.plan(["SparkingZERO/Binaries/Win64/dinput8.dll", "SparkingZERO/Content/Paks/~mods/a.pak"])
        self.assertEqual([d for _s, d in p], ["SparkingZERO/Binaries/Win64/dinput8.dll",
                                              "SparkingZERO/Content/Paks/~mods/a.pak"])

    def test_content_tree_mapped_to_game_project(self):
        p = self.plan(["Content/Paks/~mods/a.pak"])
        self.assertEqual(p, [("Content/Paks/~mods/a.pak", "SparkingZERO/Content/Paks/~mods/a.pak")])

    def test_wrapper_peeled_and_readme_dropped(self):
        p = self.plan(["Cool Mod v2/Binaries/Win64/x.dll", "Cool Mod v2/readme.txt"])
        self.assertEqual(p, [("Cool Mod v2/Binaries/Win64/x.dll", "SparkingZERO/Binaries/Win64/x.dll")])

    def test_proxy_dll_and_asi_beside_exe(self):
        p = self.plan(["dsound.dll", "plugins/fix.asi", "readme.md"])
        self.assertEqual([d for _s, d in p], ["SparkingZERO/Binaries/Win64/dsound.dll",
                                              "SparkingZERO/Binaries/Win64/plugins/fix.asi"])

    def test_unknown_files_decline(self):
        self.assertIsNone(self.plan(["dsound.dll", "weird/thing.bin"]))

    def test_bepinex_pack_goes_to_root(self):
        p = eg.plan_root_install(["BepInEx/core/BepInEx.dll", "winhttp.dll", "doorstop_config.ini"],
                                 {"Game.exe", "Game_Data"}, {"game_data": ["Game_Data"]}, "BepInEx/plugins", "")
        self.assertEqual(sorted(d for _s, d in p), ["BepInEx/core/BepInEx.dll", "doorstop_config.ini", "winhttp.dll"])

    def test_bepinex_plugin_mod_left_to_folder(self):
        self.assertIsNone(eg.plan_root_install(["BepInEx/plugins/Cool/Cool.dll"], {"Game.exe", "BepInEx"},
                                               {"bepinex": ["BepInEx"], "plugins": ["BepInEx/plugins"]},
                                               "BepInEx/plugins", ""))

    def test_ambiguous_dir_declines(self):
        self.assertIsNone(eg.plan_root_install(["Content/x.uasset"], {"A", "B"},
                                               {"content": ["A/Content", "B/Content"]}, "Mods", ""))

    def test_index_game_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "Proj/Content/Paks/a.pak", 1)
            touch(d, "Engine/Content/x", 1)
            idx = eg.index_game_dirs(d)
            self.assertEqual(idx["content"], ["Proj/Content"])  # Engine/ is never a mod target


class ToolGameTests(unittest.TestCase):
    def test_tool_archive_is_not_a_loader(self):
        self.assertIsNone(eg.framework_layout(
            ["SpiderManPCTool.exe", "DotNetZip.dll", "Newtonsoft.Json.dll"], ""))

    def test_tool_with_proxy_dll_is_still_a_loader(self):
        self.assertIsNotNone(eg.framework_layout(["Setup.exe", "dinput8.dll"], ""))

    def test_overstrike_profile(self):
        g = {"nexusDomain": "marvelsspidermanremastered", "modsSubdir": "Mods"}
        self.assertTrue(eg.apply_tool_profile(g, 4199))
        self.assertEqual(g["modsSubdir"], "Overstrike/Mods Library")
        self.assertEqual(g["framework"]["detectFile"], "Overstrike/Overstrike.exe")
        self.assertIn(".smpcmod", g["flatModExtensions"])
        self.assertFalse(eg.apply_tool_profile({"nexusDomain": "witcher3"}, 1))
        self.assertFalse(eg.apply_tool_profile({"nexusDomain": "spidermanmilesmorales"}, None))

    def test_profile_mods_order_and_paths(self):
        out = eg.overstrike_profile_mods([(5, ["sub/b.suit"]), (1, ["a.smpcmod", "a.smpcmod"])], [])
        self.assertEqual(out, [["a.smpcmod", True], ["sub\\b.suit", True]])


class Ue4ssTests(unittest.TestCase):
    def test_ue4ss_archive_is_a_loader_beside_exe(self):
        r = eg.framework_layout(["dwmapi.dll", "ue4ss/UE4SS.dll", "ue4ss/UE4SS-settings.ini",
                                 "ue4ss/Mods/mods.txt"], "Pal/Binaries/Win64")
        self.assertEqual(r, {"installSubdir": "Pal/Binaries/Win64",
                             "detectFile": "Pal/Binaries/Win64/dwmapi.dll"})

    def test_after_install_inspection_routes_scripts(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "Pal/Content/Paks/Pal-Windows.pak", 100)
            touch(d, "Pal/Binaries/Win64/Palworld-Win64-Shipping.exe", 1)
            self.assertNotIn("ue4ss", eg.inspect_install(d))
            touch(d, "Pal/Binaries/Win64/dwmapi.dll", 1)
            touch(d, "Pal/Binaries/Win64/ue4ss/UE4SS.dll", 1)
            touch(d, "Pal/Binaries/Win64/ue4ss/Mods/mods.txt", 1)
            self.assertEqual(eg.inspect_install(d)["ue4ss"]["modsSubdir"], "Pal/Binaries/Win64/ue4ss/Mods")


class ClassifyTests(unittest.TestCase):
    UE = {"engine": "unreal", "modsSubdir": "SparkingZERO/Content/Paks/~mods",
          "processName": "SparkingZERO/Binaries/Win64/SparkingZERO-Win64-Shipping.exe"}
    ROOT = {"SparkingZERO", "Engine"}
    INDEX = {"sparkingzero": ["SparkingZERO"], "binaries": ["SparkingZERO/Binaries"],
             "content": ["SparkingZERO/Content"], "win64": ["SparkingZERO/Binaries/Win64"]}

    def c(self, paths, game=None, **kw):
        return eg.classify_mod(paths, game or self.UE, self.ROOT, self.INDEX, **kw)

    def test_verdicts(self):
        self.assertEqual(self.c(["Goku_P.pak", "Goku_P.utoc", "Goku_P.ucas"]), "mods_folder")
        self.assertEqual(self.c(["Binaries/Win64/dinput8.dll"]), "game_folder")
        self.assertEqual(self.c(["fomod/ModuleConfig.xml", "a/x.pak"]), "wizard")
        self.assertEqual(self.c(["Tool.exe", "lib.dll", "readme.txt"]), "program")
        self.assertEqual(self.c(["textures/x.dds"]), "no_target")
        self.assertEqual(self.c(None), "unknown")
        self.assertEqual(self.c(["dsound.dll"], is_framework=True), "loader")

    def test_tool_game(self):
        g = {"toolApply": "overstrike", "flatModExtensions": [".smpcmod", ".suit"]}
        self.assertEqual(self.c(["x.smpcmod"], g), "tool_managed")
        self.assertEqual(self.c(["Suit Tool.exe"], g), "program")
        self.assertEqual(self.c(["x.png"], g), "no_target")

    def test_summary(self):
        s = eg.summarize([{"verdict": "mods_folder"}, {"verdict": "unknown"}, {"verdict": "program"}])
        self.assertEqual((s["working"], s["checked"], s["total"]), (1, 2, 3))


if __name__ == "__main__":
    unittest.main()
