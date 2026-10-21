"""Mods that are their own installer program: kept, run on request, what they add recorded."""
import asyncio
import os
import shutil
import tempfile
import unittest
import unittest.mock

from test_backend import main


class ProgramTests(unittest.TestCase):
    def setUp(self):
        self.root = main._game_dir("Prog Game")
        shutil.rmtree(self.root, ignore_errors=True)
        os.makedirs(os.path.join(self.root, "data"))
        with open(os.path.join(self.root, "data", "old.bin"), "wb") as f:
            f.write(b"old")
        self.home = tempfile.mkdtemp()
        self.p = unittest.mock.patch.object(main, "PROGRAMS_DIR", self.home)
        self.p.start()
        self.game = {"appId": 3, "nexusDomain": "proggame", "installDirName": "Prog Game",
                     "processName": "Game.exe", "engine": "generic", "modsSubdir": "mods"}
        main._save_settings({"experimental_games": {"3": self.game}})

    def tearDown(self):
        self.p.stop()
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_pick(self):
        self.assertEqual(main._pick_program(["A/vc_redist.x64.exe", "A/Complete SSJ4.exe", "A/info.txt"],
                                            "Complete SSJ4"), "A/Complete SSJ4.exe")
        self.assertEqual(main._pick_program(["readme.txt"], "x"), "")

    def test_keep_run_uninstall(self):
        scratch = tempfile.mkdtemp()
        for n in ("Wish.exe", "Wish.installinfo", "readme.txt"):
            open(os.path.join(scratch, n), "w").close()
        key = main._experimental_root_install(scratch, self.root, "mods", self.game, "proggame", 3,
                                              {"name": "A New Wish"})
        self.assertTrue(key)
        plugin = main.Plugin()
        loop = asyncio.new_event_loop()
        info = loop.run_until_complete(plugin.get_mod_program("proggame", key))
        self.assertEqual(info["exe"], "Wish.exe")

        def fake_run(exe, timeout):
            with open(os.path.join(self.root, "data", "wish.x2d"), "w") as f:
                f.write("new")
            with open(os.path.join(self.root, "data", "old.bin"), "wb") as f:
                f.write(b"changed!")
            return 0
        emitted = []

        async def emit(*a):
            emitted.append(a)
        with unittest.mock.patch.object(main, "_run_program_blocking", fake_run), \
                unittest.mock.patch.object(main.decky, "emit", emit):
            async def go():
                r = await plugin.run_mod_program("proggame", key)
                self.assertTrue(r["ok"], r)
                for _ in range(50):
                    if emitted:
                        break
                    await asyncio.sleep(0.05)
            loop.run_until_complete(go())
        self.assertEqual(emitted[0][0], "mod_program_done")
        rec = main._load_settings()["installed"]["proggame"][key]
        self.assertEqual(rec["files"], ["data/wish.x2d"])
        self.assertIn("changed 1", rec["warning"])
        settings = main._load_settings()
        main._remove_files_record("proggame", key, self.root, settings)
        main._save_settings(settings)
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "wish.x2d")))
        main._prune_programs()
        self.assertEqual(os.listdir(os.path.join(self.home, "proggame")), [])


if __name__ == "__main__":
    unittest.main()
