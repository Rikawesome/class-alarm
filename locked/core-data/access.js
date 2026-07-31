import { db } from "./db.js";
import { randomUUID } from "node:crypto";

export function getAllCourses() {
  return db
    .prepare(
      `
        SELECT *
        FROM courses
        ORDER BY day_of_week, start_time, name
      `,
    )
    .all();
}

export function getCourseById(id) {
  return db.prepare("SELECT * FROM courses WHERE id = ?").get(id);
}

export function createCourse({
  name,
  day_of_week,
  start_time,
  end_time,
  recurrence = "weekly",
}) {
  if (!name || typeof name !== "string" || !name.trim()) {
    throw new Error("Course name is required.");
  }
  if (
    typeof day_of_week !== "number" ||
    day_of_week < 0 ||
    day_of_week > 6
  ) {
    throw new Error("Day of week must be between 0 (Sunday) and 6 (Saturday).");
  }
  const timeRegex = /^([01]\d|2[0-3]):([0-5]\d)$/;
  if (!timeRegex.test(start_time) || !timeRegex.test(end_time)) {
    throw new Error("Start time and end time must be in HH:MM 24-hour format.");
  }

  const id = `course-${randomUUID().slice(0, 8)}`;
  db.prepare(
    `
      INSERT INTO courses (id, name, day_of_week, start_time, end_time, recurrence)
      VALUES (?, ?, ?, ?, ?, ?)
    `,
  ).run(id, name.trim(), day_of_week, start_time, end_time, recurrence);

  return getCourseById(id);
}

export function deleteCourse(id) {
  const existing = getCourseById(id);
  if (!existing) {
    throw new Error("Course not found.");
  }
  db.prepare("DELETE FROM courses WHERE id = ?").run(id);
  return existing;
}
