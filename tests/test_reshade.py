"""ReShade for experimental games: setup, shader packs, presets, removal."""
import asyncio
import io
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
import zipfile

from test_backend import main
from test_reloaded_ii import _pe

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))
import reshade_setup as rs  # noqa: E402

PACKS = """[00]
PackageName=Standard effects
Required=1
InstallPath=.\\reshade-shaders\\Shaders
TextureInstallPath=.\\reshade-shaders\\Textures
DownloadUrl=https://x/standard.zip
EffectFiles=DisplayDepth.fx,UIMask.fx
[01]
PackageName=SweetFX
Enabled=0
InstallPath=.\\reshade-shaders\\Shaders\\SweetFX
TextureInstallPath=.\\reshade-shaders\\Textures\\SweetFX
DownloadUrl=https://x/sweetfx.zip
EffectFiles=LumaSharpen.fx,Vibrance.fx
"""


def _zip(files, prefix=b""):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return prefix + buf.getvalue()


class HelperTests(unittest.TestCase):
    def test_setup_url(self):
        html = ('<a href="/downloads/ReShade_Setup_6.3.3.exe">x</a>'
                '<a href="/downloads/ReShade_Setup_6.3.3_Addon.exe">y</a>'
                '<a href="/downloads/ReShade_Setup_6.2.0.exe">z</a>')
        self.assertEqual(rs.setup_url(html), ("6.3.3", "https://reshade.me/downloads/ReShade_Setup_6.3.3.exe"))
        self.assertIsNone(rs.setup_url("nothing"))

    def test_api(self):
        self.assertEqual(rs.api_for(["KERNEL32.dll", "d3d9.dll"]), ("d3d9", "d3d9.dll"))
        self.assertEqual(rs.api_for(["d3d11.dll", "dxgi.dll"]), ("dxgi", "dxgi.dll"))
        self.assertEqual(rs.api_for(["OPENGL32.dll"]), ("opengl", "opengl32.dll"))
        self.assertIsNone(rs.api_for(["vulkan-1.dll"]))

    def test_module_from_setup(self):
        blob = _zip({"ReShade32.dll": b"R32", "ReShade64.dll": b"R64"}, prefix=b"MZ" + b"\0" * 5000)
        self.assertEqual(rs.module_from_setup(blob, True), b"R64")
        self.assertEqual(rs.module_from_setup(blob, False), b"R32")

    def test_packages_and_presets(self):
        pk = rs.packages(PACKS)
        self.assertEqual([p["name"] for p in pk], ["Standard effects", "SweetFX"])
        self.assertEqual(pk[1]["installPath"], "./reshade-shaders/Shaders/SweetFX")
        eff = rs.preset_effects("Techniques=LumaSharpen@LumaSharpen.fx,Vibrance@Vibrance.fx\n[LumaSharpen.fx]\nsharp=1\n")
        self.assertEqual(eff, {"LumaSharpen.fx", "Vibrance.fx"})
        self.assertEqual([p["name"] for p in rs.packages_for(eff, pk, set())], ["Standard effects", "SweetFX"])
        self.assertEqual([p["name"] for p in rs.packages_for(eff, pk, {"lumasharpen.fx", "vibrance.fx"})],
                         ["Standard effects"])
        self.assertEqual(rs.is_preset_archive(["SR2 Preset/MY SR2 PRESET.ini", "SR2 Preset/shot.jpg"]),
                         ["SR2 Preset/MY SR2 PRESET.ini"])
        self.assertEqual(rs.is_preset_archive(["dxgi.dll", "a.ini"]), [])
        self.assertEqual(rs.is_preset_archive(["Mod Files/a.xtbl"]), [])


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.root = main._game_dir("Shade Game")
        shutil.rmtree(self.root, ignore_errors=True)
        os.makedirs(self.root)
        with open(os.path.join(self.root, "Game.exe"), "wb") as f:
            f.write(_pe(["KERNEL32.dll", "d3d9.dll"], is64=False))
        self.cache = tempfile.mkdtemp()
        self.p = unittest.mock.patch.object(main, "RESHADE_CACHE", self.cache)
        self.p.start()
        self.game = {"appId": 5, "nexusDomain": "shadegame", "installDirName": "Shade Game",
                     "processName": "Game.exe", "engine": "generic", "modsSubdir": "mods"}
        main._save_settings({"experimental_games": {"5": self.game}})
        setup = _zip({"ReShade32.dll": b"RESHADE32", "ReShade64.dll": b"RESHADE64"}, prefix=b"MZ" + b"\0" * 600)
        files = {
            "https://reshade.me/": b'<a href="/downloads/ReShade_Setup_6.3.3.exe">',
            "https://reshade.me/downloads/ReShade_Setup_6.3.3.exe": setup,
            rs.PACKAGES_URL: PACKS.encode(),
            "https://x/standard.zip": _zip({"reshade-shaders-slim/Shaders/DisplayDepth.fx": b"fx",
                                            "reshade-shaders-slim/Textures/UIMask.png": b"png"}),
            "https://x/sweetfx.zip": _zip({"SweetFX-master/Shaders/LumaSharpen.fx": b"fx",
                                           "SweetFX-master/Shaders/Vibrance.fx": b"fx"}),
        }
        self.http = unittest.mock.patch.object(main, "_http_get", lambda url, timeout=0: files[url])
        self.http.start()

    def tearDown(self):
        self.p.stop()
        self.http.stop()
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.cache, ignore_errors=True)

    def test_setup_preset_remove(self):
        plugin = main.Plugin()
        run = asyncio.new_event_loop().run_until_complete
        r = run(plugin.install_reshade(5))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["dll"], "d3d9.dll")
        with open(os.path.join(self.root, "d3d9.dll"), "rb") as f:
            self.assertEqual(f.read(), b"RESHADE32")
        self.assertTrue(os.path.isfile(os.path.join(self.root, "reshade-shaders", "Shaders", "DisplayDepth.fx")))
        game = main._experimental_game_for("shadegame")
        self.assertTrue(game["reshadeSetup"])
        scratch = tempfile.mkdtemp()
        os.makedirs(os.path.join(scratch, "Cool Preset"))
        with open(os.path.join(scratch, "Cool Preset", "Cool.ini"), "w") as f:
            f.write("Techniques=LumaSharpen@LumaSharpen.fx\n")
        key = main._experimental_root_install(scratch, self.root, "mods", game, "shadegame", 5,
                                              {"name": "Cool Preset"})
        self.assertTrue(key)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "Cool.ini")))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "reshade-shaders", "Shaders", "SweetFX", "LumaSharpen.fx")))
        with open(os.path.join(self.root, "ReShade.ini")) as f:
            self.assertIn("PresetPath=.\\Cool.ini", f.read())
        rec = main._load_settings()["installed"]["shadegame"][key]
        self.assertIn("SweetFX", rec["warning"])
        r = run(plugin.remove_reshade(5))
        self.assertTrue(r["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "d3d9.dll")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "reshade-shaders")))


if __name__ == "__main__":
    unittest.main()
