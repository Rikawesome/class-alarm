// LOCKED MODULE — evolution requests may never modify this file.
// If a change here is ever truly needed, it requires a human developer
// decision (see registry/contracts/core-data.json -> "locked_reason").

export const COURSE_SCHEMA = {
  table: "courses",
  fields: {
    id: "TEXT PRIMARY KEY",
    name: "TEXT NOT NULL",
    day_of_week: "INTEGER NOT NULL",   // 0-6
    start_time: "TEXT NOT NULL",       // "HH:MM"
    end_time: "TEXT NOT NULL",
    recurrence: "TEXT DEFAULT 'weekly'",
  },
};

export const CREATE_TABLE_SQL = `
CREATE TABLE IF NOT EXISTS courses (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  day_of_week INTEGER NOT NULL,
  start_time TEXT NOT NULL,
  end_time TEXT NOT NULL,
  recurrence TEXT DEFAULT 'weekly'
);
`;
