// EVOLVABLE MODULE — this file is the primary surface for evolution
// requests in v1. It reads course data only through the locked accessor
// (see locked/core-data/access.js) — never a raw db import.
//
// Current behavior: manual risk flag only. This is the most likely first
// thing to evolve — e.g. "flag a course automatically after I miss it twice."

import { getCourseById } from "../../../locked/core-data/access.js";

// v1: hardcoded manual list. An evolution might replace this with a rule
// engine, a missed-count lookup, or anything else — as long as it keeps
// reading course data through the locked accessor.
const MANUALLY_FLAGGED_COURSE_IDS = new Set([
  // "course_id_1", "course_id_2"
]);

export function isRisky(courseId) {
  return MANUALLY_FLAGGED_COURSE_IDS.has(courseId);
}

export function getAlarmDisplayData(course) {
  return {
    title: course.name,
    body: isRisky(course.id)
      ? `⚠️ Risky to skip — ${course.name} now`
      : `${course.name} now`,
  };
}
