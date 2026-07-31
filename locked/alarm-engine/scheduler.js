// LOCKED MODULE — evolution requests may never modify this file.
// This is the one piece that must fire reliably regardless of what
// evolvable/ code does. If it breaks, no course alarm rings — full stop.

import { getAllCourses } from "../core-data/access.js";
import { getSafeAlarmDisplayData } from "./alarm-display.js";

export function scheduleCourseAlarms(
  courses,
  notify,
  alarmDisplayFormatter,
  {
    now = () => new Date(),
    setTimer = setTimeout,
    clearTimer = clearTimeout,
  } = {},
) {
  const scheduledFrom = now();
  const today = scheduledFrom.getDay();
  const todaysCourses = courses.filter(
    (course) => course.day_of_week === today,
  );
  const scheduledAlarms = [];

  for (const course of todaysCourses) {
    const [hour, minute] = course.start_time.split(":").map(Number);
    const fireAt = new Date(scheduledFrom);
    fireAt.setHours(hour, minute, 0, 0);

    const msUntilFire = fireAt.getTime() - scheduledFrom.getTime();
    if (msUntilFire <= 0) continue;

    const timer = setTimer(() => {
      // Evolvable code may customize display data through the injected
      // formatter, but invalid output falls back to a locked default.
      const displayData = getSafeAlarmDisplayData(
        course,
        alarmDisplayFormatter,
      );
      notify(displayData, course);
    }, msUntilFire);

    scheduledAlarms.push({
      courseId: course.id,
      courseName: course.name,
      fireAt: fireAt.toISOString(),
      cancel() {
        clearTimer(timer);
      },
    });
  }

  return scheduledAlarms;
}

export function scheduleTodaysAlarms(
  notify,
  alarmDisplayFormatter,
  runtime,
) {
  return scheduleCourseAlarms(
    getAllCourses(),
    notify,
    alarmDisplayFormatter,
    runtime,
  );
}
