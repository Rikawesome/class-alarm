import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import test from "node:test";

const ROOT = resolve(import.meta.dirname, "..", "..");
const LOCKED_ROOT = join(ROOT, "locked");

async function collectJavaScriptFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const entryPath = join(directory, entry.name);

    if (entry.isDirectory()) {
      files.push(...(await collectJavaScriptFiles(entryPath)));
    } else if (entry.isFile() && entry.name.endsWith(".js")) {
      files.push(entryPath);
    }
  }

  return files;
}

test("locked modules do not import evolvable code", async () => {
  const violations = [];

  for (const filePath of await collectJavaScriptFiles(LOCKED_ROOT)) {
    const source = await readFile(filePath, "utf8");

    if (/(?:from\s+|import\s*\()["'][^"']*evolvable\//.test(source)) {
      violations.push(filePath);
    }
  }

  assert.deepEqual(violations, []);
});
