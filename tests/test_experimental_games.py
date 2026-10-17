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


if __name__ == "__main__":
    unittest.main()
