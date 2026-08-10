// LOCKED MODULE - owns feature-private personal data storage.

import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";

const MODULE_DIR = dirname(import.meta.filename);
const ROOT = resolve(MODULE_DIR, "..", "..");

export const DEFAULT_PERSONAL_DATABASE_PATH = resolve(
  ROOT,
  "data",
  "personal-data.db",
);

function hasNamespacePrimaryKey(database) {
  const columns = database.prepare("PRAGMA table_info(personal_namespace_backups)").all();
  return columns.some((column) => column.name === "namespace" && column.pk > 0);
}

function migrateNamespaceBackups(database) {
  if (hasNamespacePrimaryKey(database)) return;

  // Early versions of the application created this table without a unique
  // namespace. CREATE TABLE IF NOT EXISTS cannot upgrade that live schema,
  // but backupNamespace() relies on its ON CONFLICT(namespace) clause. Rebuild
  // the small backup table atomically, retaining the most recently inserted
  // snapshot for any legacy duplicate namespace.
  database.exec("BEGIN IMMEDIATE");
  try {
    database.exec(`
      CREATE TABLE personal_namespace_backups_migrated (
        namespace TEXT PRIMARY KEY,
        snapshot_json TEXT NOT NULL,
        created_at TEXT NOT NULL
      );
      INSERT OR REPLACE INTO personal_namespace_backups_migrated (
        namespace,
        snapshot_json,
        created_at
      )
      SELECT namespace, snapshot_json, created_at
      FROM personal_namespace_backups
      ORDER BY created_at, rowid;
      DROP TABLE personal_namespace_backups;
      ALTER TABLE personal_namespace_backups_migrated
        RENAME TO personal_namespace_backups;
      COMMIT;
    `);
  } catch (error) {
    database.exec("ROLLBACK");
    throw error;
  }
}

export function openPersonalDatabase(
  databasePath = process.env.CLASS_ALARM_PERSONAL_DB_PATH || DEFAULT_PERSONAL_DATABASE_PATH,
) {
  if (databasePath !== ":memory:") {
    mkdirSync(dirname(databasePath), { recursive: true });
  }

  const database = new DatabaseSync(databasePath);
  database.exec(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS personal_records (
      namespace TEXT NOT NULL,
      record_key TEXT NOT NULL,
      value_json TEXT NOT NULL,
      schema_version INTEGER NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY (namespace, record_key)
    );
    CREATE TABLE IF NOT EXISTS personal_namespace_backups (
      namespace TEXT PRIMARY KEY,
      snapshot_json TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
  `);
  migrateNamespaceBackups(database);
  return database;
}

export const db = openPersonalDatabase();

let databaseClosed = false;

export function closePersonalDatabase() {
  if (databaseClosed) return;
  db.close();
  databaseClosed = true;
}
