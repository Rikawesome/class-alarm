import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const ROOT = fileURLToPath(new URL(".", import.meta.url));

// The Darwin evolution pipeline runs `npm run build` inside a disposable
// temp copy of this repo for every validation attempt (see
// create_validation_workspace() in server/main.py). Vite's default cache
// location (node_modules/.vite, resolved relative to THIS file) would live
// inside that temp copy and get deleted along with it -- forcing a fully
// cold dependency pre-bundle on every single attempt, which is one of the
// biggest contributors to validation latency.
//
// DARWIN_VITE_CACHE_DIR lets the pipeline point the cache at a fixed,
// persistent location on the real disk instead, so the (expensive)
// dependency pre-bundling step can actually be reused across attempts and
// across separate /evolve calls. node_modules itself is symlinked/junctioned
// into every temp workspace pointing at the same real folder, so the
// dependency set is identical every time -- reusing this cache is safe, not
// stale, since it doesn't cache YOUR evolving source files, just the
// third-party dependency pre-bundle.
//
// When this env var isn't set (normal `npm run dev` / manual `npm run
// build`), Vite just falls back to its own default -- nothing changes for
// everyday local development.
const cacheDir = process.env.DARWIN_VITE_CACHE_DIR
  ? resolve(process.env.DARWIN_VITE_CACHE_DIR)
  : undefined;

export default defineConfig({
  root: resolve(ROOT, "web"),
  plugins: [react()],
  server: {
    fs: {
      allow: [ROOT],
    },
  },
  build: {
    outDir: resolve(ROOT, "dist"),
    emptyOutDir: true,
  },
  ...(cacheDir ? { cacheDir } : {}),
});