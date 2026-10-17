"""Experimental any-game: requirement detection and tracked loader installs."""
import asyncio
import os
import unittest
import unittest.mock

from test_backend import main  # stubs decky/aiohttp and imports main.py


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class ExperimentalFrameworkTests(unittest.TestCase):
    def setUp(self):
        self.plugin = main.Plugin()
        main._save_settings({})

    def _game(self):
        return {"appId": 2767030, "nexusDomain": "marvelrivals",
                "installDirName": "MarvelRivals",
                "processName": "MarvelGame/Marvel/Binaries/Win64/Marvel-Win64-Shipping.exe"}

    def test_detects_shared_loader(self):
        async def get_mods(*a, **k):
            return {"ok": True, "mods": [{"modId": i} for i in range(1, 21)]}

        async def resolve(*a):
            return 1

        async def legacy(game_id, ids, fields, key=None):
            req = {"nexusRequirements": {"nodes": [{"modId": 2940, "modName": "UTOC Signature Bypass",
                                                    "url": "https://www.nexusmods.com/marvelrivals/mods/2940"}]}}
            return [{"modId": i, "modRequirements": req if i <= 12 else {}} for i in ids]

        async def files(domain, mid):
            return {"ok": True, "files": [{"file_id": 7, "category_name": "MAIN"}]}

        async def listing(domain, mid, fid):
            return [{"type": "file", "path": "dsound.dll"},
                    {"type": "directory", "children": [{"type": "file", "path": "plugins/bypass.asi"}]}]

        g = self._game()
        with unittest.mock.patch.object(self.plugin, "get_mods", get_mods), \
                unittest.mock.patch.object(main, "_resolve_game_id", resolve), \
                unittest.mock.patch.object(main, "_legacy_mods_in_batches", legacy), \
                unittest.mock.patch.object(self.plugin, "get_mod_files", files), \
                unittest.mock.patch.object(main, "_mod_file_listing", listing):
            _run(self.plugin._experimental_framework(g))
        self.assertTrue(g["frameworkChecked"])
        fw = g["framework"]
        self.assertEqual(fw["nexusModId"], 2940)
        self.assertEqual(fw["installKind"], "copyRootTracked")
        self.assertEqual(fw["detectFile"], "MarvelGame/Marvel/Binaries/Win64/dsound.dll")
        self.assertIn("ban", fw["warning"])

    def test_tracked_copy_and_remove_restores_game_file(self):
        game_root = main._game_dir("MarvelRivals")
        win64 = os.path.join(game_root, "MarvelGame", "Marvel", "Binaries", "Win64")
        os.makedirs(win64, exist_ok=True)
        with open(os.path.join(win64, "dsound.dll"), "w") as f:
            f.write("original")
        scratch = os.path.join(main.DOWNLOADS_DIR, "fw-test")
        os.makedirs(os.path.join(scratch, "plugins"), exist_ok=True)
        with open(os.path.join(scratch, "dsound.dll"), "w") as f:
            f.write("loader")
        with open(os.path.join(scratch, "plugins", "b.asi"), "w") as f:
            f.write("x")
        moved, backed = main._copy_root_payload(scratch, win64, "dsound.dll", "", backup=True)
        self.assertEqual(sorted(moved), ["dsound.dll", "plugins/b.asi"])
        self.assertEqual(backed, ["dsound.dll"])
        sub = "MarvelGame/Marvel/Binaries/Win64"
        g = dict(self._game(), framework={"nexusModId": 2940, "installKind": "copyRootTracked",
                                          "installSubdir": "MarvelGame/Marvel/Binaries/Win64"})
        main._save_settings({
            "experimental_games": {"2767030": g},
            "experimental_frameworks": {"marvelrivals/2940": {
                "install_dir": "MarvelRivals",
                "files": [f"{sub}/{r}" for r in moved],
                "backups": [f"{sub}/{r}" for r in backed]}},
        })
        r = _run(self.plugin.remove_experimental_framework(2767030))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["removed"], 2)
        with open(os.path.join(win64, "dsound.dll")) as f:
            self.assertEqual(f.read(), "original")
        self.assertFalse(os.path.exists(os.path.join(win64, "plugins")))
        self.assertTrue(os.path.isdir(win64))

    def test_toggle_renames_loader_and_status_follows(self):
        root = main._game_dir("MarvelRivals")
        sub = "MarvelGame/Marvel/Binaries/Win64"
        win64 = os.path.join(root, *sub.split("/"))
        os.makedirs(os.path.join(win64, "plugins"), exist_ok=True)
        for rel in ("dsound.dll", "plugins/b.asi", "License.txt"):
            with open(os.path.join(win64, *rel.split("/")), "w") as f:
                f.write("x")
        g = dict(self._game(), framework={"nexusModId": 2940, "installKind": "copyRootTracked",
                                          "installSubdir": "MarvelGame/Marvel/Binaries/Win64"})
        main._save_settings({
            "experimental_games": {"2767030": g},
            "experimental_frameworks": {"marvelrivals/2940": {
                "install_dir": "MarvelRivals",
                "files": [f"{sub}/dsound.dll", f"{sub}/plugins/b.asi", f"{sub}/License.txt"],
                "backups": []}},
        })
        detect = f"{sub}/dsound.dll"
        r = _run(self.plugin.set_experimental_framework_enabled(2767030, False))
        self.assertEqual(r["changed"], 2)
        self.assertTrue(os.path.isfile(os.path.join(win64, "dsound.dll.nexusoff")))
        self.assertTrue(os.path.isfile(os.path.join(win64, "License.txt")))
        st = _run(self.plugin.get_game_status("MarvelRivals", "MarvelGame/Marvel/Content/Paks/~mods", detect))
        self.assertTrue(st["framework_installed"])
        self.assertFalse(st["framework_enabled"])
        _run(self.plugin.set_experimental_framework_enabled(2767030, True))
        st = _run(self.plugin.get_game_status("MarvelRivals", "MarvelGame/Marvel/Content/Paks/~mods", detect))
        self.assertTrue(st["framework_enabled"])
        self.assertTrue(os.path.isfile(os.path.join(win64, "plugins", "b.asi")))
        _run(self.plugin.set_experimental_framework_enabled(2767030, False))
        r = _run(self.plugin.remove_experimental_framework(2767030))
        self.assertEqual(r["removed"], 3)
        self.assertEqual(os.listdir(win64), [])


if __name__ == "__main__":
    unittest.main()
