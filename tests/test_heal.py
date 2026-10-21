"""Putting mod files back after Steam's "verify files" restores the game's own."""
import os
import shutil
import tempfile
import unittest
import unittest.mock

from test_backend import main


class HealTests(unittest.TestCase):
    def setUp(self):
        main._HEAL_SEEN.clear()
        self.root = main._game_dir("Heal Game")
        shutil.rmtree(self.root, ignore_errors=True)
        os.makedirs(os.path.join(self.root, "bin"))
        self.stash = tempfile.mkdtemp()
        self.p = unittest.mock.patch.object(main, "STASH_DIR", self.stash)
        self.p.start()
        self.write("bin/dinput8.dll", b"MOD-LOADER")
        self.write("bin/dinput8.dll.nexusbak", b"GAME")
        self.write("patch.pak", b"MODPAK!!")
        self.write("patch.pak.nexusbak", b"GAMEPAK!")
        main._save_settings({
            "experimental_games": {"1": {"nexusDomain": "healgame", "installDirName": "Heal Game"}},
            "installed": {"healgame": {"Mod": {"mode": "files", "target": ".", "files": ["patch.pak"],
                                                "backups": ["patch.pak"]}}},
            "experimental_frameworks": {"healgame/0": {"install_dir": "Heal Game",
                                                         "files": ["bin/dinput8.dll"],
                                                         "backups": ["bin/dinput8.dll"]}}})

    def tearDown(self):
        self.p.stop()
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.stash, ignore_errors=True)

    def write(self, rel, data):
        with open(os.path.join(self.root, *rel.split("/")), "wb") as f:
            f.write(data)

    def read(self, rel):
        with open(os.path.join(self.root, *rel.split("/")), "rb") as f:
            return f.read()

    def test_verify_is_undone(self):
        self.assertEqual(main._heal_replaced_files(), [])  # learns the mod files
        self.write("bin/dinput8.dll", b"GAME")     # Steam verify
        self.write("patch.pak", b"GAMEPAK!")
        self.assertEqual(sorted(main._heal_replaced_files()),
                         ["healgame: bin/dinput8.dll", "healgame: patch.pak"])
        self.assertEqual(self.read("bin/dinput8.dll"), b"MOD-LOADER")
        self.assertEqual(self.read("patch.pak"), b"MODPAK!!")
        self.assertEqual(main._heal_replaced_files(), [])

    def test_mod_update_is_learned(self):
        main._heal_replaced_files()
        self.write("patch.pak", b"MODPAK v2")
        self.assertEqual(main._heal_replaced_files(), [])
        self.write("patch.pak", b"GAMEPAK!")
        main._heal_replaced_files()
        self.assertEqual(self.read("patch.pak"), b"MODPAK v2")

    def test_switched_off_is_left_alone(self):
        main._heal_replaced_files()
        s = main._load_settings()
        s["installed"]["healgame"]["Mod"]["enabled"] = False
        main._save_settings(s)
        self.write("patch.pak", b"GAMEPAK!")
        os.replace(os.path.join(self.root, "bin", "dinput8.dll"),
                   os.path.join(self.root, "bin", "dinput8.dll.nexusoff"))
        self.write("bin/dinput8.dll", b"GAME")
        self.assertEqual(main._heal_replaced_files(), [])
        self.assertEqual(self.read("patch.pak"), b"GAMEPAK!")


if __name__ == "__main__":
    unittest.main()


class HealExtraTests(HealTests):
    def test_big_files_are_named_not_copied(self):
        with unittest.mock.patch.object(main, "STASH_MAX_BYTES", 4):
            lost = []
            main._heal_replaced_files(lost)
            self.assertEqual(lost, [])
            shutil.copyfile(os.path.join(self.root, "patch.pak.nexusbak"), os.path.join(self.root, "patch.pak"))
            main._HEAL_SEEN.clear()
            main._heal_replaced_files(lost)
            self.assertIn("healgame: patch.pak", lost)

    def test_uninstalled_copies_go(self):
        main._heal_replaced_files()
        self.assertTrue(os.path.isfile(os.path.join(self.stash, "healgame", "patch.pak")))
        s = main._load_settings()
        s["installed"]["healgame"].pop("Mod")
        main._save_settings(s)
        main._heal_replaced_files()
        self.assertFalse(os.path.isfile(os.path.join(self.stash, "healgame", "patch.pak")))
