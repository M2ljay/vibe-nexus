"""Bringing a game's window to the front after launch, for games that ask."""
import asyncio
import unittest
import unittest.mock

from test_backend import main


class FocusTests(unittest.TestCase):
    def test_focuses_at_each_delay_once(self):
        main._FOCUS_SEEN.clear()
        main._save_settings({"experimental_games": {"1": {
            "nexusDomain": "g", "processName": "bin/Game.exe", "focusAfterLaunch": True}}})
        clock = [100.0]
        focused = []

        async def fake_sleep(_s):
            clock[0] += 3
            if clock[0] > 140:
                raise asyncio.CancelledError
        with unittest.mock.patch.object(main, "_running_pids", lambda: {"game.exe": [42]}), \
                unittest.mock.patch.object(main, "_main_window", lambda pid: f"win{pid}"), \
                unittest.mock.patch.object(main, "_bring_to_front", lambda h: focused.append(h) or True), \
                unittest.mock.patch.object(main.time, "monotonic", lambda: clock[0]), \
                unittest.mock.patch.object(main.asyncio, "sleep", fake_sleep):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.new_event_loop().run_until_complete(main._watch_focus())
        self.assertEqual(focused, ["win42", "win42"])  # at 6s and 18s, not again

    def test_off_by_default(self):
        main._save_settings({"experimental_games": {"1": {"appId": 1, "nexusDomain": "g", "processName": "Game.exe"}}})
        p = main.Plugin()
        r = asyncio.new_event_loop().run_until_complete(p.set_experimental_focus(1, True))
        self.assertTrue(r["game"]["focusAfterLaunch"])


if __name__ == "__main__":
    unittest.main()
