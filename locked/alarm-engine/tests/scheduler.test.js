import assert from "node:assert/strict";
import test from "node:test";

import { scheduleCourseAlarms } from "../scheduler.js";

test("schedules future courses and delivers normalized display data", () => {
  const current = new Date(2026, 6, 31, 9, 0, 0);
  const timers = [];
  const notifications = [];
  const courses = [
    {
      id: "future-course",
      name: "Future Course",
      day_of_week: current.getDay(),
      start_time: "09:05",
      end_time: "10:00",
      recurrence: "weekly",
    },
  ];

  const scheduled = scheduleCourseAlarms(
    courses,
    (displayData, course) => {
      notifications.push({ displayData, course });
    },
    () => ({
      title: "Prepared title",
      body: "Prepared body",
    }),
    {
      now: () => new Date(current),
      setTimer(callback, delay) {
        const timer = { callback, delay, cancelled: false };
        timers.push(timer);
        return timer;
      },
      clearTimer(timer) {
        timer.cancelled = true;
      },
    },
  );

  assert.equal(scheduled.length, 1);
  assert.equal(timers[0].delay, 5 * 60 * 1000);

  timers[0].callback();

  assert.deepEqual(notifications[0].displayData, {
    title: "Prepared title",
    body: "Prepared body",
  });
  assert.equal(notifications[0].course.id, "future-course");

  scheduled[0].cancel();
  assert.equal(timers[0].cancelled, true);
});

test("does not schedule past courses or courses on another day", () => {
  const current = new Date(2026, 6, 31, 12, 0, 0);
  const courses = [
    {
      id: "past-course",
      name: "Past Course",
      day_of_week: current.getDay(),
      start_time: "11:00",
      end_time: "12:00",
      recurrence: "weekly",
    },
    {
      id: "another-day",
      name: "Another Day",
      day_of_week: (current.getDay() + 1) % 7,
      start_time: "13:00",
      end_time: "14:00",
      recurrence: "weekly",
    },
  ];

  const scheduled = scheduleCourseAlarms(courses, () => {}, undefined, {
    now: () => new Date(current),
    setTimer() {
      throw new Error("No timer should be created.");
    },
  });

  assert.deepEqual(scheduled, []);
});
