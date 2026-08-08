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
  return database;
}

export const db = openPersonalDatabase();

let databaseClosed = false;

export function closePersonalDatabase() {
  if (databaseClosed) return;
  db.close();
  databaseClosed = true;
}
