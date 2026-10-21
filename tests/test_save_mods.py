"""Save-file mods go where the game keeps its saves, yours backed up first."""
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


class SaveTests(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(eg.save_files(["S/README.txt", "S/_1084.bbsave", "S/profile.dat"]),
                         ["S/_1084.bbsave", "S/profile.dat"])
        self.assertEqual(eg.save_files(["Mod Files/a.xtbl", "x.bbsave"]), [])
        hit = eg.score_save_dir("C:/u/AppData/Local/THQ/Saints Row 2", {"_9.bbsave", "profile.dat"},
                                ["_1084.bbsave", "profile.dat"], "Saints Row 2")
        other = eg.score_save_dir("C:/u/AppData/Local/Other", {"profile.dat"}, ["_1084.bbsave", "profile.dat"],
                                  "Saints Row 2")
        self.assertGreater(hit, other)
        self.assertEqual(eg.score_save_dir("C:/x", {"a.txt"}, ["_1.bbsave"], "SR2"), 0)

    def test_install_and_uninstall(self):
        home = tempfile.mkdtemp()
        backups = tempfile.mkdtemp()
        scratch = tempfile.mkdtemp()
        try:
            saves = os.path.join(home, "AppData", "Local", "THQ", "Saints Row 2")
            os.makedirs(saves)
            with open(os.path.join(saves, "profile.dat"), "wb") as f:
                f.write(b"MINE")
            with open(os.path.join(saves, "_0001.bbsave"), "wb") as f:
                f.write(b"MY SAVE")
            os.makedirs(os.path.join(scratch, "Save"))
            for n, d in (("profile.dat", b"MOD"), ("_1084.bbsave", b"MODSAVE"), ("README.txt", b"hi")):
                with open(os.path.join(scratch, "Save", n), "wb") as f:
                    f.write(d)
            game = {"appId": 9480, "nexusDomain": "saintsrow2", "installDirName": "Saints Row 2",
                    "displayName": "Saints Row 2", "processName": "SR2_pc.exe"}
            main._save_settings({"experimental_games": {"9480": game}})
            with unittest.mock.patch.object(main, "_save_roots", lambda g: [home]), \
                    unittest.mock.patch.object(main, "SAVE_BACKUPS", backups):
                key = main._install_save_mod(scratch, ["Save/profile.dat", "Save/_1084.bbsave"], game,
                                             "saintsrow2", {"name": "100% Save"})
            self.assertTrue(key)
            with open(os.path.join(saves, "profile.dat"), "rb") as f:
                self.assertEqual(f.read(), b"MOD")
            zips = os.listdir(os.path.join(backups, "saintsrow2"))
            with zipfile.ZipFile(os.path.join(backups, "saintsrow2", zips[0])) as z:
                self.assertEqual(sorted(z.namelist()), ["_0001.bbsave", "profile.dat"])
            settings = main._load_settings()
            rec = settings["installed"]["saintsrow2"][key]
            self.assertIn("backed up", rec["warning"])
            main._remove_files_record("saintsrow2", key, saves, settings)
            with open(os.path.join(saves, "profile.dat"), "rb") as f:
                self.assertEqual(f.read(), b"MINE")
            self.assertFalse(os.path.exists(os.path.join(saves, "_1084.bbsave")))
            self.assertTrue(os.path.exists(os.path.join(saves, "_0001.bbsave")))
        finally:
            for d in (home, backups, scratch):
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
