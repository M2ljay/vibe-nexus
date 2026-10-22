// Experimental "any game" support (this fork). Panel rows for games without a
// curated entry: an opt-in switch, a one-press setup that matches the game to
// its Nexus Mods domain and guesses its mods folder, and a way to undo it.
// The matching and folder guessing run in the backend
// (py_modules/experimental_games.py); this file only drives them.
import {
  ButtonItem,
  Field,
  ModalRoot,
  PanelSectionRow,
  TextField,
  ToggleField,
  showModal,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";

import {
  CoverageRow,
  ExperimentalCandidate,
  GotrOption,
  getGotrOptions,
  setGotrAll,
  setGotrOption,
  applyExperimentalTool,
  checkExperimentalCoverage,
  experimentalFolderOptions,
  setExperimentalFramework,
  setExperimentalModsFolder,
  setExperimentalFocus,
  setExperimentalDomain,
  installReshade,
  removeReshade,
  findExperimentalGame,
  getExperimentalState,
  removeExperimentalFramework,
  removeExperimentalGame,
  saveExperimentalGame,
  setExperimentalEnabled,
} from "./api";
import {
  SupportedGame,
  isExperimentalEnabled,
  isExperimentalGame,
  isTrackedLoader,
  managedGames,
  setExperimentalState,
  toolName,
} from "./games";
import { notifyGameStateChanged } from "./state";

/** Toast for the backend's automatic re-apply after an install/uninstall. */
export function toolAppliedToast(
  _domain: string,
  result: {
    ok: boolean;
    count?: number;
    error?: string;
    restart?: boolean;
    tool?: string;
    fetched?: string[];
    missing?: string[];
    note?: string;
  }
): void {
  const tool = result.tool ?? "Overstrike";
  const reloaded = tool === "Reloaded-II" || tool === "XV2 Mods Installer";
  const what = reloaded ? "mod" : "mod file";
  const extra = [
    result.fetched?.length
      ? `Fetched ${result.fetched.length} required librar${result.fetched.length === 1 ? "y" : "ies"}.`
      : "",
    result.missing?.length
      ? `Still needed (not on Reloaded's feed - install from Nexus or GameBanana): ${result.missing.join(", ")}`
      : "",
    result.note ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  toaster.toast(
    result.ok
      ? {
          title: result.restart
            ? "Mods applied - restart the game to see them"
            : `${tool} ${reloaded ? "updated your mod list" : "applied your mods"}`,
          body:
            (result.restart
              ? "The game was already running and loaded the old files."
              : result.count
                ? `${result.count} ${what}${result.count === 1 ? "" : "s"} active - you can play now`
                : "No mods installed - the game is back to vanilla") +
            (extra ? ` ${extra}` : ""),
        }
      : { title: `${tool} couldn't apply mods`, body: result.error ?? "" }
  );
}

/** Shown when the automatic re-apply starts, so nobody launches mid-way. */
export function toolApplyingToast(domain?: string): void {
  const game = managedGames().find((g) => g.nexusDomain === domain);
  toaster.toast({
    title: `Applying mods with ${toolName(game?.toolApply)}…`,
    body: "Wait for the next message before starting the game",
  });
}

/** Pull the saved experimental state from the backend into games.ts. */
export async function loadExperimentalState(): Promise<void> {
  try {
    const r = await getExperimentalState();
    if (r.ok) {
      setExperimentalState(r.enabled, r.games ?? []);
      notifyGameStateChanged();
    }
  } catch (e) {
    console.warn("[Nexus Mods] experimental state not loaded", e);
  }
}

function PickGameModal({
  steamName,
  candidates,
  onPick,
  closeModal,
}: {
  steamName: string;
  candidates: ExperimentalCandidate[];
  onPick: (c: ExperimentalCandidate) => void;
  closeModal?: () => void;
}) {
  return (
    <ModalRoot closeModal={closeModal}>
      <h3 style={{ marginTop: 0 }}>Which Nexus Mods game is {steamName}?</h3>
      <div style={{ fontSize: "13px", opacity: 0.9, marginBottom: "8px" }}>
        The names did not match exactly. Pick the right one, or back out if
        none of these is the game.
      </div>
      {candidates.map((c) => (
        <ButtonItem
          key={c.domain}
          layout="below"
          description={
            c.mods ? `${c.mods.toLocaleString()} mods · ${c.domain}` : c.domain
          }
          onClick={() => {
            closeModal?.();
            onPick(c);
          }}
        >
          {c.name}
        </ButtonItem>
      ))}
    </ModalRoot>
  );
}

const VERDICT_TEXT: Record<CoverageRow["verdict"], string> = {
  mods_folder: "Works · mods folder",
  game_folder: "Works · game folder",
  wizard: "Works · installer wizard",
  tool_managed: "Works · applied by the mod tool",
  loader: "Step 1 loader",
  program: "Desktop program - can't install",
  no_target: "No clear place - likely won't load",
  ue_config: "Works · settings tweak (Engine.ini)",
  save_file: "Works · save file (yours are backed up first)",
  cheat_table: "Cheat Engine table - used from the desktop",
  reshade_preset: "ReShade preset - press Set up ReShade first",
  reshade_ready: "Works · ReShade preset",
  texmod: "TexMod package - needs TexMod/uMod, not installed",
  old_version: "Made for an older version of the game",
  docs_only: "Only instructions - nothing to install",
  unknown: "Can't check (no file list)",
};

function CoverageModal({
  gameName,
  result,
  closeModal,
  onDeep,
}: {
  gameName: string;
  result: { working?: number; checked?: number; total?: number; rows?: CoverageRow[] };
  closeModal?: () => void;
  onDeep?: () => void;
}) {
  const rows = result.rows ?? [];
  const problems = rows.filter((r) =>
    ["program", "no_target", "unknown", "cheat_table", "reshade_preset", "texmod", "old_version"].includes(r.verdict)
  );
  return (
    <ModalRoot closeModal={closeModal}>
      <h3 style={{ marginTop: 0 }}>
        {gameName}: {result.working ?? 0} of {result.checked ?? 0} checked mods should work
      </h3>
      <div style={{ fontSize: "13px", opacity: 0.85, marginBottom: "8px" }}>
        The {result.total ?? 0} most-endorsed mods, judged from the files Nexus
        Mods lists for them - nothing was downloaded. A prediction, not a promise.
      </div>
      {(result.rows ?? []).some((r) => r.verdict === "unknown") && onDeep && (
        <ButtonItem
          layout="below"
          description="Downloads the mods Nexus lists no files for (up to 4 GB in total), looks inside, and deletes them again. Nothing is installed."
          onClick={() => {
            closeModal?.();
            onDeep();
          }}
        >
          Check the unlisted ones by downloading them
        </ButtonItem>
      )}
      {problems.length === 0 ? (
        <div style={{ fontSize: "13px" }}>No problem mods found.</div>
      ) : (
        problems.map((r) => (
          <Field key={r.modId} label={r.name} childrenLayout="below">
            {VERDICT_TEXT[r.verdict]}
          </Field>
        ))
      )}
    </ModalRoot>
  );
}

export function ExperimentalToggle() {
  const [enabled, setEnabled] = useState(isExperimentalEnabled());
  return (
    <ToggleField
      label="Experimental: any game"
      description="Offer generic mod support for games the plugin has no rules for. Mods go into a folder guessed from the game's files."
      checked={enabled}
      onChange={async (v: boolean) => {
        setEnabled(v);
        const r = await setExperimentalEnabled(v);
        if (r.ok) {
          setExperimentalState(r.enabled, r.games ?? []);
          setEnabled(r.enabled);
          notifyGameStateChanged();
        }
      }}
    />
  );
}

/** Rows under "Current Game" when the game has no curated support. */
export function ExperimentalUnsupportedRows({
  appId,
  name,
}: {
  appId?: number;
  name: string;
}) {
  const [busy, setBusy] = useState(false);
  const enabled = isExperimentalEnabled();

  const save = async (c: ExperimentalCandidate) => {
    if (appId === undefined) return;
    const r = await saveExperimentalGame(appId, name, c.domain, c.name);
    if (!r.ok || !r.game) {
      toaster.toast({ title: "Setup failed", body: r.error ?? "Unknown error" });
      return;
    }
    await loadExperimentalState();
    toaster.toast({
      title: `${name}: experimental support on`,
      body: `Nexus Mods game: ${c.name}. Mods go in ${r.game.modsSubdir}.`,
    });
  };

  const setup = async () => {
    if (appId === undefined || busy) return;
    setBusy(true);
    try {
      const r = await findExperimentalGame(appId, name);
      if (!r.ok) {
        toaster.toast({ title: "Setup failed", body: r.error ?? "Unknown error" });
        return;
      }
      if (r.inspection?.engine === "missing") {
        toaster.toast({
          title: `${name} isn't installed here`,
          body: r.inspection.note,
        });
        return;
      }
      if (r.exact) {
        await save(r.exact);
        return;
      }
      const candidates = r.candidates ?? [];
      if (candidates.length === 0) {
        toaster.toast({
          title: "No Nexus Mods page found",
          body: `Nothing on Nexus Mods matched "${r.name || name}".`,
        });
        return;
      }
      showModal(
        <PickGameModal
          steamName={name}
          candidates={candidates}
          onPick={(c) => void save(c)}
        />
      );
    } finally {
      setBusy(false);
    }
  };

  if (!enabled) {
    return (
      <PanelSectionRow>
        <ExperimentalToggle />
      </PanelSectionRow>
    );
  }
  return (
    <>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy || appId === undefined}
          description="Experimental: matches this game on Nexus Mods and guesses where its mods go."
          onClick={setup}
        >
          {busy ? "Looking it up…" : `Set up mods for ${name}`}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ExperimentalToggle />
      </PanelSectionRow>
    </>
  );
}

/** Extra rows under "Current Game" for a game set up experimentally. */
/** Gentlemen of the Row's optional mods, one switch each. Turning one on
 * turns off any that change the same files. */
function GotrOptionsModal({ closeModal }: { closeModal?: () => void }) {
  const [options, setOptions] = useState<GotrOption[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void getGotrOptions().then((r) =>
      r.ok ? setOptions(r.options ?? []) : setError(r.error ?? "Couldn't read the options")
    );
  }, []);
  return (
    <ModalRoot onCancel={closeModal} onEscKeypress={closeModal}>
      <Field label="Gentlemen of the Row: optional mods" bottomSeparator="none">
        Switching one on switches off any that change the same files. Changes
        apply the next time the game starts.
      </Field>
      {error && <Field label={error} />}
      {!options && !error && <Field label="Loading…" />}
      {options && (
        <>
          {[false, true].map((on) => (
            <ButtonItem
              key={String(on)}
              layout="below"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const r = await setGotrAll(on);
                  if (r.ok) setOptions(r.options ?? options);
                  else toaster.toast({ title: "Couldn't switch them", body: r.error ?? "" });
                } finally {
                  setBusy(false);
                }
              }}
            >
              {on ? "Switch all on (skipping overlaps)" : "Switch all off"}
            </ButtonItem>
          ))}
        </>
      )}
      {options?.map((o) => (
        <ToggleField
          key={o.name}
          label={o.name}
          description={
            o.clashesWith.length
              ? `${o.files} files · overlaps with ${o.clashesWith.join(", ")}`
              : `${o.files} files`
          }
          checked={o.enabled}
          disabled={busy}
          onChange={async (on: boolean) => {
            setBusy(true);
            try {
              const r = await setGotrOption(o.name, on);
              if (!r.ok) {
                toaster.toast({ title: "Couldn't switch it", body: r.error ?? "" });
                return;
              }
              setOptions(r.options ?? options);
              if (r.turnedOff?.length) {
                toaster.toast({
                  title: `Switched off ${r.turnedOff.length} overlapping mod${r.turnedOff.length === 1 ? "" : "s"}`,
                  body: r.turnedOff.join(", "),
                });
              }
              if (r.restart) {
                toaster.toast({
                  title: "Restart the game to see it",
                  body: "The game reads its mod list when it starts",
                });
              }
            } finally {
              setBusy(false);
            }
          }}
        />
      ))}
    </ModalRoot>
  );
}

function FolderModal({
  game,
  current,
  options,
  closeModal,
}: {
  game: SupportedGame;
  current: string;
  options: string[];
  closeModal?: () => void;
}) {
  const [custom, setCustom] = useState(current);
  const pick = async (subdir: string) => {
    const r = await setExperimentalModsFolder(game.appId, subdir);
    if (!r.ok) {
      toaster.toast({ title: "Mods folder not changed", body: r.error ?? "" });
      return;
    }
    closeModal?.();
    toaster.toast({ title: "Mods folder changed", body: subdir });
    await loadExperimentalState();
  };
  return (
    <ModalRoot closeModal={closeModal}>
      <h3 style={{ marginTop: 0 }}>Where do {game.displayName} mods go?</h3>
      <div style={{ fontSize: "13px", opacity: 0.85, marginBottom: "8px" }}>
        Folders inside the game folder. Each mod gets its own folder in the one
        you pick. Check a popular mod's instructions if you're unsure.
      </div>
      {options.map((o) => (
        <ButtonItem key={o} layout="below" onClick={() => void pick(o)}>
          {o === current ? `${o} (current)` : o}
        </ButtonItem>
      ))}
      <TextField
        label="Or type a folder (relative to the game folder)"
        value={custom}
        onChange={(e: any) => setCustom(e.target.value)}
      />
      <ButtonItem layout="below" onClick={() => void pick(custom)}>
        Use this folder
      </ButtonItem>
    </ModalRoot>
  );
}

export function ExperimentalGameRows({ game }: { game: SupportedGame }) {
  const [busy, setBusy] = useState(false);
  if (!isExperimentalGame(game)) return null;
  return (
    <>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          label="Mods folder"
          disabled={busy || game.toolApply !== undefined || game.installMode === "dataDir"}
          description={game.modsSubdir}
          onClick={async () => {
            const r = await experimentalFolderOptions(game.appId);
            if (!r.ok) {
              toaster.toast({ title: "Couldn't list folders", body: r.error ?? "" });
              return;
            }
            showModal(
              <FolderModal
                game={game}
                current={r.current ?? game.modsSubdir}
                options={r.options ?? []}
              />
            );
          }}
        >
          Change
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy}
          description={
            game.framework
              ? `Step 1 (${game.framework.name}) was guessed from what the top mods require. Remove it if this game doesn't need it - files it installed are taken out.`
              : "Looks again at what the game's top mods require, in case they need a loader installed first."
          }
          onClick={async () => {
            setBusy(true);
            try {
              const r = await setExperimentalFramework(
                game.appId,
                game.framework ? "none" : "redetect"
              );
              toaster.toast(
                r.ok
                  ? {
                      title: game.framework ? "Step 1 removed" : "Step 1 checked",
                      body: r.game?.framework
                        ? `Needs ${r.game.framework.name}`
                        : "No loader needed",
                    }
                  : { title: "Couldn't change Step 1", body: r.error ?? "" }
              );
              await loadExperimentalState();
            } finally {
              setBusy(false);
            }
          }}
        >
          {game.framework ? "This game doesn't need Step 1" : "Look for a Step 1 loader"}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy}
          description="Checks the 50 most popular mods for this game, without downloading them, and lists the ones the plugin can't place where the game loads them."
          onClick={async () => {
            const run = async (deep: boolean) => {
              setBusy(true);
              try {
                if (deep) {
                  toaster.toast({
                    title: "Downloading unlisted mods to check them…",
                    body: "This can take a few minutes",
                  });
                }
                const r = await checkExperimentalCoverage(game.appId, 50, deep);
                if (!r.ok) {
                  toaster.toast({ title: "Check failed", body: r.error ?? "" });
                  return;
                }
                showModal(
                  <CoverageModal
                    gameName={game.displayName}
                    result={r}
                    onDeep={deep ? undefined : () => void run(true)}
                  />
                );
              } finally {
                setBusy(false);
              }
            };
            await run(false);
          }}
        >
          {busy ? "Checking…" : "Check mod compatibility"}
        </ButtonItem>
      </PanelSectionRow>
      {game.toolApply !== undefined && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={busy}
            description={
              game.toolApply === "reloaded"
                ? "Updates Reloaded-II's mod list for this game from what is installed here, and fetches libraries the mods need. Happens by itself after each change; use this if that failed."
                : game.toolApply === "doommodloader"
                  ? "Runs DOOMModLoader over the zips in Mods. Happens by itself after each change; use this after a game update or if that failed. Close the game first."
                  : game.toolApply === "khpatch"
                  ? "Applies new .kh1pcpatch / .kh2pcpatch / .compcpatch / .bbspcpatch mods with KHPCPatchManager. Happens by itself after each install; after removing a patch, verify the game's files in Steam and press this to put the rest back. Close the game first."
                  : game.toolApply === "tfcinstaller"
                  ? "Opens TFC Installer when the set of installed TFC mods changed: tick the mods there and press Install. Close the game first."
                  : game.toolApply === "xv2ins"
                  ? "Installs new .x2m mods with XV2 Mods Installer, and opens its window on the desktop for any you removed. Happens by itself after each change; use this if that failed. Close the game first."
                  : "Runs Overstrike now with every installed mod. Happens by itself after each install or uninstall; use this after a game update or if that failed. Close the game first."
            }
            onClick={async () => {
              setBusy(true);
              try {
                toolAppliedToast(game.nexusDomain, await applyExperimentalTool(game.appId));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Applying…" : `Apply mods with ${toolName(game.toolApply)}`}
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy}
          description={
            game.reshadeSetup
              ? "Takes ReShade, its effects and its settings out of the game folder. Presets you installed stay until you uninstall them."
              : "Downloads ReShade from reshade.me into the game folder, so ReShade presets from Nexus install with the effects they use. Press Home in game for its menu. Online games with anti-cheat may object to it."
          }
          onClick={async () => {
            setBusy(true);
            try {
              const r = game.reshadeSetup
                ? await removeReshade(game.appId)
                : await installReshade(game.appId);
              toaster.toast(
                r.ok
                  ? {
                      title: game.reshadeSetup ? "ReShade removed" : "ReShade set up",
                      body: game.reshadeSetup
                        ? "Your game is back to how it looked"
                        : "Install ReShade presets for this game now. Press Home in game for its menu.",
                    }
                  : { title: "ReShade didn't work", body: r.error ?? "" }
              );
              await loadExperimentalState();
            } finally {
              setBusy(false);
            }
          }}
        >
          {game.reshadeSetup ? "Remove ReShade" : "Set up ReShade"}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Bring to front after launch"
          description="For games that sit on a black or frozen screen in gaming mode because Steam keeps the focus. The plugin focuses the game's window a few seconds after it starts."
          checked={!!game.focusAfterLaunch}
          onChange={async (on: boolean) => {
            const r = await setExperimentalFocus(game.appId, on);
            if (r.ok) await loadExperimentalState();
          }}
        />
      </PanelSectionRow>
      {(game.domainChoices?.length ?? 0) > 1 && (
        <PanelSectionRow>
          <Field
            label="Mod this game as"
            description="This install holds several games with their own Nexus pages. Pick which one Browse and installs use; each keeps its own mods."
            childrenLayout="below"
          >
            {game.domainChoices!.map((c) => (
              <ButtonItem
                key={c.domain}
                layout="below"
                disabled={busy || c.domain === game.nexusDomain}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const r = await setExperimentalDomain(game.appId, c.domain);
                    if (!r.ok) toaster.toast({ title: "Nexus Mods", body: r.error ?? "Couldn't switch" });
                    await loadExperimentalState();
                    notifyGameStateChanged();
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {c.domain === game.nexusDomain ? `✓ ${c.name}` : c.name}
              </ButtonItem>
            ))}
          </Field>
        </PanelSectionRow>
      )}
      {game.nexusDomain === "saintsrow2" && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description="Switch Gentlemen of the Row's optional mods on and off. Overlapping ones switch each other off."
            onClick={() => showModal(<GotrOptionsModal />)}
          >
            GotR optional mods
          </ButtonItem>
        </PanelSectionRow>
      )}
      {game.framework && isTrackedLoader(game.framework.installKind) && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={busy}
            description={`Deletes the files ${game.framework.name} added and puts back any game file it replaced.`}
            onClick={async () => {
              setBusy(true);
              try {
                const r = await removeExperimentalFramework(game.appId);
                toaster.toast({
                  title: r.ok
                    ? `${game.framework?.name} removed`
                    : "Nothing to remove",
                  body: r.ok ? `${r.removed ?? 0} files deleted` : r.error ?? "",
                });
                notifyGameStateChanged();
              } finally {
                setBusy(false);
              }
            }}
          >
            Remove {game.framework.name}
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy}
          description="Stops treating this game as set up. Installed mods and loaders stay where they are; remove them first if you want them gone."
          onClick={async () => {
            setBusy(true);
            try {
              await removeExperimentalGame(game.appId);
              await loadExperimentalState();
            } finally {
              setBusy(false);
            }
          }}
        >
          Undo experimental setup
        </ButtonItem>
      </PanelSectionRow>
    </>
  );
}
