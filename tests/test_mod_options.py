"""Changing an installed mod's version from its kept archive."""
import asyncio
import os
import shutil
import tempfile
import unittest
import unittest.mock

from test_backend import main


class ModOptionTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.p = unittest.mock.patch.object(main, "OPTIONS_DIR", self.dir)
        self.p.start()
        self.archive = os.path.join(self.dir, "g", "5-6.zip")
        os.makedirs(os.path.dirname(self.archive))
        with open(self.archive, "wb") as f:
            f.write(b"PK..")
        self.call = {"game_domain": "g", "mod_id": 5, "file_id": 6, "file_name": "m.zip",
                     "mod_name": "M", "mod_version": "1", "install_dir": "G", "mods_subdir": "mods",
                     "install_mode": "folder", "app_id": 1}
        main._save_settings({"experimental_games": {"1": {"nexusDomain": "g", "installDirName": "G"}},
                             "installed": {"g": {"M": {"name": "M", "modOptions": {
                                 "options": ["A", "B"], "labels": ["A", "B"], "choice": "A",
                                 "archive": self.archive, "call": self.call}}}}})
        self.plugin = main.Plugin()

    def tearDown(self):
        self.p.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_(self, c):
        return asyncio.new_event_loop().run_until_complete(c)

    def test_get(self):
        r = self.run_(self.plugin.get_mod_options("g", "M"))
        self.assertEqual((r["options"], r["choice"]), (["A", "B"], "A"))
        self.assertFalse(self.run_(self.plugin.get_mod_options("g", "Other"))["ok"])

    def test_switch_and_fallback(self):
        calls = []

        async def uninstall(self_, *a, **k):
            calls.append(("un",) + a[:4])
            return {"ok": True}

        async def install(self_, **k):
            calls.append(("in", k["payload_choice"]))
            return {"ok": k["payload_choice"] != "BAD", "folder": "M", "error": "nope"}
        with unittest.mock.patch.object(main.Plugin, "uninstall_mod", uninstall), \
                unittest.mock.patch.object(main.Plugin, "install_mod", install):
            r = self.run_(self.plugin.set_mod_option("g", "M", "B"))
            self.assertTrue(r["ok"])
            self.assertEqual(calls, [("un", "g", "G", "mods", "M"), ("in", "B")])
            calls.clear()
            r = self.run_(self.plugin.set_mod_option("g", "M", "BAD"))
            self.assertFalse(r["ok"])
            self.assertEqual(calls[-1], ("in", "A"))  # the previous version back

    def test_prune(self):
        stray = os.path.join(self.dir, "g", "9-9.zip")
        open(stray, "wb").close()
        main._prune_kept_archives()
        self.assertFalse(os.path.exists(stray))
        self.assertTrue(os.path.exists(self.archive))


if __name__ == "__main__":
    unittest.main()
