"""Across-game tools: install check, vanilla memory, setups, overlaps,
storage, setup backups, problem reports, fork updates, reapply."""
import asyncio
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from test_backend import main


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.root = main._game_dir("Tool Game")
        shutil.rmtree(self.root, ignore_errors=True)
        os.makedirs(os.path.join(self.root, "Data"))
        self.write("Data/hud.dat", b"GAME")
        self.game = {"appId": 78, "nexusDomain": "toolgame", "installDirName": "Tool Game",
                     "processName": "Game.exe", "engine": "generic", "modsSubdir": "mods"}
        main._save_settings({"experimental_games": {"78": self.game}, "api_key": "SECRETKEY1234567890"})
        self.plugin = main.Plugin()
        self.args = ("Tool Game", "mods", "folder", "toolgame", 78, "", "starred")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, rel, data, base=None):
        p = os.path.join(base or self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)

    def install(self, name, files, mod_id=1):
        scratch = tempfile.mkdtemp()
        for rel, data in files.items():
            self.write(rel, data, scratch)
        return main._experimental_root_install(scratch, self.root, "mods", self.game, "toolgame", 78,
                                               {"name": name, "mod_id": mod_id, "file_id": mod_id * 10})

    def on(self):
        r = run(self.plugin.get_installed_mods("toolgame", "Tool Game", "mods", "folder", 78))
        return {m["folder"] for m in r["mods"] if m["enabled"]}

    def test_verify_record(self):
        k = self.install("Blue", {"Data/blue.dat": b"b", "Data/x.dat": b"x"})
        self.assertEqual(main._verify_record("toolgame", k), "")
        os.remove(os.path.join(self.root, "Data", "x.dat"))
        self.assertIn("1 of 2", main._verify_record("toolgame", k))
        settings = main._load_settings()
        settings["installed"]["toolgame"]["Prog"] = {"mode": "files", "target": ".", "files": [],
                                                     "program": {"exe": "x.exe"}}
        main._save_settings(settings)
        self.assertEqual(main._verify_record("toolgame", "Prog"), "")

    def test_vanilla_remembers(self):
        a = self.install("A", {"Data/a.dat": b"a"}, 1)
        b = self.install("B", {"Data/b.dat": b"b"}, 2)
        run(self.plugin.set_mod_enabled("Tool Game", "mods", b, False, "folder", "toolgame", 78))
        self.assertEqual(self.on(), {a})
        r = run(self.plugin.set_all_mods_enabled("Tool Game", "mods", False, "folder", "toolgame", 78))
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.on(), set())
        self.assertFalse(os.path.exists(os.path.join(self.root, "Data", "a.dat")))
        run(self.plugin.set_all_mods_enabled("Tool Game", "mods", True, "folder", "toolgame", 78))
        self.assertEqual(self.on(), {a})  # B stays off: it was off before

    def test_setups(self):
        a = self.install("A", {"Data/a.dat": b"a"}, 1)
        b = self.install("B", {"Data/b.dat": b"b"}, 2)
        self.assertTrue(run(self.plugin.save_mod_setup(*self.args, "both"))["ok"])
        run(self.plugin.set_mod_enabled("Tool Game", "mods", a, False, "folder", "toolgame", 78))
        run(self.plugin.save_mod_setup(*self.args, "only b"))
        r = run(self.plugin.apply_mod_setup(*self.args, "both"))
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.on(), {a, b})
        run(self.plugin.apply_mod_setup(*self.args, "only b"))
        self.assertEqual(self.on(), {b})
        names = [s["name"] for s in run(self.plugin.get_mod_setups("toolgame"))["setups"]]
        self.assertEqual(names, ["both", "only b"])

    def test_overlaps(self):
        self.install("Blue HUD", {"Data/hud.dat": b"BLUE"}, 1)
        self.install("Red HUD", {"Data/hud.dat": b"RED", "Data/red.dat": b"r"}, 2)
        r = run(self.plugin.get_mod_overlaps("toolgame"))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["overlaps"][0]["active"], "Red HUD")
        self.assertEqual(r["overlaps"][0]["examples"], ["Data/hud.dat"])
        self.assertTrue(any(x["name"] == "Blue HUD" for x in r["replaces"]))

    def test_space_and_clear(self):
        os.makedirs(main.RESHADE_CACHE, exist_ok=True)
        with open(os.path.join(main.RESHADE_CACHE, "x.bin"), "wb") as f:
            f.write(b"0" * 5000)
        r = run(self.plugin.get_space_report("toolgame"))
        item = next(i for i in r["items"] if i["id"] == "reshade_cache")
        self.assertEqual(item["bytes"], 5000)
        self.assertFalse(run(self.plugin.clear_space_item("toolgame", "save_backups"))["ok"])
        self.assertEqual(run(self.plugin.clear_space_item("toolgame", "reshade_cache"))["freed"], 5000)
        self.assertFalse(os.path.exists(main.RESHADE_CACHE))

    def test_export_and_read_backup(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(main, "_report_dir", lambda: d):
            self.install("A", {"Data/a.dat": b"a"}, 1)
            run(self.plugin.save_mod_setup(*self.args, "s1"))
            r = run(self.plugin.export_mod_setup("toolgame"))
            self.assertEqual(r["count"], 1)
            backs = run(self.plugin.list_setup_backups("toolgame"))["backups"]
            self.assertEqual(len(backs), 1)
            settings = main._load_settings()
            settings["installed"] = {}
            settings["mod_setups"] = {}
            main._save_settings(settings)
            got = run(self.plugin.read_setup_backup("toolgame", backs[0]["file"]))
            self.assertEqual([(m["mod_id"], m["installed"]) for m in got["mods"]], [(1, False)])
            self.assertIn("s1", main._load_settings()["mod_setups"]["toolgame"])
            self.assertFalse(run(self.plugin.read_setup_backup("toolgame", "../x.json"))["ok"])
        shutil.rmtree(d)

    def test_problem_report_scrubbed(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(main, "_report_dir", lambda: d), \
                mock.patch.object(main, "_recent_logs", lambda: 'used SECRETKEY1234567890 and "apikey": "abcdefghijkl1234"'):
            r = run(self.plugin.save_problem_report("toolgame", 78, "it broke"))
            with open(r["path"], encoding="utf-8") as f:
                text = f.read()
        self.assertIn("it broke", text)
        self.assertNotIn("SECRETKEY1234567890", text)
        self.assertNotIn("abcdefghijkl1234", text)
        shutil.rmtree(d)

    def test_fork_update(self):
        good = {"version": "1.21.32-anygame.99", "hash": "a" * 64,
                "artifact": main.FORK_RAW + "Nexus-Mods.zip", "notes": "x"}
        main._ForkUpdateCache.data = None
        with mock.patch.object(main, "_fetch_bytes", mock.AsyncMock(return_value=json.dumps(good).encode())), \
                mock.patch.object(main, "APP_VERSION", "1.21.32-anygame.40"):
            r = run(self.plugin.get_plugin_update(True))
        self.assertTrue(r["update_available"], r)
        bad = dict(good, artifact="https://evil.example/x.zip")
        main._ForkUpdateCache.data = None
        with mock.patch.object(main, "_fetch_bytes", mock.AsyncMock(return_value=json.dumps(bad).encode())), \
                mock.patch.object(main, "APP_VERSION", "1.21.32-anygame.40"):
            r = run(self.plugin.get_plugin_update(True))
        self.assertFalse(r.get("update_available"))

    def test_reapply_reason(self):
        g = dict(self.game, toolApply="doommodloader")
        with mock.patch.object(main, "_steam_build_id", lambda app: "100"):
            main._record_tool_state(g, {"ok": True, "count": 2})
            self.assertEqual(main._generic_reapply_reason(g), "")
        with mock.patch.object(main, "_steam_build_id", lambda app: "101"):
            self.assertEqual(main._generic_reapply_reason(g), "the game updated")


if __name__ == "__main__":
    unittest.main()


class VerdictOnPageTests(unittest.TestCase):
    def test_doubt_and_works(self):
        root = main._game_dir("Verdict Game")
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(os.path.join(root, "Data"))
        game = {"appId": 79, "nexusDomain": "verdictgame", "installDirName": "Verdict Game",
                "processName": "Game.exe", "engine": "unknown", "modsSubdir": "mods"}
        main._save_settings({"experimental_games": {"79": game}})
        main._LAYOUT_CACHE.clear()
        plugin = main.Plugin()

        def listing(paths):
            return mock.AsyncMock(return_value=[{"type": "file", "path": p} for p in paths])
        with mock.patch.object(main, "_mod_file_listing", listing(["Suit.tpf"])):
            r = run(plugin.get_install_block("verdictgame", 1, 2, "Suit"))
        self.assertEqual(r["verdict"], "texmod")
        self.assertIn("TexMod", r["doubt"])
        with mock.patch.object(main, "_mod_file_listing", listing(["Data/hud.dat"])):
            r = run(plugin.get_install_block("verdictgame", 1, 3, "Hud"))
        self.assertEqual(r["verdict"], "game_folder")
        self.assertIn("Should work", r["works"])
        with mock.patch.object(main, "_mod_file_listing", listing(["Data/hud.dat"])):
            r = run(plugin.get_install_block("notagame", 1, 3, "Hud"))
        self.assertNotIn("verdict", r)
        shutil.rmtree(root, ignore_errors=True)
