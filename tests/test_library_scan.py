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


class MatchTests(unittest.TestCase):
    def test_capcom_names_and_remake_years(self):
        games = [{"name": "Resident Evil 2 (2019)", "domain_name": "residentevil22019", "mods": 2000},
                 {"name": "Resident Evil 2", "domain_name": "residentevil2classic", "mods": 10}]
        r = eg.match_games(games, "RESIDENT EVIL 2  BIOHAZARD RE2")
        self.assertEqual(r["exact"]["domain"], "residentevil2classic")
        r = eg.match_games(games[:1], "RESIDENT EVIL 2  BIOHAZARD RE2")
        self.assertEqual(r["exact"]["domain"], "residentevil22019")

    def test_downloading_games_are_not_ready(self):
        lib = tempfile.mkdtemp()
        try:
            with open(os.path.join(lib, "appmanifest_1778820.acf"), "w") as f:
                f.write('"AppState"\n{\n\t"name"\t\t"TEKKEN 8"\n\t"StateFlags"\t\t"1026"\n'
                        '\t"installdir"\t\t"TEKKEN 8"\n}\n')
            g = eg.installed_games([lib])[0]
            self.assertFalse(g["ready"])
        finally:
            shutil.rmtree(lib)

    def test_outside_dir(self):
        rule = {"modPath": "Electronic Arts\\The Sims 4\\Mods\\Vortex Mods"}
        self.assertEqual(eg.vortex_outside_dir(rule), "Electronic Arts/The Sims 4/Mods/Vortex Mods")
        docs = tempfile.mkdtemp()
        try:
            self.assertEqual(eg.pick_outside_base(eg.vortex_outside_dir(rule), [docs]), "")
            os.makedirs(os.path.join(docs, "Electronic Arts", "The Sims 4", "Mods"))
            self.assertEqual(eg.pick_outside_base(eg.vortex_outside_dir(rule), ["", docs]), docs)
        finally:
            shutil.rmtree(docs)
        g = {"mergeInto": "Electronic Arts/The Sims 4/Mods", "mergeBase": "C:/Docs"}
        self.assertEqual(eg.classify_mod(["CAS/hair.package"], g, set(), {}), "mods_folder")
