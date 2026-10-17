"""Experimental any-game: requirement detection and tracked loader installs."""
import asyncio
import os
import shutil
import zipfile
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


class ExperimentalRootInstallTests(unittest.TestCase):
    def setUp(self):
        self.plugin = main.Plugin()
        self.root = main._game_dir("SparkingZERO")
        main._force_rmtree(self.root)
        for rel, text in (("SparkingZERO/Binaries/Win64/SparkingZERO-Win64-Shipping.exe", "exe"),
                          ("SparkingZERO/Binaries/Win64/dinput8.dll", "game's own"),
                          ("SparkingZERO/Content/Paks/pakchunk0.pak", "p")):
            path = os.path.join(self.root, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(text)
        self.game = {"appId": 1790600, "nexusDomain": "dragonballsparkingzero",
                     "installDirName": "SparkingZERO",
                     "modsSubdir": "SparkingZERO/Content/Paks/~mods",
                     "processName": "SparkingZERO/Binaries/Win64/SparkingZERO-Win64-Shipping.exe"}
        main._save_settings({"experimental_games": {"1790600": self.game}})

    def scratch(self, files):
        d = os.path.join(main.DOWNLOADS_DIR, "exp-scratch")
        main._force_rmtree(d)
        for rel in files:
            path = os.path.join(d, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("mod")
        return d

    def read(self, rel):
        with open(os.path.join(self.root, *rel.split("/"))) as f:
            return f.read()

    def test_install_toggle_uninstall_restores_game_file(self):
        self.assertEqual(main._experimental_game_for("dragonballsparkingzero"), self.game)
        d = self.scratch(["Cool v1/Binaries/Win64/dinput8.dll", "Cool v1/Content/Paks/~mods/c_P.pak",
                          "Cool v1/readme.txt"])
        key = main._experimental_root_install(d, self.root, self.game["modsSubdir"], self.game,
                                              "dragonballsparkingzero", 1790600, {"name": "Cool", "file_id": 1})
        self.assertEqual(key, "Cool")
        dll = "SparkingZERO/Binaries/Win64/dinput8.dll"
        self.assertEqual(self.read(dll), "mod")
        self.assertEqual(self.read(dll + ".nexusbak"), "game's own")
        self.assertEqual(self.read("SparkingZERO/Content/Paks/~mods/c_P.pak"), "mod")
        rec = main._load_settings()["installed"]["dragonballsparkingzero"]["Cool"]
        self.assertEqual(rec["backups"], [dll])
        listed = _run(self.plugin.get_installed_mods(
            "dragonballsparkingzero", "SparkingZERO", self.game["modsSubdir"], "folder", 1790600, "", "starred", []))
        row = [m for m in listed["mods"] if m["folder"] == "Cool"][0]
        self.assertTrue(row["togglable"])
        off = _run(self.plugin.set_mod_enabled("SparkingZERO", self.game["modsSubdir"], "Cool", False,
                                               "folder", "dragonballsparkingzero", 1790600))
        self.assertTrue(off["ok"], off)
        self.assertEqual(self.read(dll), "game's own")
        on = _run(self.plugin.set_mod_enabled("SparkingZERO", self.game["modsSubdir"], "Cool", True,
                                              "folder", "dragonballsparkingzero", 1790600))
        self.assertTrue(on["ok"], on)
        self.assertEqual(self.read(dll), "mod")
        r = _run(self.plugin.uninstall_mod("dragonballsparkingzero", "SparkingZERO", self.game["modsSubdir"],
                                           "Cool", "folder", 1790600, "", "starred"))
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.read(dll), "game's own")
        self.assertFalse(os.path.exists(os.path.join(self.root, *dll.split("/")) + ".nexusbak"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "SparkingZERO/Content/Paks/~mods/c_P.pak")))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "SparkingZERO/Content/Paks/pakchunk0.pak")))

    def test_coverage_check(self):
        async def get_mods(*a, **k):
            return {"ok": True, "mods": [{"modId": 1, "name": "Pak"}, {"modId": 2, "name": "Dll"},
                                         {"modId": 3, "name": "Tool"}, {"modId": 4, "name": "Bare"}]}

        async def files(domain, mid):
            return {"ok": True, "files": [{"file_id": mid, "category_name": "MAIN",
                                           "file_name": f"f{mid}.zip",
                                           "content_preview_link": "" if mid == 4 else f"L{mid}"}]}

        listings = {"L1": ["a_P.pak"], "L2": ["Binaries/Win64/dinput8.dll"], "L3": ["T.exe"]}

        async def preview(link):
            return listings.get(link)

        async def resolve(*a):
            return 7

        self.game["engine"] = "unreal"
        main._save_settings({"experimental_games": {"1790600": self.game}})
        with unittest.mock.patch.object(self.plugin, "get_mods", get_mods), \
                unittest.mock.patch.object(self.plugin, "get_mod_files", files), \
                unittest.mock.patch.object(main, "_preview_paths", preview), \
                unittest.mock.patch.object(main, "_resolve_game_id", resolve):
            r = _run(self.plugin.check_experimental_coverage(1790600, 4))
        self.assertTrue(r["ok"], r)
        verdicts = {row["name"]: row["verdict"] for row in r["rows"]}
        self.assertEqual(verdicts, {"Pak": "mods_folder", "Dll": "game_folder",
                                    "Tool": "program", "Bare": "unknown"})
        self.assertEqual((r["working"], r["checked"]), (2, 3))

    def test_ue_config_tweak_goes_to_user_config_and_back(self):
        cfg = os.path.join(main.DOWNLOADS_DIR, "LocalAppData", "SparkingZERO", "Saved", "Config", "Windows")
        os.makedirs(cfg, exist_ok=True)
        with open(os.path.join(cfg, "Engine.ini"), "w") as f:
            f.write("player's own")
        self.game["engine"] = "unreal"
        main._save_settings({"experimental_games": {"1790600": self.game}})
        d = self.scratch(["Engine.ini", "Instruction Manual.txt"])
        with unittest.mock.patch.object(main, "_ue_user_config_dir", lambda g: cfg):
            key = main._experimental_root_install(d, self.root, self.game["modsSubdir"], self.game,
                                                  "dragonballsparkingzero", 1790600, {"name": "Perf", "file_id": 3})
        self.assertEqual(key, "Perf")
        with open(os.path.join(cfg, "Engine.ini")) as f:
            self.assertEqual(f.read(), "mod")
        rec = main._load_settings()["installed"]["dragonballsparkingzero"]["Perf"]
        self.assertEqual(rec["base"], cfg)
        off = _run(self.plugin.set_mod_enabled("SparkingZERO", self.game["modsSubdir"], "Perf", False,
                                               "folder", "dragonballsparkingzero", 1790600))
        self.assertTrue(off["ok"], off)
        with open(os.path.join(cfg, "Engine.ini")) as f:
            self.assertEqual(f.read(), "player's own")
        _run(self.plugin.set_mod_enabled("SparkingZERO", self.game["modsSubdir"], "Perf", True,
                                         "folder", "dragonballsparkingzero", 1790600))
        r = _run(self.plugin.uninstall_mod("dragonballsparkingzero", "SparkingZERO", self.game["modsSubdir"],
                                           "Perf", "folder", 1790600, "", "starred"))
        self.assertTrue(r["ok"], r)
        with open(os.path.join(cfg, "Engine.ini")) as f:
            self.assertEqual(f.read(), "player's own")

    def test_change_mods_folder_and_decline_step1(self):
        p = self.plugin
        r = _run(p.experimental_folder_options(1790600))
        self.assertIn("SparkingZERO/Content/Paks/~mods", r["options"])
        self.assertFalse(_run(p.set_experimental_mods_folder(1790600, "../x"))["ok"])
        r = _run(p.set_experimental_mods_folder(1790600, "SparkingZERO/Content/Paks/LogicMods"))
        self.assertTrue(r["ok"], r)
        st = main._load_settings()
        st["installed"] = {"dragonballsparkingzero": {"Goku": {"mod_id": 1, "name": "Goku"}}}
        main._save_settings(st)
        r = _run(p.set_experimental_mods_folder(1790600, "SparkingZERO/Content/Paks/~mods"))
        self.assertFalse(r["ok"])
        self.assertIn("Uninstall", r["error"])
        g = main._load_settings()["experimental_games"]["1790600"]
        g["framework"] = {"nexusModId": 18, "installKind": "copyRootTracked", "installSubdir": ""}
        st = main._load_settings(); st["experimental_games"]["1790600"] = g; main._save_settings(st)
        r = _run(p.set_experimental_framework(1790600, "none"))
        self.assertTrue(r["ok"])
        g = main._load_settings()["experimental_games"]["1790600"]
        self.assertNotIn("framework", g)
        self.assertTrue(g["frameworkDeclined"])

    def test_plain_pak_left_to_mods_folder(self):
        d = self.scratch(["Goku_P.pak", "Goku_P.utoc"])
        self.assertEqual(main._experimental_root_install(
            d, self.root, self.game["modsSubdir"], self.game, "dragonballsparkingzero", 1790600, {"name": "G"}), "")

    def test_curated_domains_never_match(self):
        self.assertIsNone(main._experimental_game_for("skyrimspecialedition"))


class OverstrikeTests(unittest.TestCase):
    def setUp(self):
        self.plugin = main.Plugin()
        self.root = main._game_dir("Marvel's Spider-Man Remastered")
        main._force_rmtree(self.root)
        self.ovs = os.path.join(self.root, "Overstrike")
        os.makedirs(os.path.join(self.ovs, "Mods Library"), exist_ok=True)
        self.calls = os.path.join(self.ovs, "calls.txt")
        exe = os.path.join(self.ovs, "Overstrike.exe")
        with open(exe, "w") as f:
            f.write("#!/bin/sh\n"
                    "echo \"$@\" >> calls.txt\n"
                    "if [ \"$1\" = create-profile ]; then mkdir -p Profiles; "
                    "printf '{\"game\":\"MSMR\",\"path\":\"x\",\"mods\":[]}' > Profiles/$2.json; fi\n")
        os.chmod(exe, 0o755)
        self.game = {"appId": 1817070, "nexusDomain": "marvelsspidermanremastered",
                     "installDirName": "Marvel's Spider-Man Remastered"}
        main.experimental_games.apply_tool_profile(self.game, 4199)
        main._save_settings({
            "experimental_games": {"1817070": self.game},
            "installed": {"marvelsspidermanremastered": {
                "Suit B": {"mode": "files", "target": "Overstrike/Mods Library",
                           "files": ["b.suit"], "install_seq": 2},
                "Mod A": {"mode": "files", "target": "Overstrike/Mods Library",
                          "files": ["a.smpcmod"], "install_seq": 1}}},
        })

    def test_apply_writes_profile_and_runs_install(self):
        r = _run(main._overstrike_apply(self.game))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["count"], 2)
        with open(os.path.join(self.ovs, "Profiles", "Nexus.json")) as f:
            data = main.json.load(f)
        self.assertEqual(data["mods"], [["a.smpcmod", True], ["b.suit", True]])
        self.assertEqual(data["game"], "MSMR")
        with open(self.calls) as f:
            lines = f.read().splitlines()
        self.assertTrue(lines[0].startswith("create-profile Nexus "))
        self.assertEqual(lines[-1], "install-mods Nexus")

    def test_reapply_after_update_or_verify(self):
        r = _run(main._overstrike_apply(self.game))
        self.assertTrue(r["ok"], r)
        self.assertEqual(main._tool_reapply_reason(self.game), "")
        toc = os.path.join(self.root, "asset_archive", "toc")
        os.makedirs(os.path.dirname(toc), exist_ok=True)
        st = main._load_settings()
        open(toc, "w").close()
        os.utime(toc, (1000, 1000))
        st["tool_apply_state"]["marvelsspidermanremastered"]["toc_mtime"] = 1000.0
        st["tool_apply_state"]["marvelsspidermanremastered"]["buildid"] = "100"
        main._save_settings(st)
        with unittest.mock.patch.object(main, "_steam_build_id", lambda a: "100"):
            self.assertEqual(main._tool_reapply_reason(self.game), "")
            os.utime(toc, (5000, 5000))
            self.assertEqual(main._tool_reapply_reason(self.game), "Steam restored the game's files")
        os.utime(toc, (1000, 1000))
        with unittest.mock.patch.object(main, "_steam_build_id", lambda a: "999"):
            self.assertEqual(main._tool_reapply_reason(self.game), "the game updated")

    def test_no_mods_uninstalls(self):
        main._save_settings({"experimental_games": {"1817070": self.game}})
        r = _run(main._overstrike_apply(self.game))
        self.assertTrue(r["ok"], r)
        with open(self.calls) as f:
            self.assertEqual(f.read().splitlines()[-1], "uninstall-mods Nexus")

    def test_missing_overstrike(self):
        os.remove(os.path.join(self.ovs, "Overstrike.exe"))
        self.assertFalse(_run(main._overstrike_apply(self.game))["ok"])

    def test_superseded_guess_is_cleaned_up(self):
        # The earlier guess: the old modding tool in the game root, a mod in Mods/.
        for rel in ("DotNetZip.dll", "SpiderManPCTool.exe", "Mods/Play As Blackcat/x.smpcmod"):
            path = os.path.join(self.root, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
        st = main._load_settings()
        st["experimental_frameworks"] = {"marvelsspidermanremastered/51": {
            "install_dir": "Marvel's Spider-Man Remastered",
            "files": ["DotNetZip.dll", "SpiderManPCTool.exe"], "backups": []}}
        st["installed"]["marvelsspidermanremastered"]["Play As Blackcat"] = {"name": "Play As Blackcat"}
        main._save_settings(st)
        main._undo_superseded_experimental(self.game, 51, "Mods")
        self.assertFalse(os.path.exists(os.path.join(self.root, "DotNetZip.dll")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "Mods")))
        st = main._load_settings()
        self.assertNotIn("Play As Blackcat", st["installed"]["marvelsspidermanremastered"])
        self.assertIn("Mod A", st["installed"]["marvelsspidermanremastered"])
        self.assertEqual(st["experimental_dropped"]["marvelsspidermanremastered"], ["Play As Blackcat"])


class WindowsPathTests(unittest.TestCase):
    def test_prefix_paths_map_to_the_real_profile(self):
        env = {"LOCALAPPDATA": "/u/AppData/Local", "APPDATA": "/u/AppData/Roaming",
               "USERPROFILE": "/u"}
        with unittest.mock.patch.dict(os.environ, env), \
                unittest.mock.patch.object(main.sys, "platform", "win32"):
            self.assertEqual(main._prefix_user_path(489830, "AppData", "Local", "Skyrim Special Edition", "plugins.txt"),
                             os.path.join("/u/AppData/Local", "Skyrim Special Edition", "plugins.txt"))
            self.assertEqual(main._prefix_user_path(1, "Documents", "My Games", "Fallout4", "Fallout4.ini"),
                             os.path.join("/u", "Documents", "My Games", "Fallout4", "Fallout4.ini"))
            self.assertEqual(main._prefix_user_path(1, "AppData", "Roaming", "x"),
                             os.path.join("/u/AppData/Roaming", "x"))
            r = _run(main.Plugin().fix_prefix_runtime(1))
            self.assertTrue(r["ok"])
            self.assertFalse(r["updated"])

    def test_bethesda_profile(self):
        g = {"nexusDomain": "oblivion", "modsSubdir": "Mods", "flatModExtensions": [".x"]}
        self.assertTrue(main.experimental_games.apply_bethesda_profile(g))
        self.assertEqual((g["installMode"], g["modsSubdir"], g["pluginsTxtSubpath"], g["pluginsTxtStyle"]),
                         ("dataDir", "Data", "Oblivion/plugins.txt", "listed"))
        self.assertNotIn("flatModExtensions", g)
        self.assertFalse(main.experimental_games.apply_bethesda_profile({"nexusDomain": "witcher3"}))


class ExperimentalInstallEndToEnd(unittest.TestCase):
    """Through install_mod itself, with the archive pre-cached."""
    DOMAIN = "marvelsmidnightsuns"
    GAME = "Merge Test Game"
    SUB = "MidnightSuns/Content/Paks/~mods"

    def setUp(self):
        main._save_settings({"api_key": "k", "experimental_games": {"368260": {
            "appId": 368260, "nexusDomain": self.DOMAIN, "installDirName": self.GAME,
            "modsSubdir": self.SUB, "engine": "unreal", "installMode": "folder",
            "processName": "MidnightSuns/Binaries/Win64/MidnightSuns-Win64-Shipping.exe"}}})
        self.root = main._game_dir(self.GAME)
        main._force_rmtree(self.root)
        os.makedirs(os.path.join(self.root, "MidnightSuns", "Content", "Paks"))
        os.makedirs(os.path.join(self.root, "MidnightSuns", "Binaries", "Win64"))
        os.makedirs(main.DOWNLOADS_DIR, exist_ok=True)
        self.plugin = main.Plugin()

    def install(self, file_id, members, slug=""):
        archive = main._archive_cache_path(110, file_id, f"m{file_id}.zip")
        shutil.rmtree(main._extract_scratch(110, file_id), ignore_errors=True)
        with zipfile.ZipFile(archive, "w") as z:
            for rel in members:
                z.writestr(rel, str(file_id))
        return _run(self.plugin.install_mod(
            self.DOMAIN, 110, file_id, f"m{file_id}.zip", "Magik", "2.0", self.GAME, self.SUB,
            install_mode="folder", app_id=368260, collection_slug=slug))

    def mods(self):
        d = os.path.join(self.root, *self.SUB.split("/"), "Magik")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def test_collection_files_of_one_mod_merge(self):
        self.assertTrue(self.install(1, ["Magik/a_P.pak"], "col")["ok"])
        self.assertTrue(self.install(2, ["Magik/b_P.pak"], "col")["ok"])
        self.assertEqual(self.mods(), ["a_P.pak", "b_P.pak"])
        rec = main._load_settings()["installed"][self.DOMAIN]["Magik"]
        self.assertEqual(rec["file_ids"], [1, 2])

    def test_outside_a_collection_a_new_file_replaces(self):
        self.install(1, ["Magik/a_P.pak"])
        self.install(2, ["Magik/b_P.pak"])
        self.assertEqual(self.mods(), ["b_P.pak"])

    def test_game_folder_mod_through_install_mod(self):
        r = self.install(3, ["Binaries/Win64/dxgi.dll", "readme.txt"])
        self.assertTrue(r["ok"], r)
        self.assertTrue(os.path.isfile(os.path.join(
            self.root, "MidnightSuns", "Binaries", "Win64", "dxgi.dll")))


if __name__ == "__main__":
    unittest.main()
