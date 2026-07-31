import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const ROOT = resolve(import.meta.dirname, "..", "..", "..");

async function readCoursesInNewProcess(databasePath) {
  const script = `
    const { getAllCourses } = await import("./locked/core-data/access.js");
    process.stdout.write(JSON.stringify(getAllCourses()));
  `;
  const { stdout } = await execFileAsync(
    process.execPath,
    ["--input-type=module", "--eval", script],
    {
      cwd: ROOT,
      env: {
        ...process.env,
        CLASS_ALARM_DB_PATH: databasePath,
      },
    },
  );

  return JSON.parse(stdout);
}

test("course data is seeded once and survives application restarts", async () => {
  const temporaryRoot = await mkdtemp(join(tmpdir(), "darwin-core-data-"));
  const databasePath = join(temporaryRoot, "courses.db");

  try {
    const initialCourses = await readCoursesInNewProcess(databasePath);
    assert.equal(initialCourses.length, 4);

    const database = new DatabaseSync(databasePath);
    database
      .prepare("UPDATE courses SET name = ? WHERE id = ?")
      .run("Persistent Systems Design", "course-systems-design");
    database.close();

    const restartedCourses = await readCoursesInNewProcess(databasePath);
    const persistedCourse = restartedCourses.find(
      (course) => course.id === "course-systems-design",
    );

    assert.equal(restartedCourses.length, 4);
    assert.equal(persistedCourse.name, "Persistent Systems Design");
  } finally {
    assert.ok(temporaryRoot.startsWith(tmpdir()));
    await rm(temporaryRoot, { recursive: true, force: true });
  }
});

import { createCourse, deleteCourse, getCourseById } from "../access.js";

test("creates and deletes courses with validation", () => {
  const course = createCourse({
    name: "Software Architecture",
    day_of_week: 2,
    start_time: "14:00",
    end_time: "15:30",
  });
  assert.ok(course.id);
  assert.equal(course.name, "Software Architecture");

  const fetched = getCourseById(course.id);
  assert.equal(fetched.name, "Software Architecture");

  const deleted = deleteCourse(course.id);
  assert.equal(deleted.id, course.id);
  assert.equal(getCourseById(course.id), undefined);

  assert.throws(() => {
    createCourse({ name: "", day_of_week: 1, start_time: "09:00", end_time: "10:00" });
  }, /Course name is required/);

  assert.throws(() => {
    createCourse({ name: "Bad Time", day_of_week: 8, start_time: "09:00", end_time: "10:00" });
  }, /Day of week must be between/);

  assert.throws(() => {
    createCourse({ name: "Bad Format", day_of_week: 1, start_time: "9:00", end_time: "10:00" });
  }, /HH:MM 24-hour format/);
});
