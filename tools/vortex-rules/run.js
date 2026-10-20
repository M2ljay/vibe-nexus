// Load each Vortex game extension against a mocked Vortex API and record
// what it tells Vortex: where mods go, the Steam app id, the mod types and
// what its installers do with typical mod file layouts.
// Usage: node run.js <bundled-dir> <out.json>
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const GAME = 'C:\\GAME';
const bundleDir = process.argv[2];
const outFile = process.argv[3];

function anything(name = 'x') {
  // A value that tolerates any use: property access, calls, awaits.
  const fn = function () { return anything(name + '()'); };
  return new Proxy(fn, {
    get(t, p) {
      if (p === 'then') return undefined; // not a thenable
      if (p === Symbol.toPrimitive) return () => '';
      if (p === 'toString' || p === 'valueOf') return () => '';
      if (p === Symbol.iterator) return function* () {};
      if (p === 'length') return 0;
      return anything(name + '.' + String(p));
    },
    apply() { return anything(name + '()'); },
    construct() { return anything('new ' + name); },
  });
}

function realPath() {
  const p = Object.assign({}, path.win32);
  p.join = (...a) => path.win32.join(...a.map(x => (typeof x === 'string' ? x : '')));
  p.posix = path.posix; p.win32 = path.win32;
  return p;
}

function makeRequire() {
  const bluebird = {
    resolve: (v) => Promise.resolve(v), reject: (e) => Promise.reject(e),
    all: (a) => Promise.all(a), map: (a, f) => Promise.all((a || []).map(f)),
    each: async (a, f) => { for (const x of a || []) await f(x); return a; },
    mapSeries: async (a, f) => { const r = []; for (const x of a || []) r.push(await f(x)); return r; },
    reduce: async (a, f, init) => { let acc = init; for (const x of a || []) acc = await f(acc, x); return acc; },
    filter: async (a, f) => (a || []).filter(f), delay: () => Promise.resolve(),
    try: (f) => { try { return Promise.resolve(f()); } catch (e) { return Promise.reject(e); } },
    method: (f) => (...a) => Promise.resolve().then(() => f(...a)),
    promisify: (f) => () => Promise.resolve(),
    any: (a) => Promise.any(a),
  };
  const P = function (exec) { return new Promise(exec); };
  Object.assign(P, bluebird);
  const vortexApi = {
    util: anything('util'), fs: anything('fs'), log: () => {}, selectors: anything('selectors'),
    actions: anything('actions'), types: {}, Icon: anything('Icon'),
  };
  vortexApi.util.GameStoreHelper = anything('GameStoreHelper');
  return function (name) {
    if (name === 'path') return realPath();
    if (name === 'bluebird') return P;
    if (name === 'vortex-api') return vortexApi;
    if (name === 'util' || name === 'url') return require(name);
    return anything(name);
  };
}

const COMMON_EXTS = ['.pak', '.dll', '.esp', '.esm', '.lua', '.json', '.xml', '.txt', '.ini', '.asi',
  '.ba2', '.bsa', '.utoc', '.ucas', '.zip', '.cfg', '.js', '.png', '.dds', '.wem', '.bnk', '.ts4script',
  '.package', '.vpk', '.pck', '.rpf', '.mod', '.scs', '.archive', '.reds', '.yaml', '.toml', '.cs'];

function layouts() {
  const out = [];
  for (const e of COMMON_EXTS) {
    out.push({ name: `root${e}`, files: [`file${e}`] });
    out.push({ name: `folder${e}`, files: ['MyMod' + path.sep, `MyMod${path.sep}file${e}`] });
  }
  out.push({ name: 'bepinex', files: ['BepInEx' + path.sep, `BepInEx${path.sep}plugins${path.sep}`, `BepInEx${path.sep}plugins${path.sep}x.dll`] });
  out.push({ name: 'plugins-dir', files: ['plugins' + path.sep, `plugins${path.sep}x.dll`] });
  out.push({ name: 'mods-dir', files: ['Mods' + path.sep, `Mods${path.sep}x.dll`] });
  out.push({ name: 'data-dir', files: ['Data' + path.sep, `Data${path.sep}x.esp`] });
  out.push({ name: 'content-paks', files: [`Content${path.sep}Paks${path.sep}~mods${path.sep}x.pak`] });
  return out;
}

async function withTimeout(p, ms) {
  let t;
  const timeout = new Promise((_, rej) => { t = setTimeout(() => rej(new Error('timeout')), ms); });
  try { return await Promise.race([Promise.resolve(p), timeout]); } finally { clearTimeout(t); }
}

function plain(v, depth = 0) {
  if (v === null || v === undefined) return v;
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return v;
  if (typeof v === 'function') return undefined;
  if (depth > 4) return undefined;
  if (Array.isArray(v)) return v.map(x => plain(x, depth + 1)).filter(x => x !== undefined);
  if (typeof v === 'object') {
    const o = {};
    for (const k of Object.keys(v)) { const x = plain(v[k], depth + 1); if (x !== undefined) o[k] = x; }
    return o;
  }
  return undefined;
}

async function extract(file) {
  const games = [], modTypes = [], installers = [];
  const context = new Proxy({
    registerGame: (g) => games.push(g),
    registerModType: (id, prio, isSupported, getPath, test, opts) => modTypes.push({ id, prio, isSupported, getPath, test, opts }),
    registerInstaller: (id, prio, testSupported, install) => installers.push({ id, prio, testSupported, install }),
    requireExtension: () => {},
    api: anything('api'),
    once: (f) => {},
    optional: anything('optional'),
  }, { get: (t, p) => (p in t ? t[p] : (() => anything('ctx.' + String(p)))) });
  const code = fs.readFileSync(file, 'utf8');
  const module = { exports: {} };
  const sandbox = { module, exports: module.exports, require: makeRequire(), console: { log() {}, warn() {}, error() {} },
    process: { platform: 'win32', env: {} }, setTimeout, clearTimeout, Promise, Buffer, __dirname: 'C:\\ext', __filename: 'C:\\ext\\index.js' };
  vm.runInNewContext(code, sandbox, { timeout: 2000 });
  const main = module.exports.default || module.exports;
  if (typeof main === 'function') main(context);
  const result = [];
  for (const g of games) {
    const r = { id: g.id, name: g.name, mergeMods: plain(g.mergeMods), executable: undefined,
      requiredFiles: plain(g.requiredFiles), details: plain(g.details), environment: plain(g.environment),
      supportedTools: plain((g.supportedTools || []).map(t => ({ id: t.id, name: t.name, executable: typeof t.executable === 'function' ? safe(() => t.executable()) : t.executable, relative: t.relative }))) };
    r.executable = typeof g.executable === 'function' ? safe(() => g.executable()) : g.executable;
    try { r.modPath = await withTimeout(g.queryModPath(GAME), 1000); } catch (e) { r.modPathError = String(e.message || e); }
    if (typeof r.modPath !== 'string') { r.modPathRaw = typeof r.modPath; delete r.modPath; }
    r.modTypes = [];
    for (const mt of modTypes) {
      let p; try { p = await withTimeout(mt.getPath({ id: g.id }), 1000); } catch (e) { p = undefined; }
      r.modTypes.push({ id: mt.id, prio: mt.prio, path: typeof p === 'string' ? p : undefined, name: plain(mt.opts && mt.opts.name) });
    }
    r.installers = [];
    for (const inst of installers) {
      const results = {};
      for (const L of layouts()) {
        try {
          const sup = await withTimeout(inst.testSupported(L.files, g.id), 500);
          if (!sup || !sup.supported) continue;
          const out = await withTimeout(inst.install(L.files, 'C:\\STAGING', g.id, () => {}, undefined, undefined, undefined), 1000);
          const ins = (out && out.instructions) || [];
          results[L.name] = ins.filter(i => i && (i.type === 'copy' || i.type === 'setmodtype')).map(i => ({ type: i.type, source: i.source, destination: i.destination, value: i.value }));
        } catch (e) { /* installer needs real state */ }
      }
      r.installers.push({ id: inst.id, prio: inst.prio, results });
    }
    result.push(r);
  }
  return result;
}

function safe(f) { try { const v = f(); return typeof v === 'string' ? v : undefined; } catch (e) { return undefined; } }

(async () => {
  const out = {};
  for (const f of fs.readdirSync(bundleDir).filter(x => x.endsWith('.js')).sort()) {
    try {
      const games = await withTimeout(extract(path.join(bundleDir, f)), 15000);
      out[f.replace(/\.js$/, '')] = games;
    } catch (e) {
      out[f.replace(/\.js$/, '')] = { error: String(e && e.message || e).slice(0, 200) };
    }
  }
  fs.writeFileSync(outFile, JSON.stringify(out, null, 1));
  process.exit(0);
})();
