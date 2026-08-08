// LOCKED MODULE - exposes namespace-bound personal-data capabilities only.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { closePersonalDatabase, db } from "./db.js";

export { closePersonalDatabase };

const REGISTRY_PATH = resolve(import.meta.dirname, "..", "..", "registry", "modules.json");

const MAX_NAMESPACE_LENGTH = 64;
const MAX_KEY_LENGTH = 128;
const DEFAULT_SCHEMA_VERSION = 1;

function validateIdentifier(value, label, maxLength) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > maxLength ||
    !/^[a-z0-9][a-z0-9._-]*$/.test(value)
  ) {
    throw new Error(`${label} must be 1-${maxLength} lowercase identifier characters.`);
  }
  return value;
}

function assertJsonValue(value, seen = new Set()) {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return;
  }
  if (typeof value === "number") {
    if (Number.isFinite(value)) return;
    throw new Error("Personal data values must contain finite numbers.");
  }
  if (typeof value !== "object" || seen.has(value)) {
    throw new Error("Personal data values must be JSON-compatible and acyclic.");
  }
  seen.add(value);
  if (Array.isArray(value)) {
    for (const item of value) assertJsonValue(item, seen);
  } else {
    for (const [key, item] of Object.entries(value)) {
      if (key === "__proto__" || key === "constructor" || key === "prototype") {
        throw new Error("Personal data objects contain a forbidden property.");
      }
      assertJsonValue(item, seen);
    }
  }
  seen.delete(value);
}

function cloneAndValidate(value) {
  assertJsonValue(value);
  return JSON.parse(JSON.stringify(value));
}

function normalizeSchemaVersion(schemaVersion) {
  if (!Number.isInteger(schemaVersion) || schemaVersion < 1) {
    throw new Error("Schema version must be a positive integer.");
  }
  return schemaVersion;
}

function assertRecordSchema(value, schema) {
  if (!schema || schema.type !== "object" || !schema.properties) return;
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Personal data record must be an object.");
  }
  const required = schema.required ?? [];
  for (const key of required) {
    if (!Object.hasOwn(value, key)) throw new Error(`Personal data record is missing '${key}'.`);
  }
  if (schema.additionalProperties === false) {
    for (const key of Object.keys(value)) {
      if (!Object.hasOwn(schema.properties, key)) throw new Error(`Unknown personal data field '${key}'.`);
    }
  }
  for (const [key, descriptor] of Object.entries(schema.properties)) {
    if (!Object.hasOwn(value, key)) continue;
    const actual = typeof value[key];
    if (descriptor.type === "boolean" && actual !== "boolean") throw new Error(`Field '${key}' must be boolean.`);
    if (descriptor.type === "string" && actual !== "string") throw new Error(`Field '${key}' must be string.`);
    if (descriptor.type === "number" && (actual !== "number" || !Number.isFinite(value[key]))) throw new Error(`Field '${key}' must be a finite number.`);
  }
}

function createNamespaceCapability(namespace, schema) {
  const boundNamespace = validateIdentifier(namespace, "Namespace", MAX_NAMESPACE_LENGTH);
  const boundSchemaVersion = normalizeSchemaVersion(schema.version);

  function readValue(row) {
    if (row.schema_version !== boundSchemaVersion) {
      throw new Error(`Stored schema version mismatch for namespace '${boundNamespace}'.`);
    }
    const value = cloneAndValidate(JSON.parse(row.value_json));
    assertRecordSchema(value, schema.record);
    return value;
  }

  function backupNamespace() {
    const snapshot = db
      .prepare("SELECT record_key, value_json, schema_version, updated_at FROM personal_records WHERE namespace = ? ORDER BY record_key")
      .all(boundNamespace);
    db.prepare(`
      INSERT INTO personal_namespace_backups (namespace, snapshot_json, created_at)
      VALUES (?, ?, ?)
      ON CONFLICT(namespace) DO UPDATE SET
        snapshot_json = excluded.snapshot_json,
        created_at = excluded.created_at
    `).run(boundNamespace, JSON.stringify(snapshot), new Date().toISOString());
  }

  return Object.freeze({
    get(key) {
      const recordKey = validateIdentifier(key, "Key", MAX_KEY_LENGTH);
      const row = db
        .prepare("SELECT value_json, schema_version FROM personal_records WHERE namespace = ? AND record_key = ?")
        .get(boundNamespace, recordKey);
      if (!row) return null;
      return readValue(row);
    },

    set(key, value) {
      const recordKey = validateIdentifier(key, "Key", MAX_KEY_LENGTH);
      const safeValue = cloneAndValidate(value);
      assertRecordSchema(safeValue, schema.record);
      const now = new Date().toISOString();
      db.exec("BEGIN IMMEDIATE");
      try {
        backupNamespace();
        db.prepare(`
          INSERT INTO personal_records (namespace, record_key, value_json, schema_version, updated_at)
          VALUES (?, ?, ?, ?, ?)
          ON CONFLICT(namespace, record_key) DO UPDATE SET
            value_json = excluded.value_json,
            schema_version = excluded.schema_version,
            updated_at = excluded.updated_at
        `).run(boundNamespace, recordKey, JSON.stringify(safeValue), boundSchemaVersion, now);
        db.exec("COMMIT");
      } catch (error) {
        db.exec("ROLLBACK");
        throw error;
      }
      return safeValue;
    },

    delete(key) {
      const recordKey = validateIdentifier(key, "Key", MAX_KEY_LENGTH);
      const existing = db.prepare("SELECT 1 FROM personal_records WHERE namespace = ? AND record_key = ?")
        .get(boundNamespace, recordKey);
      if (!existing) return false;
      db.exec("BEGIN IMMEDIATE");
      try {
        backupNamespace();
        db.prepare("DELETE FROM personal_records WHERE namespace = ? AND record_key = ?")
          .run(boundNamespace, recordKey);
        db.exec("COMMIT");
      } catch (error) {
        db.exec("ROLLBACK");
        throw error;
      }
      return true;
    },

    list() {
      return db
        .prepare("SELECT record_key, value_json, schema_version FROM personal_records WHERE namespace = ? ORDER BY record_key")
        .all(boundNamespace)
        .map((row) => {
          return { key: row.record_key, value: readValue(row) };
        });
    },
  });
}

function getRegisteredStorageDefinition(moduleId) {
  if (typeof moduleId !== "string" || !moduleId) {
    throw new Error("A registered module ID is required.");
  }
  const registry = JSON.parse(readFileSync(REGISTRY_PATH, "utf8"));
  const entry = registry.modules?.[moduleId];
  if (!entry || entry.evolution_policy !== "evolvable") {
    throw new Error(`Module '${moduleId}' is not an eligible evolvable storage owner.`);
  }
  if (!entry.storage_namespace || !entry.storage_schema) {
    throw new Error(`Module '${moduleId}' has incomplete storage registration.`);
  }
  return { namespace: entry.storage_namespace, schema: entry.storage_schema };
}

export function recoverPersonalDataForModule(moduleId) {
  const { namespace, schema } = getRegisteredStorageDefinition(moduleId);
  const backup = db.prepare("SELECT snapshot_json FROM personal_namespace_backups WHERE namespace = ?")
    .get(namespace);
  if (!backup) throw new Error(`No recovery backup exists for module '${moduleId}'.`);
  let snapshot;
  try {
    snapshot = JSON.parse(backup.snapshot_json);
    if (!Array.isArray(snapshot)) throw new Error("Backup snapshot must be an array.");
    for (const row of snapshot) {
      if (row.schema_version !== schema.version) throw new Error("Backup schema version mismatch.");
      const value = cloneAndValidate(JSON.parse(row.value_json));
      assertRecordSchema(value, schema.record);
    }
  } catch (error) {
    throw new Error(`Recovery backup is invalid for module '${moduleId}': ${error.message}`);
  }
  db.exec("BEGIN IMMEDIATE");
  try {
    db.prepare("DELETE FROM personal_records WHERE namespace = ?").run(namespace);
    const insert = db.prepare("INSERT INTO personal_records (namespace, record_key, value_json, schema_version, updated_at) VALUES (?, ?, ?, ?, ?)");
    for (const row of snapshot) insert.run(namespace, row.record_key, row.value_json, row.schema_version, row.updated_at);
    db.exec("COMMIT");
  } catch (error) {
    db.exec("ROLLBACK");
    throw error;
  }
  return { moduleId, namespace, restored_records: snapshot.length };
}

export function createPersonalDataCapabilityForModule(moduleId) {
  const { namespace, schema } = getRegisteredStorageDefinition(moduleId);
  return createNamespaceCapability(namespace, schema);
}
