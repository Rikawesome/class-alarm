// LOCKED MODULE - owns the physical course database and initializes it.
// Application and evolvable code must read courses through access.js.

import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";

import { CREATE_TABLE_SQL } from "./schema.js";

const CORE_DATA_DIR = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(CORE_DATA_DIR, "..", "..");

export const DEFAULT_DATABASE_PATH = resolve(
  ROOT,
  "data",
  "class-alarm.db",
);

function formatTime(date) {
  return `${String(date.getHours()).padStart(2, "0")}:${String(
    date.getMinutes(),
  ).padStart(2, "0")}`;
}

function createSeedCourses(now = new Date()) {
  const upcomingStart = new Date(now.getTime() + 5 * 60 * 1000);
  const upcomingEnd = new Date(upcomingStart.getTime() + 60 * 60 * 1000);

  return [
    {
      id: "course-applied-algorithms",
      name: "Applied Algorithms",
      day_of_week: upcomingStart.getDay(),
      start_time: formatTime(upcomingStart),
      end_time: formatTime(upcomingEnd),
      recurrence: "weekly",
    },
    {
      id: "course-systems-design",
      name: "Systems Design",
      day_of_week: (now.getDay() + 1) % 7,
      start_time: "09:30",
      end_time: "10:45",
      recurrence: "weekly",
    },
    {
      id: "course-data-ethics",
      name: "Data Ethics",
      day_of_week: (now.getDay() + 2) % 7,
      start_time: "13:00",
      end_time: "14:00",
      recurrence: "weekly",
    },
    {
      id: "course-research-studio",
      name: "Research Studio",
      day_of_week: (now.getDay() + 4) % 7,
      start_time: "15:30",
      end_time: "17:00",
      recurrence: "weekly",
    },
  ];
}

function seedCourses(database, now) {
  const existing = database
    .prepare("SELECT COUNT(*) AS count FROM courses")
    .get();

  if (Number(existing.count) > 0) {
    return;
  }

  const insert = database.prepare(`
    INSERT INTO courses (
      id,
      name,
      day_of_week,
      start_time,
      end_time,
      recurrence
    ) VALUES (?, ?, ?, ?, ?, ?)
  `);

  database.exec("BEGIN");

  try {
    for (const course of createSeedCourses(now)) {
      insert.run(
        course.id,
        course.name,
        course.day_of_week,
        course.start_time,
        course.end_time,
        course.recurrence,
      );
    }

    database.exec("COMMIT");
  } catch (error) {
    database.exec("ROLLBACK");
    throw error;
  }
}

export function openCourseDatabase({
  databasePath = process.env.CLASS_ALARM_DB_PATH || DEFAULT_DATABASE_PATH,
  now = new Date(),
} = {}) {
  if (databasePath !== ":memory:") {
    mkdirSync(dirname(databasePath), { recursive: true });
  }

  const database = new DatabaseSync(databasePath);
  database.exec("PRAGMA journal_mode = WAL");
  database.exec(CREATE_TABLE_SQL);
  seedCourses(database, now);

  return database;
}

export const db = openCourseDatabase();

let databaseClosed = false;

export function closeCourseDatabase() {
  if (databaseClosed) {
    return;
  }

  db.close();
  databaseClosed = true;
}
