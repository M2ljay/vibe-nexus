"""Whole Steam library scan and background compatibility check."""
import asyncio
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

from test_backend import main  # stubs decky/aiohttp and imports main.py

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import experimental_games as eg  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _manifest(lib, app_id, name, installdir):
    with open(os.path.join(lib, f"appmanifest_{app_id}.acf"), "w") as f:
        f.write(f'"AppState"\n{{\n\t"appid"\t\t"{app_id}"\n\t"name"\t\t"{name}"\n'
                f'\t"installdir"\t\t"{installdir}"\n}}\n')


class InstalledGamesTests(unittest.TestCase):
    def test_lists_games_and_skips_tools(self):
        lib = tempfile.mkdtemp()
        try:
            _manifest(lib, 367520, "Hollow Knight", "Hollow Knight")
            _manifest(lib, 1493710, "Proton Experimental", "Proton - Experimental")
            _manifest(lib, 228980, "Steamworks Common Redistributables", "Steamworks Shared")
            _manifest(lib, 12210, "Grand Theft Auto IV", "GTAIV")
            open(os.path.join(lib, "libraryfolders.vdf"), "w").close()
            games = eg.installed_games([lib, lib])
            self.assertEqual([g["name"] for g in games], ["Grand Theft Auto IV", "Hollow Knight"])
        finally:
            shutil.rmtree(lib)


class LibraryScanTests(unittest.TestCase):
    def setUp(self):
        self.plugin = main.Plugin()
        main._save_settings({"experimental_games": {"367520": {"nexusDomain": "hollowknight"}}})

    def test_scan_matches_and_marks_status(self):
        installed = [{"appId": 367520, "name": "Hollow Knight", "installDir": "Hollow Knight"},
                     {"appId": 72850, "name": "The Elder Scrolls V: Skyrim", "installDir": "Skyrim"},
                     {"appId": 1, "name": "Some Obscure Game", "installDir": "Obscure"}]
        nexus = [{"name": "Hollow Knight", "domain_name": "hollowknight", "mods": 137},
                 {"name": "Skyrim", "domain_name": "skyrim", "mods": 70000}]

        async def nexus_list():
            return nexus
        with unittest.mock.patch.object(eg, "installed_games", lambda libs: installed), \
                unittest.mock.patch.object(self.plugin, "_nexus_games_list", nexus_list):
            r = _run(self.plugin.scan_steam_library([72850]))
        self.assertTrue(r["ok"], r)
        by = {g["appId"]: g for g in r["games"]}
        self.assertEqual(by[367520]["domain"], "hollowknight")
        self.assertEqual(by[367520]["status"], "added")
        self.assertEqual(by[72850]["status"], "supported")
        self.assertEqual(by[1]["domain"], "")

    def test_background_check_stores_results_and_stops_on_repeated_failures(self):
        main._save_settings({"library_scan": {"games": [
            {"appId": a, "name": f"G{a}", "installDir": f"G{a}", "domain": f"g{a}"} for a in range(1, 6)]}})
        calls = []

        async def one(row, count):
            calls.append(row["appId"])
            if row["appId"] == 1:
                return {"working": 8, "checked": 10, "total": 10}
            raise RuntimeError("HTTP 429")

        async def no_sleep(*_a):
            return None
        with unittest.mock.patch.object(self.plugin, "_library_check_one", one), \
                unittest.mock.patch.object(main.asyncio, "sleep", no_sleep):
            _run(self.plugin._library_check([1, 2, 3, 4, 5], 20))
        self.assertEqual(calls, [1, 2, 3, 4])
        res = main._load_settings()["library_scan"]["results"]
        self.assertEqual(res["1"]["working"], 8)
        self.assertIn("429", res["4"]["error"])
        self.assertNotIn("5", res)


if __name__ == "__main__":
    unittest.main()
