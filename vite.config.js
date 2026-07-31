import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const ROOT = fileURLToPath(new URL(".", import.meta.url));

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
});
