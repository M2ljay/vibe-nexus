"""Juiced Patch Step 1 against the real release zip, when it is on disk."""
import asyncio
import json
import os
import shutil
import sys
import unittest
import unittest.mock

from test_backend import main
from test_reloaded_ii import _pe

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import experimental_games as eg  # noqa: E402

ZIP = os.environ.get("SR2_JUICED_ZIP", "")


@unittest.skipUnless(ZIP and os.path.isfile(ZIP), "real SR2_JUICED.zip not given")
class RealJuiced(unittest.TestCase):
    def test_setup(self):
        root = main._game_dir("Saints Row 2")
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root)
        with open(os.path.join(root, "SR2_pc.exe"), "wb") as f:
            f.write(_pe(["KERNEL32.dll"], is64=False))
        game = {"appId": 9480, "nexusDomain": "saintsrow2", "installDirName": "Saints Row 2",
                "processName": "SR2_pc.exe"}
        eg.apply_sr2_profile(game, main._sr2_framework())
        main._save_settings({"experimental_games": {"9480": game}})
        rel = [{"tag_name": "v9.3.1", "assets": [{"name": "SR2_JUICED.zip",
                                                  "browser_download_url": "zip"}]}]

        async def fetch(url, timeout=300):
            return open(ZIP, "rb").read() if url == "zip" else json.dumps(rel).encode()
        with unittest.mock.patch.object(main, "_fetch_bytes", fetch):
            r = asyncio.new_event_loop().run_until_complete(main._github_loader_setup("saintsrow2"))
        self.assertTrue(r["ok"], r)
        names = {n.lower() for n in os.listdir(root)}
        self.assertIn("dfengine.dll", names)
        self.assertIn("juiced.ini", names)
        self.assertIn("mods", names)
        print(r, sorted(os.listdir(root)))
        shutil.rmtree(root, ignore_errors=True)
