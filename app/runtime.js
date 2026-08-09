// APPLICATION COMPOSITION - this is where protected capabilities and optional
// evolvable behavior are wired together. Neither side imports the other.

import { EventEmitter } from "node:events";
import { randomUUID } from "node:crypto";

import { defaultExtensionHost } from "./extensions.js";
import { createRiskFlag } from "../evolvable/features/risk-flag/index.js";
import { getSafeAlarmDisplayData } from "../locked/alarm-engine/alarm-display.js";
import { scheduleCourseAlarms } from "../locked/alarm-engine/scheduler.js";
import { getAllCourses, createCourse, deleteCourse } from "../locked/core-data/access.js";
import { createPersonalDataCapabilityForModule } from "../locked/personal-data/access.js";

const MAX_NOTIFICATION_HISTORY = 20;

function toPublicScheduledAlarm(alarm) {
  return {
    courseId: alarm.courseId,
    courseName: alarm.courseName,
    fireAt: alarm.fireAt,
  };
}

export function createClassAlarmRuntime({
  courseReader = { getAllCourses },
  alarmDisplayFormatter,
  riskEvaluator,
  now = () => new Date(),
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  scheduleDailyRefresh = true,
  riskStorage = createPersonalDataCapabilityForModule("risk-flag"),
  extensionHost = defaultExtensionHost,
} = {}) {
  const riskFlag = createRiskFlag({ storage: riskStorage });
  const displayFormatter = alarmDisplayFormatter ?? riskFlag.getAlarmDisplayData;
  const evaluateRisk = riskEvaluator ?? riskFlag.isRisky;
  const events = new EventEmitter();
  let scheduledAlarms = [];
  let recentNotifications = [];
  let dailyRefreshTimer = null;
  let started = false;

  function listCourses() {
    return courseReader.getAllCourses().map((course) => ({
      ...course,
      is_risky: Boolean(evaluateRisk(course.id)),
    }));
  }

  function addCourse(courseData) {
    const course = createCourse(courseData);
    reschedule();
    return course;
  }

  function removeCourse(courseId) {
    const course = deleteCourse(courseId);
    reschedule();
    return course;
  }

  function toggleCourseRisk(courseId, risky) {
    riskFlag.setRisky(courseId, risky);
    reschedule();
    return listCourses().find((c) => c.id === courseId);
  }

  function importCourses(coursesList) {
    const created = [];
    for (const c of coursesList) {
      created.push(createCourse(c));
    }
    reschedule();
    return created;
  }

  function recordNotification(displayData, course, source) {
    const notification = {
      id: randomUUID(),
      title: displayData.title,
      body: displayData.body,
      courseId: course?.id ?? null,
      courseName: course?.name ?? displayData.title,
      deliveredAt: now().toISOString(),
      source,
    };

    recentNotifications = [
      notification,
      ...recentNotifications,
    ].slice(0, MAX_NOTIFICATION_HISTORY);
    events.emit("notification", notification);

    return notification;
  }

  function cancelScheduledAlarms() {
    for (const alarm of scheduledAlarms) {
      alarm.cancel();
    }

    scheduledAlarms = [];
  }

  function scheduleNextDailyRefresh() {
    if (!scheduleDailyRefresh) {
      return;
    }

    if (dailyRefreshTimer) {
      clearTimer(dailyRefreshTimer);
    }

    const current = now();
    const nextDay = new Date(current);
    nextDay.setHours(24, 0, 5, 0);

    dailyRefreshTimer = setTimer(() => {
      reschedule();
      scheduleNextDailyRefresh();
    }, nextDay.getTime() - current.getTime());
  }

  function reschedule() {
    cancelScheduledAlarms();

    scheduledAlarms = scheduleCourseAlarms(
      listCourses(),
      (displayData, course) => {
        recordNotification(displayData, course, "scheduled");
      },
      displayFormatter,
      {
        now,
        setTimer,
        clearTimer,
      },
    );

    return scheduledAlarms.map(toPublicScheduledAlarm);
  }

  function start() {
    if (started) {
      return getSnapshot();
    }

    started = true;
    reschedule();
    scheduleNextDailyRefresh();

    return getSnapshot();
  }

  function stop() {
    cancelScheduledAlarms();

    if (dailyRefreshTimer) {
      clearTimer(dailyRefreshTimer);
      dailyRefreshTimer = null;
    }

    started = false;
  }

  function getSnapshot() {
    const publicAlarms = scheduledAlarms
      .map(toPublicScheduledAlarm)
      .sort((left, right) => left.fireAt.localeCompare(right.fireAt));

    return {
      status: started ? "running" : "stopped",
      deliveryMode: "application-process",
      generatedAt: now().toISOString(),
      scheduledAlarms: publicAlarms,
      nextAlarm: publicAlarms[0] ?? null,
      recentNotifications,
      extensions: extensionHost.getState(),
    };
  }

  function triggerTestAlarm(courseId) {
    const courses = listCourses();
    const course =
      courses.find((candidate) => candidate.id === courseId) ??
      courses.find((candidate) => candidate.id === scheduledAlarms[0]?.courseId) ??
      courses[0];

    if (!course) {
      throw new Error("No course is available for a test alarm.");
    }

    const displayData = getSafeAlarmDisplayData(
      course,
      displayFormatter,
    );

    return recordNotification(displayData, course, "test");
  }

  function onNotification(listener) {
    events.on("notification", listener);
    return () => events.off("notification", listener);
  }

  return {
    addCourse,
    executeExtension: extensionHost.execute,
    reloadExtensions: extensionHost.reload,
    getSnapshot,
    importCourses,
    listCourses,
    onNotification,
    removeCourse,
    reschedule,
    start,
    stop,
    toggleCourseRisk,
    triggerTestAlarm,
  };
}
