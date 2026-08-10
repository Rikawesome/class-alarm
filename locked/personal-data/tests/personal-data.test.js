import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { promisify } from "node:util";
import test from "node:test";

const execFileAsync = promisify(execFile);
const ROOT = resolve(import.meta.dirname, "..", "..", "..");
const temporaryRoot = await mkdtemp(join(tmpdir(), "darwin-personal-data-"));
const databasePath = join(temporaryRoot, "personal.db");
process.env.CLASS_ALARM_PERSONAL_DB_PATH = databasePath;
const {
  closePersonalDatabase,
  createPersonalDataCapabilityForModule,
  recoverPersonalDataForModule,
} = await import("../access.js");
const { db } = await import("../db.js");

test.after(async () => {
  closePersonalDatabase();
  await rm(temporaryRoot, { recursive: true, force: true });
});

test("persists JSON records across a new process", async () => {
  const writer = `
    const { createPersonalDataCapabilityForModule } = await import("./locked/personal-data/access.js");
    createPersonalDataCapabilityForModule("risk-flag").set("current", { isRisky: true });
  `;
  await execFileAsync(process.execPath, ["--input-type=module", "--eval", writer], {
    cwd: ROOT,
    env: { ...process.env, CLASS_ALARM_PERSONAL_DB_PATH: databasePath },
  });

  const reader = `
    const { createPersonalDataCapabilityForModule } = await import("./locked/personal-data/access.js");
    process.stdout.write(JSON.stringify(createPersonalDataCapabilityForModule("risk-flag").get("current")));
  `;
  const { stdout } = await execFileAsync(process.execPath, ["--input-type=module", "--eval", reader], {
    cwd: ROOT,
    env: { ...process.env, CLASS_ALARM_PERSONAL_DB_PATH: databasePath },
  });
  assert.deepEqual(JSON.parse(stdout), { isRisky: true });
  createPersonalDataCapabilityForModule("risk-flag").delete("current");
});

test("migrates a legacy backup table before using namespace upserts", async () => {
  const legacyRoot = await mkdtemp(join(tmpdir(), "darwin-personal-data-legacy-"));
  const legacyPath = join(legacyRoot, "personal.db");
  const createLegacyDatabase = `
    import { DatabaseSync } from 'node:sqlite';
    const database = new DatabaseSync(process.env.CLASS_ALARM_PERSONAL_DB_PATH);
    database.exec(\`
      CREATE TABLE personal_namespace_backups (
        namespace TEXT NOT NULL,
        snapshot_json TEXT NOT NULL,
        created_at TEXT NOT NULL
      );
    \`);
    database.close();
  `;
  const migrateAndInspect = `
    const { createPersonalDataCapabilityForModule, closePersonalDatabase } = await import('./locked/personal-data/access.js');
    const { db } = await import('./locked/personal-data/db.js');
    createPersonalDataCapabilityForModule('risk-flag').set('migration-check', { isRisky: true });
    const columns = db.prepare('PRAGMA table_info(personal_namespace_backups)').all();
    process.stdout.write(JSON.stringify(columns));
    closePersonalDatabase();
  `;
  try {
    await execFileAsync(process.execPath, ["--input-type=module", "--eval", createLegacyDatabase], {
      cwd: ROOT,
      env: { ...process.env, CLASS_ALARM_PERSONAL_DB_PATH: legacyPath },
    });
    const { stdout } = await execFileAsync(process.execPath, ["--input-type=module", "--eval", migrateAndInspect], {
      cwd: ROOT,
      env: { ...process.env, CLASS_ALARM_PERSONAL_DB_PATH: legacyPath },
    });
    const columns = JSON.parse(stdout);
    assert.equal(columns.find((column) => column.name === "namespace").pk, 1);
  } finally {
    await rm(legacyRoot, { recursive: true, force: true });
  }
});

test("capabilities cannot cross namespaces", () => {
  const goals = createPersonalDataCapabilityForModule("risk-flag");
  const planner = createPersonalDataCapabilityForModule("ui");
  const riskKey = "risk-isolation";
  const uiKey = "ui-isolation";
  goals.set(riskKey, { isRisky: true });
  planner.set(uiKey, { note: "ui-owned" });

  assert.equal(planner.get(riskKey), null);
  assert.equal(goals.get(uiKey), null);
  assert.deepEqual(goals.get(riskKey), { isRisky: true });
  assert.deepEqual(planner.get(uiKey), { note: "ui-owned" });
  assert.equal(goals.delete(uiKey), false);
  assert.equal(planner.delete(riskKey), false);
  goals.delete(riskKey);
  planner.delete(uiKey);
});

test("capability exposes operations without storage primitives", () => {
  const capability = createPersonalDataCapabilityForModule("risk-flag");
  assert.deepEqual(Object.keys(capability).sort(), ["delete", "get", "list", "set"]);
  assert.equal(Object.prototype.hasOwnProperty.call(capability, "db"), false);
  assert.equal(Object.prototype.hasOwnProperty.call(capability, "databasePath"), false);
});

test("rejects invalid keys and non-JSON values without changing state", () => {
  const capability = createPersonalDataCapabilityForModule("risk-flag");
  const key = "invalid-inputs";
  assert.throws(() => capability.set("Bad Key", true), /Key must be/);
  assert.throws(() => capability.set("function", () => true), /JSON-compatible/);
  assert.equal(capability.get(key), null);
});

test("enforces the registered record schema", () => {
  const capability = createPersonalDataCapabilityForModule("risk-flag");
  assert.throws(() => capability.set("invalid", {}), /missing 'isRisky'/);
  assert.throws(() => capability.set("invalid", { isRisky: true, extra: 1 }), /Unknown personal data field/);
  assert.equal(capability.get("invalid"), null);
});

test("rejects a stored schema version mismatch", () => {
  const versionOne = createPersonalDataCapabilityForModule("risk-flag");
  versionOne.set("versioned", { isRisky: true });
  db.prepare("UPDATE personal_records SET schema_version = 99 WHERE namespace = ? AND record_key = ?")
    .run("risk-flag", "versioned");
  assert.throws(() => versionOne.get("versioned"), /schema version mismatch/);
  db.prepare("DELETE FROM personal_records WHERE namespace = ? AND record_key = ?")
    .run("risk-flag", "versioned");
});

test("recovers one namespace without changing another", () => {
  const risk = createPersonalDataCapabilityForModule("risk-flag");
  const ui = createPersonalDataCapabilityForModule("ui");
  const riskKey = "recovery-isolation";
  const uiKey = "recovery-unrelated";
  risk.delete(riskKey);
  ui.delete(uiKey);
  risk.set(riskKey, { isRisky: true });
  ui.set(uiKey, { note: "keep" });
  risk.delete(riskKey);

  const result = recoverPersonalDataForModule("risk-flag");
  assert.equal(result.restored_records, 1);
  assert.deepEqual(risk.get(riskKey), { isRisky: true });
  assert.deepEqual(ui.get(uiKey), { note: "keep" });

  risk.delete(riskKey);
  ui.delete(uiKey);
});

test("refuses a malformed backup without changing live records", () => {
  const risk = createPersonalDataCapabilityForModule("risk-flag");
  risk.set("protected", { isRisky: true });
  db.prepare("UPDATE personal_namespace_backups SET snapshot_json = ? WHERE namespace = ?")
    .run("not-json", "risk-flag");

  assert.throws(() => recoverPersonalDataForModule("risk-flag"), /Recovery backup is invalid/);
  assert.deepEqual(risk.get("protected"), { isRisky: true });
  db.prepare("DELETE FROM personal_records WHERE namespace = ? AND record_key = ?")
    .run("risk-flag", "protected");
});

test("personal storage operations do not modify protected course storage", async () => {
  const isolatedRoot = await mkdtemp(join(tmpdir(), "darwin-protected-boundary-"));
  const coreDatabasePath = join(isolatedRoot, "courses.db");
  const personalDatabasePath = join(isolatedRoot, "personal.db");
  const script = `
    const { getAllCourses } = await import("./locked/core-data/access.js");
    const { createPersonalDataCapabilityForModule } = await import("./locked/personal-data/access.js");
    const before = getAllCourses();
    const storage = createPersonalDataCapabilityForModule("risk-flag");
    storage.set("boundary", { isRisky: true });
    storage.delete("boundary");
    const after = getAllCourses();
    process.stdout.write(JSON.stringify({ before, after }));
  `;
  try {
    const { stdout } = await execFileAsync(process.execPath, ["--input-type=module", "--eval", script], {
      cwd: ROOT,
      env: {
        ...process.env,
        CLASS_ALARM_DB_PATH: coreDatabasePath,
        CLASS_ALARM_PERSONAL_DB_PATH: personalDatabasePath,
      },
    });
    const result = JSON.parse(stdout);
    assert.deepEqual(result.after, result.before);
  } finally {
    await rm(isolatedRoot, { recursive: true, force: true });
  }
});
