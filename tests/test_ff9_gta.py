"""Final Fantasy IX (Memoria), GTA III archives, Forza paths."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import experimental_games as eg  # noqa: E402
import gta_img  # noqa: E402
import memoria  # noqa: E402


class MemoriaTests(unittest.TestCase):
    def test_folders(self):
        self.assertEqual(memoria.mod_folders(["PSXHUD/ModDescription.xml", "PSXHUD/StreamingAssets/x.bundle",
                                              "PSXHUD/Memoria.ini"]), ["PSXHUD"])
        self.assertEqual(memoria.mod_folders(["DKR_Alt/DragonKnightRising/FF9_Data/embeddedasset/text/a.mes"]),
                         ["DKR_Alt/DragonKnightRising"])
        self.assertEqual(memoria.mod_folders(["BlackCat/ModDescription.xml",
                                              "BlackCat/AlternateFantasy/StreamingAssets/Data/x.csv"]), ["BlackCat"])
        feats = memoria.mod_folders([f"Sh1nRa/Features/{n}/StreamingAssets/a.png" for n in ("A", "B")])
        self.assertEqual(feats, ["Sh1nRa/Features/A", "Sh1nRa/Features/B"])
        self.assertEqual(memoria.mod_folders(["StreamingAssets/x.bin"]), [""])
        self.assertEqual(memoria.plan(["StreamingAssets/x.bin"], "Mine"), [("StreamingAssets/x.bin", "Mine/StreamingAssets/x.bin")])

    def test_ini(self):
        text = "[Mod]\n\t; comment\nFolderNames = \"UserMod\", \"Old\"\nPriorities = \n\n[Font]\nEnabled = 0\n"
        out = memoria.set_folder_names(text, ["New", "PSXHUD"], {"New", "PSXHUD", "Old"})
        self.assertIn('FolderNames = "New", "PSXHUD", "UserMod"', out)
        self.assertIn("[Font]", out)
        self.assertIn("FolderNames", memoria.set_folder_names("", ["A"], {"A"}))

    def test_classify(self):
        g = {"nexusDomain": "finalfantasy9", "installDirName": "FINAL FANTASY IX"}
        memoria.apply_ff9_profile(g)
        self.assertEqual(g["toolApply"], "memoria")
        self.assertEqual(eg.classify_mod(["PSXHUD/ModDescription.xml", "PSXHUD/StreamingAssets/a.bundle"],
                                         g, set(), {}, False, {}), "tool_managed")
        self.assertTrue(memoria.patch_ok("V Done"))
        self.assertFalse(memoria.patch_ok("X The patching could only complete 40%"))


class GtaImgTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "models"))
        self.orig = {"gta3": [("a.dff", b"A" * 3000), ("b.txd", b"B" * 100)], "txd": [("b.txd", b"b" * 50)]}
        for base, items in self.orig.items():
            img, entries, sec = b"", [], 0
            for n, data in items:
                pad = (-len(data)) % 2048
                img += data + b"\0" * pad
                size = (len(data) + pad) // 2048
                entries.append([sec, size, n])
                sec += size
            with open(os.path.join(self.root, "models", base + ".img"), "wb") as f:
                f.write(img)
            with open(os.path.join(self.root, "models", base + ".dir"), "wb") as f:
                f.write(gta_img.build_dir(entries))

    def tearDown(self):
        shutil.rmtree(self.root)

    def entry(self, base, name):
        with open(os.path.join(self.root, "models", base + ".dir"), "rb") as f:
            for o, s, n in gta_img.parse_dir(f.read()):
                if n == name:
                    with open(os.path.join(self.root, "models", base + ".img"), "rb") as g:
                        g.seek(o * 2048)
                        return g.read(s * 2048).rstrip(b"\0")
        return None

    def test_rebuild_and_restore(self):
        self.assertEqual(gta_img.names(self.root), {"a.dff": "models/gta3.img", "b.txd": "models/gta3.img"})
        mod = os.path.join(self.root, "mod_b.txd")
        with open(mod, "wb") as f:
            f.write(b"NEW" * 10)
        new = os.path.join(self.root, "c.dff")
        with open(new, "wb") as f:
            f.write(b"C")
        size0 = os.path.getsize(os.path.join(self.root, "models", "gta3.img"))
        st = gta_img.rebuild(self.root, {}, [("b.txd", mod), ("c.dff", new)])
        self.assertEqual(self.entry("gta3", "b.txd"), b"NEW" * 10)
        self.assertEqual(self.entry("txd", "b.txd"), b"NEW" * 10)  # both archives
        self.assertEqual(self.entry("gta3", "c.dff"), b"C")
        self.assertEqual(self.entry("gta3", "a.dff"), b"A" * 3000)
        st = gta_img.rebuild(self.root, st, [])  # mod removed
        self.assertEqual(self.entry("gta3", "b.txd"), b"B" * 100)
        self.assertIsNone(self.entry("gta3", "c.dff"))
        self.assertEqual(os.path.getsize(os.path.join(self.root, "models", "gta3.img")), size0)

    def test_planner_routes_into_archive(self):
        idx = eg.index_game_files(self.root)
        self.assertEqual(idx["a.dff"], ["models/gta3.img::a.dff"])
        g = {"nexusDomain": "gta3", "installDirName": "GTA", "processName": "gta3.exe"}
        gta_img.apply_gta_profile(g)
        files = ["[III] Upscale/a.dff", "[III] Upscale/readme.txt"]
        p = eg.plan_root_install(files, {"models", "gta3.exe"}, eg.index_game_dirs(self.root), "Mods", "",
                                 idx, "", "GTA")
        self.assertEqual(p, [("[III] Upscale/a.dff", "models/gta3.img::a.dff")])
        self.assertEqual(eg.classify_mod(files, g, {"models"}, eg.index_game_dirs(self.root), False, idx),
                         "game_folder")
        cs = eg.plan_root_install(["health100.cs", "health100.txt"], {"models"}, {}, "Mods", "", idx, "", "")
        self.assertEqual(cs, [("health100.cs", "cleo/health100.cs")])
        self.assertEqual(g["framework"]["with"], ["cleo3"])


class ForzaTests(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(list(eg.alias_paths(["Content/mediapc/Audio/x.xml", "mediapc/Camera/y.ini"],
                                             "forzahorizon6")),
                         ["media/Audio/x.xml", "media/Camera/y.ini"])
        g = {"nexusDomain": "forzahorizon6", "engine": "unknown", "processName": "forzahorizon6.exe"}
        self.assertEqual(eg.classify_mod(["mediapc/Camera/CameraSettings.ini"], g, {"media"},
                                         {"media": ["media"]}, False, {}), "game_folder")


if __name__ == "__main__":
    unittest.main()
