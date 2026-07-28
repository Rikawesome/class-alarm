// LOCKED MODULE - normalizes evolvable display output before it reaches
// the notification boundary. A formatter failure must never suppress an alarm.

export function getDefaultAlarmDisplayData(course) {
  const courseName =
    typeof course?.name === "string" && course.name.trim()
      ? course.name.trim()
      : "Course";

  return {
    title: courseName,
    body: `${courseName} now`,
  };
}

export function getSafeAlarmDisplayData(course, formatter) {
  const fallback = getDefaultAlarmDisplayData(course);

  if (typeof formatter !== "function") {
    return fallback;
  }

  try {
    const candidate = formatter(course);
    const hasValidTitle =
      typeof candidate?.title === "string" && candidate.title.trim();
    const hasValidBody =
      typeof candidate?.body === "string" && candidate.body.trim();

    if (!hasValidTitle || !hasValidBody) {
      return fallback;
    }

    return {
      title: candidate.title,
      body: candidate.body,
    };
  } catch {
    return fallback;
  }
}
