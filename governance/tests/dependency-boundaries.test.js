import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";
import test from "node:test";

const ROOT = resolve(import.meta.dirname, "..", "..");
const LOCKED_ROOT = join(ROOT, "locked");
const EVOLVABLE_ROOT = join(ROOT, "evolvable");
const PROTECTED_HOST_ROOTS = [
  join(ROOT, "app"),
  join(ROOT, "server"),
  join(ROOT, "governance"),
  join(ROOT, "registry"),
];

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

function findImports(source) {
  const patterns = [
    /\bimport\s+.*?\s+from\s+["']([^"']+)["']/gs,
    /\bimport\s+["']([^"']+)["']/g,
    /\bimport\s*\(\s*["']([^"']+)["']\s*\)/g,
    /\brequire\s*\(\s*["']([^"']+)["']\s*\)/g,
  ];
  return patterns.flatMap((pattern) =>
    [...source.matchAll(pattern)].map((match) => match[1]),
  );
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

test("evolvable modules do not import storage or filesystem primitives", async () => {
  const violations = [];

  for (const filePath of await collectJavaScriptFiles(EVOLVABLE_ROOT)) {
    const source = await readFile(filePath, "utf8");
    if (
      source.includes("locked/personal-data") ||
      source.includes("node:sqlite") ||
      source.includes("node:fs") ||
      source.includes("node:fs/promises")
    ) {
      violations.push(filePath);
    }
  }

  assert.deepEqual(violations, []);
});

test("evolvable modules do not import protected host composition or governance", async () => {
  const violations = [];

  for (const filePath of await collectJavaScriptFiles(EVOLVABLE_ROOT)) {
    const source = await readFile(filePath, "utf8");
    for (const importPath of findImports(source)) {
      if (!importPath.startsWith(".")) continue;
      const importedPath = resolve(dirname(filePath), importPath);
      if (
        PROTECTED_HOST_ROOTS.some(
          (root) => importedPath === root || importedPath.startsWith(`${root}${sep}`),
        )
      ) {
        violations.push(filePath);
      }
    }
  }

  assert.deepEqual(violations, []);
});
