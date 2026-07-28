// LOCKED MODULE — the ONLY sanctioned way for evolvable/ code to read
// course data. Evolvable modules must import from here, never from
// schema.js or a raw db client directly. The triage check in
// server/triage.py enforces this via static import-graph analysis.

import { db } from "./db.js";

export function getAllCourses() {
  return db.prepare("SELECT * FROM courses").all();
}

export function getCourseById(id) {
  return db.prepare("SELECT * FROM courses WHERE id = ?").get(id);
}

// No write functions are exposed here on purpose. Writing course data
// stays a locked-module-only operation (see core-data.json contract).
