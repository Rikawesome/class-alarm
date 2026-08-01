const flaggedCourseIds = new Set([
  "course-systems-design",
]);

export function isRisky(courseId) {
  return flaggedCourseIds.has(courseId);
}

export function setRisky(courseId, risky) {
  if (risky) {
    flaggedCourseIds.add(courseId);
  } else {
    flaggedCourseIds.delete(courseId);
  }
}

export function getAlarmDisplayData(course) {
  return {
    title: course.name,
    body: isRisky(course.id)
      ? `⚠️ Risky to skip — ${course.name} now`
      : `${course.name} now`,
  };
}
