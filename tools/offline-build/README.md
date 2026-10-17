# Offline build

Builds `dist/index.js` with esbuild alone, for machines that cannot reach the
npm registry. Decky's own globals stand in for the externals the rollup build
leaves out (`SP_REACT`, `SP_JSX`, `SP_REACTDOM`, `DFL`); `@decky/api` 1.1.3 and
the 17 react-icons this plugin uses are vendored in `shims/` (taken from a
rollup-built bundle). Behaviour matches `pnpm build`; `pnpm build` remains the
normal way when the registry is reachable.

    ESBUILD=/path/to/esbuild tools/offline-build/build.sh

New icons from `react-icons/fa` must be added to `shims/fa.js` by hand.
