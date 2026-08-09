import assert from "node:assert/strict";
import { access, readFile, readdir } from "node:fs/promises";
import { join, resolve } from "node:path";
import test from "node:test";

const ROOT = resolve(import.meta.dirname, "..", "..");
const REGISTRY_PATH = join(ROOT, "registry", "modules.json");
const KNOWN_EXTENSION_CAPABILITIES = new Set(["personal-storage"]);

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

    if (entry.evolution_policy === "evolvable") {
      assert.equal(typeof entry.storage_namespace, "string");
      assert.equal(contract.storage_namespace, entry.storage_namespace);
      assert.deepEqual(contract.storage_schema, entry.storage_schema);
      assert.equal(Number.isInteger(entry.storage_schema?.version), true);
      assert.match(entry.storage_namespace, /^[a-z0-9][a-z0-9._-]*$/);
    } else {
      assert.equal(entry.storage_namespace, undefined);
      assert.equal(contract.storage_namespace, undefined);
      assert.equal(entry.storage_schema, undefined);
      assert.equal(contract.storage_schema, undefined);
    }

    if (entry.extension !== undefined) {
      assert.equal(entry.role, "feature");
      assert.equal(entry.evolution_policy, "evolvable");
      assert.deepEqual(
        Object.keys(entry.extension).sort(),
        ["authorized_capabilities", "contract_version", "enabled", "runtime"],
      );
      assert.equal(entry.extension.contract_version, "1.0");
      assert.equal(typeof entry.extension.enabled, "boolean");
      assert.deepEqual(
        Object.keys(entry.extension.runtime).sort(),
        ["entry", "factory_export"],
      );
      assert.match(entry.extension.runtime.entry, /^(?!\/)(?!.*(?:^|\/)\.\.?\/)(?!.*\\).+\.js$/);
      assert.match(entry.extension.runtime.factory_export, /^[A-Za-z_$][A-Za-z0-9_$]*$/);
      assert.deepEqual(
        entry.extension.authorized_capabilities,
        [...entry.extension.authorized_capabilities].sort(),
      );
      assert.equal(
        new Set(entry.extension.authorized_capabilities).size,
        entry.extension.authorized_capabilities.length,
      );
      for (const capability of entry.extension.authorized_capabilities) {
        assert.ok(KNOWN_EXTENSION_CAPABILITIES.has(capability));
      }

      assert.equal(contract.extension.contract_version, entry.extension.contract_version);
      assert.deepEqual(contract.extension.runtime, entry.extension.runtime);
      assert.deepEqual(
        contract.extension.requested_capabilities,
        entry.extension.authorized_capabilities,
      );
      assert.equal(contract.extension.enabled, undefined);
    }

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

test("app-runtime declares its protected personal-data dependency", async () => {
  const contract = await readJson(join(ROOT, "app", "module.json"));
  assert.ok(contract.depends_on.includes("personal-data"));
});
