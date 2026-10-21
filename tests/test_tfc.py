"""Batman: Arkham Origins TFC Installer mods."""
import os
import shutil
import sys
import tempfile
import unittest

from test_backend import main

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import experimental_games as eg  # noqa: E402

AG = "Arkham Origins Advanced Graphics/"
FILES = [AG + "Readme.txt", AG + "01 - Core Config/AdvancedGraphicsConfig.bat",
         AG + "01 - Core Config/Config/Default/BmEngine.ini",
         AG + "02 - Visual Assets/Advanced Graphics - Visual Assets 1080p/GameProfile.xml",
         AG + "02 - Visual Assets/Advanced Graphics - Visual Assets 1080p/ObjectDescriptors.descriptor",
         AG + "02 - Visual Assets/Advanced Graphics - Visual Assets 1080p/TexturePack/Texture2D_0.tfc",
         AG + "02 - Visual Assets/Advanced Graphics - Visual Assets 1080p/TexturePack/Batman Arkham Origins.TFCMapping",
         AG + "02 - Visual Assets/Advanced Graphics - Visual Assets 1080p/Game/BmGame/CookedPCConsole/x.upk",
         AG + "02 - Visual Assets/Advanced Graphics - Visual Assets 4K/GameProfile.xml",
         AG + "02 - Visual Assets/Advanced Graphics - Visual Assets 4K/TexturePack/Texture2D_0.tfc"]


class TfcTests(unittest.TestCase):
    def test_roots_and_profile(self):
        self.assertEqual(eg.tfc_mod_roots(FILES), [
            AG + "02 - Visual Assets/Advanced Graphics - Visual Assets 1080p",
            AG + "02 - Visual Assets/Advanced Graphics - Visual Assets 4K"])
        g = {"nexusDomain": "batmanarkhamorigins", "processName": "SinglePlayer/Binaries/Win32/BatmanOrigins.exe"}
        self.assertTrue(eg.apply_tfc_profile(g))
        self.assertEqual(g["framework"]["sourceDomain"], "site")
        self.assertEqual(eg.classify_mod(FILES, g, set(), {}, False, {}), "tool_managed")
        self.assertFalse(eg.apply_tfc_profile({"nexusDomain": "skyrim"}))

    def test_install_asks_then_copies(self):
        root = main._game_dir("Batman Arkham Origins")
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root)
        game = {"appId": 209000, "nexusDomain": "batmanarkhamorigins", "installDirName": "Batman Arkham Origins",
                "processName": "SinglePlayer/Binaries/Win32/BatmanOrigins.exe", "modsSubdir": "Mods"}
        eg.apply_tfc_profile(game)
        main._save_settings({"experimental_games": {"209000": game}})

        def scratch():
            d = tempfile.mkdtemp()
            for f in FILES:
                p = os.path.join(d, *f.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, "w").close()
            return d
        with self.assertRaises(main.NeedsChoice) as cm:
            main._experimental_root_install(scratch(), root, "Mods", game, "batmanarkhamorigins", 1,
                                            {"name": "Advanced Graphics"})
        self.assertEqual(len(cm.exception.options), 2)
        key = main._experimental_root_install(scratch(), root, "Mods", game, "batmanarkhamorigins", 1,
                                              {"name": "Advanced Graphics"}, cm.exception.options[1])
        mod = os.path.join(root, "SinglePlayer", "TFCInstaller", "Mods", "Advanced Graphics")
        self.assertTrue(os.path.isfile(os.path.join(mod, "GameProfile.xml")))
        self.assertTrue(os.path.isfile(os.path.join(mod, "TexturePack", "Texture2D_0.tfc")))
        rec = main._load_settings()["installed"]["batmanarkhamorigins"][key]
        self.assertTrue(rec["tfcMod"])
        self.assertIn(".bat", rec["warning"])
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
