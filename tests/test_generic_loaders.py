"""Engine-wide loaders installed from GitHub releases."""
import asyncio
import io
import json
import os
import shutil
import sys
import unittest
import unittest.mock
import zipfile

from test_backend import main  # stubs decky/aiohttp and imports main.py
from test_reloaded_ii import _pe

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import generic_loaders as gl  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


BEPINEX_RELEASES = [
    {"tag_name": "v6.0.0-pre.2", "prerelease": True, "assets": [
        {"name": "BepInEx-Unity.IL2CPP-win-x64-6.0.0-pre.2.zip", "browser_download_url": "https://x/il2cpp.zip"}]},
    {"tag_name": "v5.4.23.2", "prerelease": False, "assets": [
        {"name": "BepInEx_win_x86_5.4.23.2.zip", "browser_download_url": "https://x/x86.zip"},
        {"name": "BepInEx_win_x64_5.4.23.2.zip", "browser_download_url": "https://x/x64.zip"}]},
]


class SuggestTests(unittest.TestCase):
    def test_bepinex_from_listings(self):
        listings = [["BepInEx/plugins/A.dll"], ["BepInEx/plugins/B/B.dll", "readme.txt"],
                    ["BepInEx/config/c.cfg", "BepInEx/plugins/C.dll"], ["Saves/x.dat"], None]
        self.assertEqual(gl.suggest_loader("unity", False, listings, []), "bepinex5")
        self.assertEqual(gl.suggest_loader("unity", True, listings, []), "bepinex6il2cpp")
        # Already installed: nothing to suggest.
        self.assertEqual(gl.suggest_loader("unity-bepinex", False, listings, []), "")

    def test_melonloader_from_requirement_names(self):
        self.assertEqual(gl.suggest_loader("unity", False, [["x.dll"]],
                                           ["MelonLoader", "MelonLoader"]), "melonloader")

    def test_ue4ss_and_asi(self):
        ue = [["MyMod/Scripts/main.lua", "MyMod/enabled.txt"]] * 3
        self.assertEqual(gl.suggest_loader("unreal", False, ue, []), "ue4ss")
        asi = [["scripts/fix.asi"], ["widescreen.asi", "widescreen.ini"], ["x.txt"]]
        self.assertEqual(gl.suggest_loader("generic", False, asi, []), "asiloader")
        self.assertEqual(gl.suggest_loader("generic", False, [["a.pak"]] * 5, []), "")

    def test_pick_asset(self):
        self.assertEqual(gl.pick_asset(BEPINEX_RELEASES, gl.LOADERS["bepinex5"], True)[1],
                         "BepInEx_win_x64_5.4.23.2.zip")
        self.assertEqual(gl.pick_asset(BEPINEX_RELEASES, gl.LOADERS["bepinex5"], False)[1],
                         "BepInEx_win_x86_5.4.23.2.zip")
        self.assertEqual(gl.pick_asset(BEPINEX_RELEASES, gl.LOADERS["bepinex6il2cpp"], True)[0],
                         "v6.0.0-pre.2")
        self.assertIsNone(gl.pick_asset(BEPINEX_RELEASES, gl.LOADERS["ue4ss"], True))

    def test_asi_proxy(self):
        self.assertEqual(gl.pick_asi_proxy(["kernel32.dll", "d3d9.dll", "winmm.dll"], set()), "winmm.dll")
        self.assertEqual(gl.pick_asi_proxy(["kernel32.dll"], set()), "")


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.root = main._game_dir("Unity Game")
        shutil.rmtree(self.root, ignore_errors=True)
        os.makedirs(self.root)
        with open(os.path.join(self.root, "Game.exe"), "wb") as f:
            f.write(_pe(["KERNEL32.dll", "winmm.dll"]))
        with open(os.path.join(self.root, "winhttp.dll"), "wb") as f:
            f.write(b"games-own")
        self.game = {"appId": 42, "nexusDomain": "unitygame", "installDirName": "Unity Game",
                     "processName": "Game.exe", "engine": "unity", "modsSubdir": "BepInEx/plugins",
                     "framework": gl.framework_entry("bepinex5", "")}
        main._save_settings({"experimental_games": {"42": self.game}})
        self.plugin = main.Plugin()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _zip(self, files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n, data in files.items():
                z.writestr(n, data)
        return buf.getvalue()

    def test_install_and_remove_bepinex(self):
        blob = self._zip({"winhttp.dll": "doorstop", "doorstop_config.ini": "x",
                          "BepInEx/core/BepInEx.dll": "core"})

        async def fetch(url, timeout=300):
            if "api.github.com" in url:
                return json.dumps(BEPINEX_RELEASES).encode()
            return blob
        with unittest.mock.patch.object(main, "_fetch_bytes", fetch):
            r = _run(main._github_loader_setup("unitygame"))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["version"], "v5.4.23.2")
        with open(os.path.join(self.root, "winhttp.dll")) as f:
            self.assertEqual(f.read(), "doorstop")
        self.assertTrue(os.path.isfile(os.path.join(self.root, "BepInEx", "core", "BepInEx.dll")))
        # The panel now routes plugins to BepInEx/plugins.
        os.makedirs(os.path.join(self.root, "BepInEx", "plugins"), exist_ok=True)
        removed = _run(self.plugin.remove_experimental_framework(42))
        self.assertTrue(removed["ok"], removed)
        with open(os.path.join(self.root, "winhttp.dll")) as f:
            self.assertEqual(f.read(), "games-own")
        self.assertFalse(os.path.exists(os.path.join(self.root, "BepInEx", "core", "BepInEx.dll")))

    def test_asi_loader_takes_the_proxy_name(self):
        self.game["framework"] = gl.framework_entry("asiloader", "", "winmm.dll")
        main._save_settings({"experimental_games": {"42": self.game}})
        blob = self._zip({"dinput8.dll": "ual"})
        rel = [{"tag_name": "v9.0.0", "assets": [
            {"name": "Ultimate-ASI-Loader_x64.zip", "browser_download_url": "https://x/u.zip"}]}]

        async def fetch(url, timeout=300):
            return json.dumps(rel).encode() if "api.github.com" in url else blob
        with unittest.mock.patch.object(main, "_fetch_bytes", fetch):
            r = _run(main._github_loader_setup("unitygame"))
        self.assertTrue(r["ok"], r)
        with open(os.path.join(self.root, "winmm.dll")) as f:
            self.assertEqual(f.read(), "ual")
        self.assertFalse(os.path.exists(os.path.join(self.root, "dinput8.dll")))

    def test_framework_detection_suggests_bepinex(self):
        g = {"appId": 42, "nexusDomain": "unitygame", "installDirName": "Unity Game",
             "processName": "Game.exe", "engine": "unity"}

        async def get_mods(*a, **k):
            return {"ok": True, "mods": [{"modId": i} for i in range(1, 13)]}

        async def resolve(*a):
            return 1

        async def legacy(game_id, ids, fields, key=None):
            return [{"modId": i, "modRequirements": {}} for i in ids]

        async def files(domain, mid):
            return {"ok": True, "files": [{"file_id": mid, "category_name": "MAIN"}]}

        async def listing(domain, mid, fid):
            return [{"type": "file", "path": f"BepInEx/plugins/M{mid}.dll"}]
        with unittest.mock.patch.object(self.plugin, "get_mods", get_mods), \
                unittest.mock.patch.object(main, "_resolve_game_id", resolve), \
                unittest.mock.patch.object(main, "_legacy_mods_in_batches", legacy), \
                unittest.mock.patch.object(self.plugin, "get_mod_files", files), \
                unittest.mock.patch.object(main, "_mod_file_listing", listing):
            _run(self.plugin._experimental_framework(g))
        self.assertEqual(g["framework"]["installKind"], "githubLoader")
        self.assertEqual(g["framework"]["loaderId"], "bepinex5")


if __name__ == "__main__":
    unittest.main()
