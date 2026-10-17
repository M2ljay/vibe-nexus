// The experimental (any-game) registry in games.ts: curated games always win,
// experimental ones count only while the switch is on, and managedGames()
// is what update checks and My Mods iterate.
//   tsc src/games.ts --outDir .test-build --module es2020 --target es2020 --skipLibCheck --declaration false
//   node --test tests/experimental.test.mjs
import assert from "node:assert/strict";
import test from "node:test";
import {
  ALL_GAMES,
  SUPPORTED_GAMES,
  getSupportedGame,
  isExperimentalEnabled,
  isExperimentalGame,
  managedGames,
  setExperimentalState,
} from "../.test-build/games.js";

const SZ = {
  appId: 1790600, displayName: "Sparking! Zero", nexusDomain: "dragonballsparkingzero",
  installDirName: "DRAGON BALL Sparking! ZERO", modsSubdir: "SparkingZERO/Content/Paks/~mods",
  moddedSaveWarning: false, processName: "", installMode: "folder",
};

test("experimental games count only while enabled", () => {
  setExperimentalState(false, [SZ]);
  assert.equal(getSupportedGame(SZ.appId), undefined);
  assert.equal(managedGames().length, ALL_GAMES.length);
  setExperimentalState(true, [SZ]);
  assert.equal(isExperimentalEnabled(), true);
  assert.equal(getSupportedGame(SZ.appId)?.nexusDomain, "dragonballsparkingzero");
  assert.equal(isExperimentalGame(getSupportedGame(SZ.appId)), true);
  assert.equal(managedGames().length, ALL_GAMES.length + 1);
});

test("a curated entry always wins over an experimental one", () => {
  const curatedId = Number(Object.keys(SUPPORTED_GAMES)[0]);
  setExperimentalState(true, [{ ...SZ, appId: curatedId, displayName: "impostor" }]);
  assert.notEqual(getSupportedGame(curatedId)?.displayName, "impostor");
  assert.equal(isExperimentalGame(getSupportedGame(curatedId)), false);
  assert.equal(managedGames().length, ALL_GAMES.length);
});

test("state is replaced, not appended", () => {
  setExperimentalState(true, [SZ]);
  setExperimentalState(true, []);
  assert.equal(getSupportedGame(SZ.appId), undefined);
});
