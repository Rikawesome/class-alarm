import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, afterEach, test } from "node:test";

const databaseRoot = await mkdtemp(join(tmpdir(), "darwin-extension-db-"));
process.env.CLASS_ALARM_PERSONAL_DB_PATH = join(databaseRoot, "personal-data.db");

const { loadApprovedExtensions } = await import("../extensions.js");
const { closePersonalDatabase } = await import(
  "../../locked/personal-data/access.js"
);

const temporaryRoots = [];

after(async () => {
  closePersonalDatabase();
  await rm(databaseRoot, { force: true, recursive: true });
});

afterEach(async () => {
  await Promise.all(
    temporaryRoots.splice(0).map((root) => rm(root, { force: true, recursive: true })),
  );
});

async function createExtensionFixture({
  moduleId = "sample-feature",
  enabled = true,
  authorizedCapabilities = ["personal-storage"],
  requestedCapabilities = authorizedCapabilities,
  source = `
    export function createExtension({ moduleId, capabilities }) {
      return {
        getState() {
          return { moduleId, stored: capabilities.personalStorage.get("value") };
        },
        execute(action, input) {
          return { action, input, moduleId };
        },
      };
    }
  `,
} = {}) {
  const root = await mkdtemp(join(tmpdir(), "darwin-extension-"));
  temporaryRoots.push(root);
  const modulePath = `evolvable/features/${moduleId}`;
  const contractPath = `${modulePath}/module.json`;
  const moduleRoot = join(root, ...modulePath.split("/"));
  await mkdir(join(root, "registry"), { recursive: true });
  await mkdir(moduleRoot, { recursive: true });

  const storageSchema = {
    version: 1,
    record: {
      type: "object",
      required: [],
      additionalProperties: true,
      properties: {},
    },
  };
  const extension = {
    contract_version: "1.0",
    enabled,
    runtime: {
      entry: "index.js",
      factory_export: "createExtension",
    },
    authorized_capabilities: authorizedCapabilities,
  };
  const manifest = {
    module: moduleId,
    role: "feature",
    evolution_policy: "evolvable",
    storage_namespace: moduleId,
    storage_schema: storageSchema,
    owns: [`${modulePath}/**`],
    extension: {
      contract_version: "1.0",
      runtime: extension.runtime,
      requested_capabilities: requestedCapabilities,
    },
    file_policies: {
      "module.json": "human-review",
      "index.js": "evolvable",
    },
  };
  const registry = {
    schema_version: "1.0.0",
    modules: {
      [moduleId]: {
        path: modulePath,
        contract: contractPath,
        role: "feature",
        evolution_policy: "evolvable",
        storage_namespace: moduleId,
        storage_schema: storageSchema,
        extension,
      },
    },
    artifacts: {},
  };

  await writeFile(join(root, "registry", "modules.json"), JSON.stringify(registry));
  await writeFile(join(root, ...contractPath.split("/")), JSON.stringify(manifest));
  await writeFile(join(moduleRoot, "index.js"), source);
  return { root, registryPath: join(root, "registry", "modules.json") };
}

test("loads enabled extensions and injects only registry-authorized capabilities", async () => {
  const fixture = await createExtensionFixture();
  const requestedModuleIds = [];
  const host = await loadApprovedExtensions({
    ...fixture,
    capabilityProviders: {
      "personal-storage": (moduleId) => {
        requestedModuleIds.push(moduleId);
        return Object.freeze({
          get: () => ({ approved: true }),
          set: () => {},
          delete: () => false,
          list: () => [],
        });
      },
    },
  });

  assert.deepEqual(requestedModuleIds, ["sample-feature"]);
  assert.deepEqual(host.getState(), {
    "sample-feature": {
      moduleId: "sample-feature",
      stored: { approved: true },
    },
  });
  assert.deepEqual(
    await host.execute("sample-feature", "save", { value: 1 }),
    {
      action: "save",
      input: { value: 1 },
      moduleId: "sample-feature",
    },
  );
});

test("registry and manifest capability drift fails protected loading", async () => {
  const fixture = await createExtensionFixture({
    requestedCapabilities: [],
  });

  await assert.rejects(
    loadApprovedExtensions({
      ...fixture,
      capabilityProviders: {
        "personal-storage": () => ({ get() {} }),
      },
    }),
    /authority differ/,
  );
});

test("disabled extensions are not imported or granted capabilities", async () => {
  const fixture = await createExtensionFixture({ enabled: false });
  let providerCalls = 0;
  const host = await loadApprovedExtensions({
    ...fixture,
    capabilityProviders: {
      "personal-storage": () => {
        providerCalls += 1;
        return {};
      },
    },
  });

  assert.equal(providerCalls, 0);
  assert.deepEqual(host.getState(), {});
  assert.throws(() => host.execute("sample-feature", "read", {}), /unavailable/);
});

test("factory failures isolate the approved feature", async () => {
  const fixture = await createExtensionFixture({
    source: "export function createExtension() { throw new Error('factory failed'); }",
  });
  const host = await loadApprovedExtensions({
    ...fixture,
    capabilityProviders: {
      "personal-storage": () => ({}),
    },
  });

  assert.deepEqual(host.getState(), {});
  assert.match(host.getFailures()["sample-feature"], /factory failed/);
  assert.throws(() => host.execute("sample-feature", "read", {}), /factory failed/);
});

test("reloads approved registry changes without replacing the host object", async () => {
  const fixture = await createExtensionFixture();
  const host = await loadApprovedExtensions({
    ...fixture,
    capabilityProviders: { "personal-storage": () => ({ get() {}, set() {}, delete() {}, list() {} }) },
  });

  const registry = JSON.parse(await readFile(fixture.registryPath, "utf8"));
  registry.modules["sample-feature"].extension.enabled = false;
  await writeFile(fixture.registryPath, JSON.stringify(registry));

  const result = await host.reload();
  assert.deepEqual(result.state, {});
  assert.deepEqual(host.getState(), {});
  assert.throws(() => host.execute("sample-feature", "read", {}), /unavailable/);
});
