"""Dragon Ball Xenoverse 2: XV2 Patcher, XV2 Mods Installer and .x2m mods."""
import asyncio
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
import zipfile

from test_backend import main  # stubs decky/aiohttp and imports main.py

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import experimental_games as eg  # noqa: E402
import xenoverse2 as xv  # noqa: E402

GUID = "0a1b2c3d-1111-2222-3333-444455556666"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _x2m(path, name="Goku Black", guid=GUID):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("x2m.xml", f'<X2M type="NEW_CHARACTER">\n <MOD_NAME value="{name}" />\n'
                              f' <MOD_GUID value="{guid.upper()}" />\n</X2M>')
        z.writestr("chara/X/X.bcs", "x")


def _tools_tree(base):
    for rel, data in {
        "XV2 Patcher/bin/xinput1_3.dll": b"..XV2PATCHER VERSION 4.7 ..",
        "XV2 Patcher/XV2PATCHER/xv2patcher.ini": b"[Patches]\nloose_files = false\n",
        "XV2 Patcher/XV2PATCHER/patches/a.xml": b"<x/>",
        "XV2 Mods Installer/xv2ins.exe": b"MZ",
        "XV2 Mods Installer/Qt5Core.dll": b"MZ",
        "XV2 Mods Installer/Internal/CharaSele/a.as": b"x",
        "XV2 Mods Installer/xv2characreat.exe": b"MZ",
        "readme.txt": b"hi",
    }.items():
        p = os.path.join(base, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)


class HelperTests(unittest.TestCase):
    def test_profile(self):
        game = {"nexusDomain": xv.DOMAIN, "processName": "START.exe"}
        self.assertTrue(xv.apply_xv2_profile(game))
        self.assertEqual(game["processName"], "bin/DBXV2.exe")
        self.assertEqual(game["toolApply"], "xv2ins")
        self.assertEqual(game["mergeInto"], "data")
        self.assertEqual(game["framework"]["installKind"], "xv2tools")
        self.assertIn("EasyAntiCheat", game["framework"]["warning"])
        self.assertFalse(xv.apply_xv2_profile({"nexusDomain": "skyrim"}))

    def test_classification(self):
        game = {"nexusDomain": xv.DOMAIN}
        xv.apply_xv2_profile(game)
        roots = {"bin", "cpk", "data", "XV2PATCHER", "START.exe"}

        def verdict(paths):
            return eg.classify_mod(paths, game, roots, {}, False, {})
        self.assertEqual(verdict(["Goku.x2m"]), "tool_managed")
        self.assertEqual(verdict(["data/chara/GOK/GOK_000.emd"]), "mods_folder")
        self.assertEqual(verdict(["chara/GOK/GOK_000.emd"]), "mods_folder")
        self.assertEqual(verdict(["Setup.exe", "readme.txt"]), "program")

    def test_merge_into_data(self):
        self.assertEqual(xv.apply_xv2_profile({"nexusDomain": xv.DOMAIN}), True)
        self.assertEqual(eg.plan_merge(["data/ui/a.emb"], "data", set()), [("data/ui/a.emb", "data/ui/a.emb")])
        self.assertEqual(eg.plan_merge(["ui/a.emb"], "data", set()), [("ui/a.emb", "data/ui/a.emb")])

    def test_find_and_plan_tools(self):
        with tempfile.TemporaryDirectory() as d:
            _tools_tree(d)
            found = xv.find_tools(d)
            self.assertTrue(found["patcher"].endswith("XV2 Patcher"))
            self.assertTrue(found["installer"].endswith("XV2 Mods Installer"))
            p = sorted(r for _s, r in xv.patcher_files(found["patcher"]))
            self.assertEqual(p, ["XV2PATCHER/patches/a.xml", "XV2PATCHER/xv2patcher.ini",
                                 "bin/xinput1_3.dll"])
            i = sorted(r for _s, r in xv.installer_files(found["installer"]))
            self.assertEqual(i, ["Internal/CharaSele/a.as", "Qt5Core.dll", "xv2ins.exe"])

    def test_candidate_archives(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("Eternity Tools 4.7.zip", "holiday.zip", "XV2_Patcher.7z", "xv2.txt"):
                open(os.path.join(d, n), "w").close()
            got = [os.path.basename(p) for p in xv.candidate_archives([d, "/nope"])]
            self.assertEqual(sorted(got), ["Eternity Tools 4.7.zip", "XV2_Patcher.7z"])

    def test_download_links(self):
        html = ('<a href="/the-citadel/x/mods/eternity-tools/download/123">Download Mod</a>'
                '<a href="https://mega.nz/file/abc">stages</a><a href="/about">about</a>'
                '<a href="https://cdn.example.com/f/EternityTools.zip?x=1">z</a>')
        links = xv.download_links(html, "https://videogamemods.com/the-citadel/x/mods/eternity-tools")
        self.assertEqual(links[0], "https://cdn.example.com/f/EternityTools.zip?x=1")
        self.assertIn("https://videogamemods.com/the-citadel/x/mods/eternity-tools/download/123", links)
        self.assertFalse(any("mega.nz" in u or "/about" in u for u in links))

    def test_inis(self):
        out = xv.patcher_ini("[General]\nx = 1\n[Patches]\nloose_files = false\nother = 2\n")
        self.assertIn("loose_files = true", out)
        self.assertIn("unlock_chara_mods = true", out)
        self.assertIn("other = 2", out)
        self.assertIn("[Patches]\nloose_files = true", xv.patcher_ini(""))
        ini = xv.installer_ini("[General]\nglobal_lang = 0\n[Editor]\nlf = c\n",
                               "C:\\Steam\\common\\DB Xenoverse 2\\")
        self.assertIn("game_directory = C:/Steam/common/DB Xenoverse 2", ini)
        self.assertIn("global_lang = 0", ini)  # kept, someone chose it
        self.assertIn("language_asked = true", ini)
        self.assertIn("lf = c", ini)
        self.assertIn("global_lang = -1", xv.installer_ini("", "C:/g"))

    def test_x2m_info_and_guids(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.x2m")
            _x2m(p)
            self.assertEqual(xv.x2m_info(p), {"name": "Goku Black", "guid": GUID})
            self.assertEqual(xv.x2m_info(os.path.join(d, "missing.x2m")), {"name": "", "guid": ""})
        self.assertEqual(xv.installed_guids([GUID.upper() + ".x2d", "readme.txt"]), {GUID})

    def test_plan_and_args(self):
        inst, gone = xv.plan_x2m({"a.x2m": "1", "b.x2m": "2"},
                                 {"a.x2m": {"fp": "1"}, "b.x2m": {"fp": "old"}, "c.x2m": {"fp": "3", "guid": "g"}})
        self.assertEqual(inst, ["b.x2m"])
        self.assertEqual(gone, [{"path": "c.x2m", "fp": "3", "guid": "g"}])
        self.assertEqual(xv.installer_args(["a"]), ["a", "a"])
        self.assertEqual(xv.installer_args(["a", "b"]), ["a", "b"])

    def test_auto_answer(self):
        self.assertTrue(xv.auto_answer("Activate silent mode?"))
        self.assertTrue(xv.auto_answer("xv2ins 3.9"))
        self.assertFalse(xv.auto_answer("xv2ins"))  # clean-install / patcher missing
        self.assertFalse(xv.auto_answer("Language optimization"))
        self.assertFalse(xv.auto_answer(""))

    def test_patcher_version(self):
        self.assertEqual(xv.patcher_version(b"aaXV2PATCHER VERSION 4.75\0"), 4.75)
        self.assertEqual(xv.patcher_version(b"nothing"), -1.0)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.root = main._game_dir("DB Xenoverse 2")
        shutil.rmtree(self.root, ignore_errors=True)
        os.makedirs(os.path.join(self.root, "bin"))
        open(os.path.join(self.root, "bin", "DBXV2.exe"), "wb").close()
        self.game = {"appId": 454650, "nexusDomain": xv.DOMAIN, "installDirName": "DB Xenoverse 2"}
        xv.apply_xv2_profile(self.game)
        main._save_settings({"experimental_games": {"454650": self.game}})
        self.dl = tempfile.mkdtemp()
        self.appdata = tempfile.mkdtemp()
        self.patches = [
            unittest.mock.patch.object(main, "_user_downloads_dir", lambda: self.dl),
            unittest.mock.patch.dict(os.environ, {"APPDATA": self.appdata}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        for d in (self.root, self.dl, self.appdata):
            shutil.rmtree(d, ignore_errors=True)

    def test_setup_from_extracted_downloads_and_remove(self):
        _tools_tree(os.path.join(self.dl, "Eternity Tools 4.7"))
        r = _run(main._xv2_setup(xv.DOMAIN))
        self.assertTrue(r["ok"], r)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "bin", "xinput1_3.dll")))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "xv2ins.exe")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "xv2characreat.exe")))
        self.assertTrue(os.path.isdir(os.path.join(self.root, "data")))
        with open(os.path.join(self.root, "XV2PATCHER", "xv2patcher.ini")) as f:
            self.assertIn("loose_files = true", f.read())
        with open(os.path.join(self.appdata, "XV2INS", "xv2ins.ini")) as f:
            self.assertIn("language_asked = true", f.read())
        removed = main._remove_tracked_framework(self.game, 0, "")
        self.assertGreater(removed, 4)
        self.assertFalse(os.path.exists(os.path.join(self.root, "xv2ins.exe")))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "bin", "DBXV2.exe")))

    def test_setup_from_archive(self):
        src = tempfile.mkdtemp()
        try:
            _tools_tree(src)
            shutil.make_archive(os.path.join(self.dl, "Eternity Tools"), "zip", src)
        finally:
            shutil.rmtree(src)
        r = _run(main._xv2_setup(xv.DOMAIN))
        self.assertTrue(r["ok"], r)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "Internal", "CharaSele", "a.as")))

    def test_setup_without_tools_explains(self):
        async def nofetch():
            return ""
        with unittest.mock.patch.object(main, "_xv2_fetch_tools", nofetch):
            r = _run(main._xv2_setup(xv.DOMAIN))
        self.assertFalse(r["ok"])
        self.assertIn("Download Mod", r["error"])
        self.assertEqual(r["openUrl"], xv.TOOLS_PAGE)

    def test_x2m_kept_whole_by_extract(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "12-34.x2m")
            _x2m(p)
            out = os.path.join(d, "out")
            self.assertEqual(_run(main._extract_archive(p, out)), "")
            self.assertEqual(os.listdir(out), ["12-34.x2m"])

    def _store(self, *names):
        store = os.path.join(self.root, xv.X2M_STORE)
        os.makedirs(store, exist_ok=True)
        for n, guid in names:
            _x2m(os.path.join(store, n), name=n[:-4], guid=guid)
        open(os.path.join(self.root, "xv2ins.exe"), "wb").close()

    def test_apply_installs_and_opens_window_for_removed(self):
        self._store(("Black.x2m", GUID))
        calls = []

        def fake_run(exe, args, timeout):
            calls.append(args)
            d = os.path.join(self.root, "data", "InstallData")
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, GUID + ".x2d"), "w").close()
            return {"rc": 0}
        opened = []
        with unittest.mock.patch.object(main, "_xv2_run_installer", fake_run), \
                unittest.mock.patch.object(main, "_xv2_open_installer", lambda e: opened.append(e) or True):
            r = _run(main._xv2_apply(self.game))
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["count"], 1)
            self.assertEqual(len(calls[0]), 2)  # one mod is passed twice: silent mode
            # Nothing changed: no second run.
            r = _run(main._xv2_apply(self.game))
            self.assertEqual(len(calls), 1)
            # Removed here: xv2ins can only uninstall in its window.
            os.remove(os.path.join(self.root, xv.X2M_STORE, "Black.x2m"))
            r = _run(main._xv2_apply(self.game))
            self.assertTrue(r["ok"])
            self.assertIn("Uninstall", r["note"])
            self.assertEqual(r["pendingUninstall"], ["Black"])
            self.assertEqual(len(opened), 1)
            # Uninstalled there: the reminder goes away.
            os.remove(os.path.join(self.root, "data", "InstallData", GUID + ".x2d"))
            r = _run(main._xv2_apply(self.game))
            self.assertNotIn("pendingUninstall", r)
            self.assertEqual(len(opened), 1)

    def test_apply_reports_failures(self):
        self._store(("A.x2m", GUID), ("B.x2m", "99999999-1111-2222-3333-444455556666"))

        def fake_run(exe, args, timeout):
            d = os.path.join(self.root, "data", "InstallData")
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, GUID + ".x2d"), "w").close()
            return {"rc": 0}
        with unittest.mock.patch.object(main, "_xv2_run_installer", fake_run):
            r = _run(main._xv2_apply(self.game))
        self.assertFalse(r["ok"])
        self.assertIn("B", r["error"])
        self.assertEqual(r["count"], 1)

    def test_apply_needs_the_installer(self):
        store = os.path.join(self.root, xv.X2M_STORE)
        os.makedirs(store)
        _x2m(os.path.join(store, "A.x2m"))
        r = _run(main._xv2_apply(self.game))
        self.assertFalse(r["ok"])
        self.assertIn("Step 1", r["error"])


if __name__ == "__main__":
    unittest.main()
