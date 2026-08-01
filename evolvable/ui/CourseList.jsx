// EVOLVABLE MODULE - presentation only. It receives course data from the
// application API and never imports protected storage or scheduling code.

import { AlertTriangle, Bell, Clock3, LoaderCircle, Trash2 } from "lucide-react";
import { isRisky } from "../features/risk-flag/index.js";

const DAY_NAMES = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

function getMinutes(time) {
  const [hour, minute] = time.split(":").map(Number);
  return hour * 60 + minute;
}

function getCourseDistance(course, now) {
  const dayDistance = (course.day_of_week - now.getDay() + 7) % 7;
  const currentMinutes = now.getHours() * 60 + now.getMinutes();
  let distance = dayDistance * 24 * 60 + getMinutes(course.start_time);

  if (dayDistance === 0) {
    distance -= currentMinutes;

    if (distance < 0) {
      distance += 7 * 24 * 60;
    }
  }

  return distance;
}

function getDayLabel(course, now) {
  const dayDistance = (course.day_of_week - now.getDay() + 7) % 7;

  if (dayDistance === 0) {
    return "Today";
  }

  if (dayDistance === 1) {
    return "Tomorrow";
  }

  return DAY_NAMES[course.day_of_week];
}

export default function CourseList({
  courses,
  nextAlarmCourseId,
  testingCourseId,
  onTestAlarm,
  onDeleteCourse,
  onToggleRisk,
}) {
  const now = new Date();
  const sortedCourses = [...courses].sort(
    (left, right) =>
      getCourseDistance(left, now) - getCourseDistance(right, now),
  );

  if (sortedCourses.length === 0) {
    return <div className="empty-schedule">No courses in the timetable.</div>;
  }

  return (
    <div className="course-table">
      <div className="course-table-header" aria-hidden="true">
        <span>Course</span>
        <span>Day</span>
        <span>Time</span>
        <span>Status</span>
        <span />
      </div>
      <ul className="course-list">
        {sortedCourses.map((course) => {
          const risky = course.is_risky ?? isRisky(course.id);
          const isNext = course.id === nextAlarmCourseId;
          const isTesting = testingCourseId === course.id;

          return (
            <li
              key={course.id}
              className={`course-row${isNext ? " next" : ""}`}
            >
              <div className="course-name-cell">
                <span
                  className={`course-swatch swatch-${course.day_of_week}`}
                  aria-hidden="true"
                />
                <span>
                  <strong>{course.name}</strong>
                  <small>{isNext ? "Next alarm" : course.recurrence}</small>
                </span>
              </div>
              <span className="course-day">{getDayLabel(course, now)}</span>
              <span className="course-time">
                <Clock3 size={15} />
                {course.start_time}–{course.end_time}
              </span>
              <span>
                <button
                  type="button"
                  className={risky ? "risk-badge interactive-badge" : "standard-status interactive-badge"}
                  title="Click to toggle risk flag"
                  onClick={() => onToggleRisk(course.id, !risky)}
                >
                  {risky ? (
                    <>
                      <AlertTriangle size={14} />
                      Risk flag
                    </>
                  ) : (
                    "Standard"
                  )}
                </button>
              </span>
              <div className="row-actions">
                <button
                  className="icon-button course-test-button"
                  type="button"
                  title={`Send test alarm for ${course.name}`}
                  aria-label={`Send test alarm for ${course.name}`}
                  disabled={Boolean(testingCourseId)}
                  onClick={() => onTestAlarm(course.id)}
                >
                  {isTesting ? (
                    <LoaderCircle className="spin" size={17} />
                  ) : (
                    <Bell size={17} />
                  )}
                </button>
                <button
                  className="icon-button course-delete-button"
                  type="button"
                  title={`Delete ${course.name}`}
                  aria-label={`Delete ${course.name}`}
                  disabled={Boolean(testingCourseId)}
                  onClick={() => onDeleteCourse(course.id)}
                >
                  <Trash2 size={17} />
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
