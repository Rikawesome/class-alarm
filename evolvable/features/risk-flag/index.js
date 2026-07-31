// EVOLVABLE MODULE — this file is the primary surface for evolution
// requests in v1. It receives the course data it needs through its public
// function arguments and never imports a database implementation.
//
// Current behavior: manual risk flag only. This is the most likely first
// thing to evolve — e.g. "flag a course automatically after I miss it twice."

// v1: hardcoded manual list. An evolution might replace this with a rule
// engine, a missed-count lookup, or anything else — as long as it keeps
// reading course data through the locked accessor.
const MANUALLY_FLAGGED_COURSE_IDS = new Set([
  "course-systems-design",
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
