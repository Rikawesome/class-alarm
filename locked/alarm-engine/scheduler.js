// LOCKED MODULE — evolution requests may never modify this file.
// This is the one piece that must fire reliably regardless of what
// evolvable/ code does. If it breaks, no course alarm rings — full stop.

import { getAllCourses } from "../core-data/access.js";
import { getSafeAlarmDisplayData } from "./alarm-display.js";

export function scheduleTodaysAlarms(notify, alarmDisplayFormatter) {
  const today = new Date().getDay();
  const courses = getAllCourses().filter(c => c.day_of_week === today);

  for (const course of courses) {
    const [hour, minute] = course.start_time.split(":").map(Number);
    const fireAt = new Date();
    fireAt.setHours(hour, minute, 0, 0);

    const msUntilFire = fireAt.getTime() - Date.now();
    if (msUntilFire <= 0) continue;

    setTimeout(() => {
      // Evolvable code may customize display data through the injected
      // formatter, but invalid output falls back to a locked default.
      const displayData = getSafeAlarmDisplayData(
        course,
        alarmDisplayFormatter,
      );
      notify(displayData);
    }, msUntilFire);
  }
}
