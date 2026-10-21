"""Kingdom Hearts HD 1.5+2.5: KHPCPatchManager patches and LuaBackend scripts."""
import asyncio
import os
import shutil
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

from test_backend import main

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import experimental_games as eg  # noqa: E402
import kingdom_hearts as kh  # noqa: E402

TOML = """[kh1]
scripts = [{ path = "scripts/kh1/", relative = true }]
base = 0x3A0606
thread_struct = 0x22B7280
exe = "KINGDOM HEARTS FINAL MIX.exe"
game_docs = "KINGDOM HEARTS HD 1.5+2.5 ReMIX"

[kh2]
scripts = [{ path = "scripts/kh2/", relative = true }]
exe = "KINGDOM HEARTS II FINAL MIX.exe"
game_docs = "KINGDOM HEARTS HD 1.5+2.5 ReMIX"
"""
DIR = "KINGDOM HEARTS -HD 1.5+2.5 ReMIX-"


class KhHelperTests(unittest.TestCase):
    def test_profile_and_classify(self):
        g = {"nexusDomain": "kingdomheartsfinalmix"}
        self.assertTrue(kh.apply_kh_profile(g))
        self.assertEqual(g["toolApply"], "khpatch")
        self.assertEqual(len(g["domainChoices"]), 4)
        self.assertEqual(eg.classify_mod(["x/Better.kh1pcpatch"], g, set(), {}, False, {}), "tool_managed")
        self.assertFalse(kh.apply_kh_profile({"nexusDomain": "skyrim"}))

    def test_plan(self):
        self.assertEqual(kh.kh_plan(["A/B/Mod.kh1pcpatch", "A/readme.txt"], "kh1"),
                         [("A/B/Mod.kh1pcpatch", "Mods/patches/Mod.kh1pcpatch")])
        self.assertEqual(kh.kh_plan(["scripts/kh2/Speed.lua", "scripts/kh2/Other.lua"], "kh2"),
                         [("scripts/kh2/Speed.lua", "Mods/scripts/kh2/Speed.lua"),
                          ("scripts/kh2/Other.lua", "Mods/scripts/kh2/Other.lua")])
        plan = kh.kh_plan(["Inv/Main.lua", "Inv/input.txt"], "kh1")
        self.assertIn(("Inv/input.txt", "Mods/scripts/kh1/Inv/input.txt"), plan)

    def test_toml(self):
        out = kh.luabackend_toml(TOML, "C:\\Games\\KH")
        data = tomllib.loads(out)
        self.assertEqual(data["kh1"]["game_docs"], "My Games/KINGDOM HEARTS HD 1.5+2.5 ReMIX")
        self.assertIn({"path": "C:\\Games\\KH\\Mods\\scripts\\kh2", "relative": False}, data["kh2"]["scripts"])
        self.assertEqual(kh.luabackend_toml(out, "C:\\Games\\KH"), out)

    def test_patcher_output(self):
        ok = "KHPCPatchManager v1.2.1\nApplying KH1 patch...\nApplying patch...\nPatching kh1_first...\nDone!"
        self.assertTrue(kh.patcher_succeeded(ok))
        self.assertFalse(kh.patcher_succeeded("KHPCPatchManager v1.2.1\nApplying KH1 patch..."))
        self.assertFalse(kh.patcher_succeeded(ok.replace("Done!", "Could not find any folder to patch!")))
        self.assertFalse(kh.patcher_succeeded("System.IO.IOException: disk full\n" + ok))
        self.assertTrue(kh.patcher_finished("Done!"))
        self.assertTrue(kh.patcher_finished("There was an error! x"))
        self.assertFalse(kh.patcher_finished("Patching kh1_first..."))

    def test_plan_patches(self):
        self.assertEqual(kh.plan_patches(["a", "b"], ["a", "c"], False), (["b"], ["c"]))
        self.assertEqual(kh.plan_patches(["a", "b"], ["a"], True), (["a", "b"], []))


class KhInstallTests(unittest.TestCase):
    def setUp(self):
        self.root = main._game_dir(DIR)
        shutil.rmtree(self.root, ignore_errors=True)
        os.makedirs(os.path.join(self.root, "Image", "en"))
        with open(os.path.join(self.root, "Image", "en", "kh1_first.hed"), "wb") as f:
            f.write(b"x")
        self.game = {"appId": kh.COLLECTION_APP, "nexusDomain": "kingdomheartsfinalmix",
                     "installDirName": DIR, "modsSubdir": "Mods"}
        kh.apply_kh_profile(self.game)
        main._save_settings({"experimental_games": {str(kh.COLLECTION_APP): self.game}})

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_install_and_apply(self):
        d = tempfile.mkdtemp()
        for f in ("Mod/Better.kh1pcpatch", "Mod/Fast.lua"):
            p = os.path.join(d, *f.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").close()
        key = main._experimental_root_install(d, self.root, "Mods", self.game, "kingdomheartsfinalmix",
                                              1, {"name": "Better"})
        rec = main._load_settings()["installed"]["kingdomheartsfinalmix"][key]
        self.assertIn("Mods/patches/Better.kh1pcpatch", rec["files"])
        self.assertIn("Mods/scripts/kh1/Fast.lua", rec["files"])
        exe = os.path.join(self.root, "KHPCPatchManager", "KHPCPatchManager.exe")
        os.makedirs(os.path.dirname(exe))
        open(exe, "w").close()
        calls = []

        def fake(root, paths):
            calls.append([os.path.basename(p) for p in paths])
            with open(os.path.join(root, "Image", "en", "kh1_first.hed"), "wb") as f:
                f.write(b"patched")
            return 0, "done"
        with mock.patch.object(main, "_kh_run_patcher", fake), \
                mock.patch.object(main, "_process_running", mock.AsyncMock(return_value=False)):
            r = asyncio.run(main._kh_apply(self.game))
            self.assertTrue(r["ok"], r)
            self.assertEqual(calls, [["Better.kh1pcpatch"]])
            r = asyncio.run(main._kh_apply(self.game))  # nothing new
            self.assertEqual(len(calls), 1)
            os.remove(os.path.join(self.root, "Mods", "patches", "Better.kh1pcpatch"))
            r = asyncio.run(main._kh_apply(self.game))
            self.assertIn("verify", r["note"])
        self.assertEqual(main._load_settings()["kh_patches"]["applied"], [])


if __name__ == "__main__":
    unittest.main()
