"""Two mods changing the same game files: the newer one wins, the older is switched off."""
import asyncio
import os
import shutil
import tempfile
import unittest

from test_backend import main


class ClashTests(unittest.TestCase):
    def setUp(self):
        self.root = main._game_dir("Clash Game")
        shutil.rmtree(self.root, ignore_errors=True)
        os.makedirs(os.path.join(self.root, "bin"))
        os.makedirs(os.path.join(self.root, "Data"))
        self.write("bin/Game.exe", b"MZ")
        self.write("Data/hud.dat", b"GAME-HUD")
        self.game = {"appId": 77, "nexusDomain": "clashgame", "installDirName": "Clash Game",
                     "processName": "bin/Game.exe", "engine": "generic", "modsSubdir": "mods"}
        main._save_settings({"experimental_games": {"77": self.game}})

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, rel, data, base=None):
        p = os.path.join(base or self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)

    def read(self, rel):
        with open(os.path.join(self.root, *rel.split("/")), "rb") as f:
            return f.read()

    def install(self, name, files):
        scratch = tempfile.mkdtemp()
        for rel, data in files.items():
            self.write(rel, data, scratch)
        return main._experimental_root_install(scratch, self.root, "mods", self.game, "clashgame", 77,
                                               {"name": name})

    def test_newer_wins_older_switched_off_and_back(self):
        a = self.install("Blue HUD", {"Data/hud.dat": b"BLUE", "Data/blue.dat": b"b"})
        self.assertEqual(self.read("Data/hud.dat"), b"BLUE")
        b = self.install("Red HUD", {"Data/hud.dat": b"RED"})
        self.assertTrue(b)
        self.assertEqual(self.read("Data/hud.dat"), b"RED")
        recs = main._load_settings()["installed"]["clashgame"]
        self.assertIs(recs[a]["enabled"], False)
        self.assertIn("Red HUD", recs[a]["disabled_reason"])
        self.assertIn("Blue HUD", recs[b]["warning"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "Data", "blue.dat")))  # parked
        # Uninstalling Red brings the game's own file back.
        settings = main._load_settings()
        main._remove_files_record("clashgame", b, self.root, settings)
        main._save_settings(settings)
        self.assertEqual(self.read("Data/hud.dat"), b"GAME-HUD")

    def test_enabling_swaps_round(self):
        a = self.install("Blue HUD", {"Data/hud.dat": b"BLUE"})
        b = self.install("Red HUD", {"Data/hud.dat": b"RED"})
        plugin = main.Plugin()
        r = asyncio.new_event_loop().run_until_complete(
            plugin.set_mod_enabled("Clash Game", "mods", a, True, "folder", "clashgame"))
        self.assertTrue(r["ok"], r)
        self.assertIn("Red HUD", r.get("warning", ""))
        self.assertEqual(self.read("Data/hud.dat"), b"BLUE")
        recs = main._load_settings()["installed"]["clashgame"]
        self.assertIs(recs[b]["enabled"], False)
        self.assertIsNot(recs[a]["enabled"], False)

    def test_no_clash_no_change(self):
        a = self.install("Blue HUD", {"Data/hud.dat": b"BLUE"})
        b = self.install("Extra", {"Data/extra.dat": b"x"})
        recs = main._load_settings()["installed"]["clashgame"]
        self.assertIsNot(recs[a].get("enabled"), False)
        self.assertNotIn("warning", recs[b])


if __name__ == "__main__":
    unittest.main()
