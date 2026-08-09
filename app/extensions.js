import { readFile, realpath, stat } from "node:fs/promises";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";

import { createPersonalDataCapabilityForModule } from "../locked/personal-data/access.js";

const ROOT = resolve(import.meta.dirname, "..");
const DEFAULT_REGISTRY_PATH = resolve(ROOT, "registry", "modules.json");
const KNOWN_CAPABILITIES = new Set(["personal-storage"]);
const FACTORY_EXPORT_PATTERN = /^[A-Za-z_$][A-Za-z0-9_$]*$/;

const DEFAULT_CAPABILITY_PROVIDERS = Object.freeze({
  "personal-storage": (moduleId) => createPersonalDataCapabilityForModule(moduleId),
});

function assertExactKeys(value, expectedKeys, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object.`);
  }
  const actualKeys = Object.keys(value).sort();
  const sortedExpected = [...expectedKeys].sort();
  if (
    actualKeys.length !== sortedExpected.length ||
    actualKeys.some((key, index) => key !== sortedExpected[index])
  ) {
    throw new Error(`${label} contains unexpected or missing fields.`);
  }
}

function assertCapabilityList(capabilities, label) {
  if (!Array.isArray(capabilities)) {
    throw new Error(`${label} must be an array.`);
  }
  if (
    capabilities.some((name) => typeof name !== "string") ||
    capabilities.some((name, index) => index > 0 && capabilities[index - 1] >= name)
  ) {
    throw new Error(`${label} must contain unique capability names in lexical order.`);
  }
  const unknown = capabilities.filter((name) => !KNOWN_CAPABILITIES.has(name));
  if (unknown.length > 0) {
    throw new Error(`${label} contains unknown capabilities: ${unknown.join(", ")}.`);
  }
}

function validateEntryPath(entryPath) {
  if (
    typeof entryPath !== "string" ||
    entryPath.length === 0 ||
    entryPath.includes("\\") ||
    entryPath.includes("\0") ||
    isAbsolute(entryPath) ||
    /^[A-Za-z]:/.test(entryPath) ||
    entryPath.includes("://")
  ) {
    throw new Error("Extension runtime entry must be a relative POSIX path.");
  }
  const segments = entryPath.split("/");
  if (segments.some((segment) => segment === "" || segment === "." || segment === "..")) {
    throw new Error("Extension runtime entry contains a forbidden path segment.");
  }
  if (!entryPath.endsWith(".js")) {
    throw new Error("Extension runtime entry must resolve to a .js file.");
  }
}

function globMatches(value, pattern) {
  const escaped = pattern
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replaceAll("**", "\0")
    .replaceAll("*", "[^/]*")
    .replaceAll("\0", ".*");
  return new RegExp(`^${escaped}$`).test(value);
}

function assertJsonCompatible(value, label) {
  const seen = new Set();

  function visit(candidate) {
    if (
      candidate === null ||
      typeof candidate === "string" ||
      typeof candidate === "boolean" ||
      (typeof candidate === "number" && Number.isFinite(candidate))
    ) {
      return;
    }
    if (typeof candidate !== "object" || seen.has(candidate)) {
      throw new Error(`${label} must be JSON-compatible.`);
    }
    seen.add(candidate);
    if (Array.isArray(candidate)) {
      for (const item of candidate) visit(item);
    } else {
      if (Object.getPrototypeOf(candidate) !== Object.prototype) {
        throw new Error(`${label} must contain only plain objects.`);
      }
      for (const [key, item] of Object.entries(candidate)) {
        if (typeof key !== "string" || item === undefined) {
          throw new Error(`${label} must be JSON-compatible.`);
        }
        visit(item);
      }
    }
    seen.delete(candidate);
  }

  visit(value);
  return structuredClone(value);
}

function validateDescriptor(moduleId, entry, manifest) {
  const descriptor = entry.extension;
  assertExactKeys(
    descriptor,
    ["authorized_capabilities", "contract_version", "enabled", "runtime"],
    `Registry extension descriptor for '${moduleId}'`,
  );
  assertExactKeys(
    descriptor.runtime,
    ["entry", "factory_export"],
    `Registry runtime descriptor for '${moduleId}'`,
  );
  if (descriptor.contract_version !== "1.0" || typeof descriptor.enabled !== "boolean") {
    throw new Error(`Registry extension descriptor for '${moduleId}' has invalid version or enablement.`);
  }
  validateEntryPath(descriptor.runtime.entry);
  if (!FACTORY_EXPORT_PATTERN.test(descriptor.runtime.factory_export)) {
    throw new Error(`Registry extension factory for '${moduleId}' is invalid.`);
  }
  assertCapabilityList(
    descriptor.authorized_capabilities,
    `Registry capabilities for '${moduleId}'`,
  );

  if (
    entry.role !== "feature" ||
    entry.evolution_policy !== "evolvable" ||
    manifest.module !== moduleId ||
    manifest.role !== entry.role ||
    manifest.evolution_policy !== entry.evolution_policy
  ) {
    throw new Error(`Registry and manifest identity differ for '${moduleId}'.`);
  }

  const request = manifest.extension;
  assertExactKeys(
    request,
    ["contract_version", "requested_capabilities", "runtime"],
    `Manifest extension request for '${moduleId}'`,
  );
  assertExactKeys(
    request.runtime,
    ["entry", "factory_export"],
    `Manifest runtime request for '${moduleId}'`,
  );
  assertCapabilityList(
    request.requested_capabilities,
    `Manifest capabilities for '${moduleId}'`,
  );
  if (
    request.contract_version !== descriptor.contract_version ||
    request.runtime.entry !== descriptor.runtime.entry ||
    request.runtime.factory_export !== descriptor.runtime.factory_export ||
    JSON.stringify(request.requested_capabilities) !==
      JSON.stringify(descriptor.authorized_capabilities)
  ) {
    throw new Error(`Registry and manifest extension authority differ for '${moduleId}'.`);
  }

  const repositoryEntry = `${entry.path}/${descriptor.runtime.entry}`;
  if (!(manifest.owns ?? []).some((pattern) => globMatches(repositoryEntry, pattern))) {
    throw new Error(`Manifest ownership does not cover the runtime entry for '${moduleId}'.`);
  }
  if (
    !Object.keys(manifest.file_policies ?? {}).some((pattern) =>
      globMatches(descriptor.runtime.entry, pattern),
    )
  ) {
    throw new Error(`Manifest file policy does not cover the runtime entry for '${moduleId}'.`);
  }
  if (
    descriptor.authorized_capabilities.includes("personal-storage") &&
    (
      manifest.storage_namespace !== entry.storage_namespace ||
      JSON.stringify(manifest.storage_schema) !== JSON.stringify(entry.storage_schema)
    )
  ) {
    throw new Error(`Personal-storage metadata differs for '${moduleId}'.`);
  }
}

async function resolveRuntimeEntry(root, entry, runtimeEntry) {
  const moduleRoot = await realpath(resolve(root, entry.path));
  const candidate = resolve(moduleRoot, runtimeEntry);
  const contained = relative(moduleRoot, candidate);
  if (contained === "" || contained.startsWith(`..${sep}`) || contained === ".." || isAbsolute(contained)) {
    throw new Error("Extension runtime entry escapes its registered module root.");
  }
  const resolvedEntry = await realpath(candidate);
  const resolvedRelative = relative(moduleRoot, resolvedEntry);
  if (
    resolvedRelative.startsWith(`..${sep}`) ||
    resolvedRelative === ".." ||
    isAbsolute(resolvedRelative)
  ) {
    throw new Error("Extension runtime entry symlink escapes its registered module root.");
  }
  const entryStat = await stat(resolvedEntry);
  if (!entryStat.isFile() || !resolvedEntry.endsWith(".js")) {
    throw new Error("Extension runtime entry must be an existing regular .js file.");
  }
  return resolvedEntry;
}

export async function loadApprovedExtensions({
  root = ROOT,
  registryPath = DEFAULT_REGISTRY_PATH,
  capabilityProviders = DEFAULT_CAPABILITY_PROVIDERS,
} = {}) {
  const registry = JSON.parse(await readFile(registryPath, "utf8"));
  const approved = [];

  for (const [moduleId, entry] of Object.entries(registry.modules ?? {})) {
    if (entry.extension === undefined) continue;
    const manifestPath = resolve(root, entry.contract);
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    validateDescriptor(moduleId, entry, manifest);
    if (entry.extension.enabled) approved.push({ moduleId, entry, manifest });
  }

  const active = new Map();
  const failures = new Map();
  let replacement = null;

  for (const { moduleId, entry } of approved) {
    try {
      const runtimeEntry = await resolveRuntimeEntry(
        root,
        entry,
        entry.extension.runtime.entry,
      );
      const capabilities = {};
      for (const capabilityName of entry.extension.authorized_capabilities) {
        const provider = capabilityProviders[capabilityName];
        if (typeof provider !== "function") {
          throw new Error(`No protected provider exists for '${capabilityName}'.`);
        }
        const propertyName =
          capabilityName === "personal-storage" ? "personalStorage" : capabilityName;
        capabilities[propertyName] = provider(moduleId);
      }
      const extensionModule = await import(pathToFileURL(runtimeEntry).href);
      const factory = extensionModule[entry.extension.runtime.factory_export];
      if (typeof factory !== "function") {
        throw new Error("Configured extension factory export is missing.");
      }
      const extension = factory(Object.freeze({
        moduleId,
        capabilities: Object.freeze(capabilities),
      }));
      if (
        !extension ||
        typeof extension.getState !== "function" ||
        typeof extension.execute !== "function"
      ) {
        throw new Error("Extension factory returned an invalid runtime interface.");
      }
      active.set(moduleId, extension);
    } catch (error) {
      failures.set(moduleId, error instanceof Error ? error.message : String(error));
    }
  }

  function unavailable(moduleId) {
    const reason = failures.get(moduleId);
    return new Error(
      reason
        ? `Extension '${moduleId}' is unavailable: ${reason}`
        : `Extension '${moduleId}' is unavailable.`,
    );
  }

  return Object.freeze({
    async reload() {
      const refreshed = await loadApprovedExtensions({
        root,
        registryPath,
        capabilityProviders,
      });
      replacement = refreshed;
      return {
        failures: refreshed.getFailures(),
        state: refreshed.getState(),
      };
    },
    execute(moduleId, action, input) {
      if (replacement) return replacement.execute(moduleId, action, input);
      const extension = active.get(moduleId);
      if (!extension) throw unavailable(moduleId);
      if (typeof action !== "string" || action.length === 0) {
        throw new Error("Extension action must be a non-empty string.");
      }
      const safeInput = assertJsonCompatible(input, "Extension action input");
      return Promise.resolve(extension.execute(action, safeInput)).then((output) =>
        assertJsonCompatible(output, "Extension action output"),
      );
    },
    getFailures() {
      if (replacement) return replacement.getFailures();
      return Object.fromEntries(failures);
    },
    getState() {
      if (replacement) return replacement.getState();
      const state = {};
      for (const [moduleId, extension] of active) {
        try {
          state[moduleId] = assertJsonCompatible(
            extension.getState(),
            `Extension state for '${moduleId}'`,
          );
        } catch (error) {
          active.delete(moduleId);
          failures.set(moduleId, error instanceof Error ? error.message : String(error));
        }
      }
      return state;
    },
  });
}

export const defaultExtensionHost = await loadApprovedExtensions();
