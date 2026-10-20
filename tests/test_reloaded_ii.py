"""Reloaded-II support: profile, setup, mod installs, apply with deps."""
import asyncio
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import unittest.mock
import zipfile

from test_backend import main  # stubs decky/aiohttp and imports main.py

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import reloaded_ii  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _pe(imports, is64=True):
    """A minimal PE whose import table names `imports`."""
    data = bytearray(0x800)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x40)
    data[0x40:0x44] = b"PE\0\0"
    opt_size = 240 if is64 else 224
    struct.pack_into("<HH", data, 0x44, 0x8664 if is64 else 0x14C, 1)
    struct.pack_into("<H", data, 0x44 + 16, opt_size)
    opt = 0x40 + 24
    struct.pack_into("<H", data, opt, 0x20B if is64 else 0x10B)
    dd = opt + (112 if is64 else 96)
    struct.pack_into("<I", data, dd + 8, 0x1000)  # import directory rva
    sec = opt + opt_size
    struct.pack_into("<IIII", data, sec + 8, 0x400, 0x1000, 0x400, 0x400)
    name_off = 0x600
    for i, name in enumerate(imports):
        struct.pack_into("<I", data, 0x400 + 20 * i + 12, 0x1000 + (name_off - 0x400))
        raw = name.encode() + b"\0"
        data[name_off:name_off + len(raw)] = raw
        name_off += len(raw)
    return bytes(data)


class PureHelperTests(unittest.TestCase):
    def test_pe_imports_and_asi_name(self):
        is64, imports = reloaded_ii.pe_info(_pe(["KERNEL32.dll", "VERSION.dll", "dinput8.dll"]))
        self.assertTrue(is64)
        self.assertEqual(imports, ["kernel32.dll", "version.dll", "dinput8.dll"])
        self.assertEqual(reloaded_ii.pick_asi_name(is64, imports), "version.dll")
        self.assertEqual(reloaded_ii.pick_asi_name(True, ["kernel32.dll"]), "")
        self.assertEqual(reloaded_ii.pe_info(b"not a program"), (False, []))

    def test_pe_32bit(self):
        is64, imports = reloaded_ii.pe_info(_pe(["d3d9.dll"], is64=False))
        self.assertFalse(is64)
        self.assertEqual(reloaded_ii.pick_asi_name(is64, imports), "d3d9.dll")

    def test_find_mods(self):
        self.assertEqual(reloaded_ii.find_mods(
            ["p4g.mod/ModConfig.json", "p4g.mod/Redirector/a.bin", "readme.txt"]),
            ["p4g.mod"])
        self.assertEqual(reloaded_ii.find_mods(["ModConfig.json", "x.dll"]), [""])

    def test_profile(self):
        g = {"nexusDomain": "persona4golden", "processName": "P4G.exe"}
        self.assertTrue(reloaded_ii.apply_reloaded_profile(g))
        self.assertEqual(g["toolApply"], "reloaded")
        self.assertEqual(g["framework"]["installKind"], "reloaded2")
        self.assertEqual(g["framework"]["detectFile"], "Reloaded.Mod.Loader.Bootstrapper.asi")
        self.assertFalse(reloaded_ii.apply_reloaded_profile({"nexusDomain": "skyrim"}))

    def test_enabled_mods_keeps_players_own(self):
        self.assertEqual(
            reloaded_ii.enabled_mods(["mine", "ours.old", "ours"], {"ours", "ours.old"}, ["ours", "dep"]),
            ["mine", "ours", "dep"])

    def test_nupkg_targets(self):
        self.assertEqual(reloaded_ii.nupkg_member_target("ModConfig.json"), "ModConfig.json")
        for skip in ("_rels/.rels", "package/services/x.psmdcp", "[Content_Types].xml",
                     "x.nuspec", "../evil", "dir/"):
            self.assertEqual(reloaded_ii.nupkg_member_target(skip), "", skip)

    def test_classify(self):
        import experimental_games
        g = {"nexusDomain": "persona4golden", "processName": "P4G.exe"}
        reloaded_ii.apply_reloaded_profile(g)
        self.assertEqual(experimental_games.classify_mod(
            ["MyMod/ModConfig.json", "MyMod/FEmulator/AWB/x.adx"], g, set(), {}), "tool_managed")


class ReloadedBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = unittest.mock.patch.dict(os.environ, {
            "APPDATA": os.path.join(self.tmp, "Roaming"),
            "LOCALAPPDATA": os.path.join(self.tmp, "Local"),
        })
        self.env.start()
        self.launcher = os.path.join(self.tmp, "Local", "Reloaded-II")
        boot = os.path.join(self.launcher, "Loader", "x64", "Bootstrapper")
        os.makedirs(boot)
        open(os.path.join(self.launcher, "Reloaded-II.exe"), "wb").close()
        with open(os.path.join(boot, reloaded_ii.BOOTSTRAPPER), "wb") as f:
            f.write(b"boot")
        self.root = main._game_dir("Persona 4 Golden")
        shutil.rmtree(self.root, ignore_errors=True)
        os.makedirs(self.root)
        with open(os.path.join(self.root, "P4G.exe"), "wb") as f:
            f.write(_pe(["KERNEL32.dll", "VERSION.dll"]))
        self.game = {"appId": 1113000, "nexusDomain": "persona4golden",
                     "installDirName": "Persona 4 Golden", "processName": "P4G.exe",
                     "name": "Persona 4 Golden"}
        reloaded_ii.apply_reloaded_profile(self.game)
        main._save_settings({"experimental_games": {"1113000": self.game}})
        self.plugin = main.Plugin()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.root, ignore_errors=True)

    def _setup(self):
        async def asi(launcher, is64):
            return b"asi-loader-64" if is64 else b"asi-loader-32"
        with unittest.mock.patch.object(main, "_reloaded_asi_loader", asi):
            return _run(main._reloaded_setup("persona4golden"))

    def _app_config(self):
        with open(os.path.join(self.launcher, "Apps", "p4g.exe", "AppConfig.json")) as f:
            return json.load(f)

    def test_setup_deploys_loader_and_configs(self):
        with open(os.path.join(self.root, "version.dll"), "wb") as f:
            f.write(b"games-own")
        r = self._setup()
        self.assertTrue(r["ok"], r)
        with open(os.path.join(self.root, "Reloaded.Mod.Loader.Bootstrapper.asi"), "rb") as f:
            self.assertEqual(f.read(), b"boot")
        with open(os.path.join(self.root, "version.dll"), "rb") as f:
            self.assertEqual(f.read(), b"asi-loader-64")
        with open(main._reloaded_config_path()) as f:
            cfg = json.load(f)
        self.assertTrue(cfg["LoaderPath64"].endswith(os.path.join("x64", "Reloaded.Mod.Loader.dll")))
        app = self._app_config()
        self.assertEqual(app["AppId"], "p4g.exe")
        self.assertEqual(app["AppLocation"], os.path.join(self.root, "P4G.exe"))
        # Remove puts the game's own dll back.
        removed = _run(self.plugin.remove_experimental_framework(1113000))
        self.assertTrue(removed["ok"], removed)
        self.assertFalse(os.path.exists(os.path.join(self.root, "Reloaded.Mod.Loader.Bootstrapper.asi")))
        with open(os.path.join(self.root, "version.dll"), "rb") as f:
            self.assertEqual(f.read(), b"games-own")

    def test_helper_programs_get_no_mod_entries(self):
        d = os.path.join(self.root, "crashdat", "bin")
        os.makedirs(d)
        open(os.path.join(d, "crashpad_handler.exe"), "wb").close()
        self.assertTrue(self._setup()["ok"])
        with open(os.path.join(self.launcher, "Apps", "crashpad_handler.exe", "AppConfig.json")) as f:
            cfg = json.load(f)
        self.assertEqual(cfg["EnabledMods"], [])
        self.assertEqual(cfg["AppId"], "crashpad_handler.exe")
        self.assertFalse(os.path.exists(os.path.join(self.launcher, "Apps", "p4g.exe", "x")))

    def test_setup_joins_existing_asi_plugins(self):
        os.makedirs(os.path.join(self.root, "scripts"))
        open(os.path.join(self.root, "scripts", "widescreen.asi"), "wb").close()
        r = self._setup()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["files"], ["scripts/Reloaded.Mod.Loader.Bootstrapper.asi"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "version.dll")))

    def test_setup_refuses_exe_without_supported_import(self):
        with open(os.path.join(self.root, "P4G.exe"), "wb") as f:
            f.write(_pe(["KERNEL32.dll"]))
        r = self._setup()
        self.assertFalse(r["ok"])
        self.assertIn("ASI loader", r["error"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "Reloaded.Mod.Loader.Bootstrapper.asi")))

    def _scratch(self, mods):
        scratch = os.path.join(main.DOWNLOADS_DIR, "r2-scratch")
        shutil.rmtree(scratch, ignore_errors=True)
        rel = []
        for folder, mod_id, deps in mods:
            d = os.path.join(scratch, folder)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "ModConfig.json"), "w") as f:
                json.dump({"ModId": mod_id, "ModDependencies": deps}, f)
            with open(os.path.join(d, "data.bin"), "w") as f:
                f.write(mod_id)
            rel += [f"{folder}/ModConfig.json", f"{folder}/data.bin"]
        return scratch, rel

    def _install(self, name, mods):
        scratch, _rel = self._scratch(mods)
        return main._experimental_root_install(
            scratch, self.root, self.game["modsSubdir"], self.game, "persona4golden", 1113000,
            {"mod_id": 1, "file_id": 2, "name": name, "installed_at": 1})

    def test_install_apply_with_dependencies_and_uninstall(self):
        self._setup()
        key = self._install("Costume Pack", [("Costumes", "p4gpc.costumes", ["lib.a"])])
        self.assertTrue(key)
        mods_dir = main._reloaded_mods_dir()
        self.assertTrue(os.path.isfile(os.path.join(mods_dir, "p4gpc.costumes", "ModConfig.json")))
        rec = main._load_settings()["installed"]["persona4golden"][key]
        self.assertEqual(rec["reloadedIds"], ["p4gpc.costumes"])
        self.assertEqual(rec["base"], mods_dir)

        def nupkg(mod_id, deps):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("ModConfig.json", json.dumps({"ModId": mod_id, "ModDependencies": deps}))
                z.writestr(f"{mod_id}.nuspec", "<x/>")
                z.writestr("_rels/.rels", "x")
                z.writestr("lib.dll", "code")
            return buf.getvalue()

        feed = {
            main.reloaded_ii.NUGET_INDEX: json.dumps({"resources": [
                {"@type": "PackageBaseAddress/3.0.0", "@id": "https://feed/flat/"}]}).encode(),
            "https://feed/flat/lib.a/index.json": b'{"versions": ["1.0.0", "1.2.0", "1.10.0-beta"]}',
            "https://feed/flat/lib.a/1.2.0/lib.a.1.2.0.nupkg": nupkg("lib.a", ["lib.b"]),
            "https://feed/flat/lib.b/index.json": b'{"versions": ["2.0.0"]}',
            "https://feed/flat/lib.b/2.0.0/lib.b.2.0.0.nupkg": nupkg("lib.b", ["not.on.feed"]),
        }

        async def fetch(url, timeout=300):
            if url not in feed:
                raise RuntimeError("HTTP 404")
            return feed[url]

        # The player's own Reloaded mod stays enabled.
        app = self._app_config()
        app["EnabledMods"] = ["players.own"]
        main._write_json(os.path.join(self.launcher, "Apps", "p4g.exe", "AppConfig.json"), app)
        with unittest.mock.patch.object(main, "_fetch_bytes", fetch):
            r = _run(main._reloaded_apply(self.game))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r.get("fetched"), ["lib.a", "lib.b"], r)
        self.assertEqual(r["missing"], ["not.on.feed"])
        self.assertEqual(self._app_config()["EnabledMods"],
                         ["players.own", "p4gpc.costumes", "lib.a", "lib.b"])
        self.assertTrue(os.path.isfile(os.path.join(mods_dir, "lib.a", "lib.dll")))
        self.assertFalse(os.path.exists(os.path.join(mods_dir, "lib.a", "lib.a.nuspec")))

        # Uninstalling drops it from the list (deps no longer needed go too).
        settings = main._load_settings()
        main._remove_files_record("persona4golden", key, self.root, settings)
        main._save_settings(settings)
        self.assertFalse(os.path.exists(os.path.join(mods_dir, "p4gpc.costumes")))
        with unittest.mock.patch.object(main, "_fetch_bytes", fetch):
            r = _run(main._reloaded_apply(self.game))
        self.assertEqual(self._app_config()["EnabledMods"], ["players.own"])

    def test_disabled_record_leaves_list(self):
        self._setup()
        key = self._install("Mod", [("M", "a.mod", [])])
        settings = main._load_settings()
        settings["installed"]["persona4golden"][key]["enabled"] = False
        main._save_settings(settings)
        r = _run(main._reloaded_apply(self.game))
        self.assertTrue(r["ok"], r)
        self.assertEqual(self._app_config()["EnabledMods"], [])

    def test_non_reloaded_archive_falls_through(self):
        scratch = os.path.join(main.DOWNLOADS_DIR, "r2-plain")
        shutil.rmtree(scratch, ignore_errors=True)
        os.makedirs(scratch)
        with open(os.path.join(scratch, "readme.txt"), "w") as f:
            f.write("x")
        self.assertEqual(main._reloaded_install_mods(
            scratch, ["readme.txt"], self.game, "persona4golden", {"name": "x"}), "")

    def test_framework_profile_wins(self):
        g = {"appId": 1113000, "nexusDomain": "persona4golden", "processName": "P4G.exe"}
        _run(self.plugin._experimental_framework(g))
        self.assertEqual(g["toolApply"], "reloaded")
        self.assertTrue(g["frameworkChecked"])

    def _fresh_install(self, run):
        shutil.rmtree(self.launcher)

        async def fetch(url, timeout=300):
            return b"MZ fake setup"
        with unittest.mock.patch.object(main, "_fetch_bytes", fetch), \
                unittest.mock.patch.object(main, "_run_elevated", run):
            return self._setup()

    def test_setup_runs_installer_elevated(self):
        calls = []

        def run(exe, args, timeout):
            calls.append(args)
            boot = os.path.join(self.launcher, "Loader", "x64", "Bootstrapper")
            os.makedirs(boot)
            open(os.path.join(self.launcher, "Reloaded-II.exe"), "wb").close()
            with open(os.path.join(boot, reloaded_ii.BOOTSTRAPPER), "wb") as f:
                f.write(b"boot")
            return 0
        r = self._fresh_install(run)
        self.assertTrue(r["ok"], r)
        self.assertIn("--nogui", calls[0])
        self.assertEqual(calls[0][-2:], ["--installdir", self.launcher])

    def test_declined_uac_says_so(self):
        r = self._fresh_install(lambda exe, args, timeout: main._ELEVATION_DECLINED)
        self.assertFalse(r["ok"])
        self.assertIn("permission prompt was declined", r["error"])


if __name__ == "__main__":
    unittest.main()


class VortexMergeInstallTests(unittest.TestCase):
    def test_merge_install_and_uninstall(self):
        root = main._game_dir("Seven Days")
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(os.path.join(root, "Mods"))
        os.makedirs(os.path.join(root, "Data"))
        game = {"appId": 7, "nexusDomain": "7daystodie", "installDirName": "Seven Days",
                "processName": "7DaysToDie.exe", "modsSubdir": "Mods", "engine": "unity",
                "mergeInto": "Mods"}
        main._save_settings({"experimental_games": {"7": game}})
        scratch = os.path.join(main.DOWNLOADS_DIR, "merge-scratch")
        shutil.rmtree(scratch, ignore_errors=True)
        os.makedirs(os.path.join(scratch, "BetterLoot", "Config"))
        for rel in ("BetterLoot/ModInfo.xml", "BetterLoot/Config/loot.xml"):
            with open(os.path.join(scratch, *rel.split("/")), "w") as f:
                f.write("x")
        key = main._experimental_root_install(scratch, root, "Mods", game, "7daystodie", 7,
                                              {"mod_id": 1, "file_id": 1, "name": "Better Loot"})
        self.assertTrue(key)
        self.assertTrue(os.path.isfile(os.path.join(root, "Mods", "BetterLoot", "ModInfo.xml")))
        settings = main._load_settings()
        main._remove_files_record("7daystodie", key, root, settings)
        main._save_settings(settings)
        self.assertFalse(os.path.exists(os.path.join(root, "Mods", "BetterLoot")))
        self.assertTrue(os.path.isdir(os.path.join(root, "Mods")))
        shutil.rmtree(root, ignore_errors=True)
