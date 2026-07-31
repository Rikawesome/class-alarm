import assert from "node:assert/strict";
import { access, readFile, readdir } from "node:fs/promises";
import { join, resolve } from "node:path";
import test from "node:test";

const ROOT = resolve(import.meta.dirname, "..", "..");
const REGISTRY_PATH = join(ROOT, "registry", "modules.json");

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}

test("registry entries resolve to one canonical local contract", async () => {
  const registry = await readJson(REGISTRY_PATH);
  const contractPaths = new Set();

  for (const [moduleId, entry] of Object.entries(registry.modules)) {
    const modulePath = resolve(ROOT, entry.path);
    const contractPath = resolve(ROOT, entry.contract);

    await access(modulePath);
    await access(contractPath);
    assert.equal(contractPaths.has(contractPath), false);
    contractPaths.add(contractPath);

    const contract = await readJson(contractPath);
    assert.equal(contract.module, moduleId);
    assert.equal(contract.role, entry.role);
    assert.equal(contract.evolution_policy, entry.evolution_policy);
    assert.equal(contract.file_policies["module.json"], "human-review");

    for (const dependency of contract.depends_on ?? []) {
      assert.ok(
        registry.modules[dependency],
        `${moduleId} references unknown dependency ${dependency}`,
      );
    }
  }

  for (const artifact of Object.values(registry.artifacts)) {
    assert.ok(
      registry.modules[artifact.owner],
      `Artifact owner ${artifact.owner} is not registered`,
    );
  }
});

test("the central registry contains no duplicate contract files", async () => {
  const legacyContractPath = join(ROOT, "registry", "contracts");
  const entries = await readdir(legacyContractPath).catch(() => []);

  assert.deepEqual(entries, []);
});
