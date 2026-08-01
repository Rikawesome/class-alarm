import {
  Activity,
  AlarmClock,
  Bell,
  BellRing,
  CalendarDays,
  CheckCircle2,
  Clock3,
  RefreshCw,
  ShieldCheck,
  Plus,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import CourseList from "./CourseList.jsx";
import { Topbar } from "./Topbar.jsx";

const DATE_FORMATTER = new Intl.DateTimeFormat(undefined, {
  weekday: "long",
  day: "numeric",
  month: "long",
});
const TIME_FORMATTER = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
});

async function requestJson(path, options) {
  const response = await fetch(path, {
    headers: {
      "content-type": "application/json",
    },
    ...options,
  });
  const body = await response.json();

  if (!response.ok) {
    throw new Error(body.error ?? "The request failed.");
  }

  return body;
}

function formatAlarmTime(value) {
  if (!value) {
    return "None scheduled";
  }

  return TIME_FORMATTER.format(new Date(value));
}

export default function App() {
  const [courses, setCourses] = useState([]);
  const [runtime, setRuntime] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [testingCourseId, setTestingCourseId] = useState(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [currentTime, setCurrentTime] = useState(new Date());
  const [toast, setToast] = useState(null);
  const [notificationPermission, setNotificationPermission] = useState(() => {
    if (!("Notification" in window)) {
      return "unsupported";
    }

    return Notification.permission;
  });
  const seenNotificationIds = useRef(new Set());

  const applyNotification = useCallback((notification, announce = true) => {
    if (seenNotificationIds.current.has(notification.id)) {
      return;
    }

    seenNotificationIds.current.add(notification.id);
    setRuntime((current) => {
      if (!current) {
        return current;
      }

      return {
        ...current,
        recentNotifications: [
          notification,
          ...current.recentNotifications,
        ].slice(0, 20),
      };
    });
    setToast(notification);

    if (
      announce &&
      "Notification" in window &&
      Notification.permission === "granted"
    ) {
      new Notification(notification.title, {
        body: notification.body,
      });
    }
  }, []);

  const loadState = useCallback(async ({ quiet = false } = {}) => {
    if (quiet) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    try {
      const data = await requestJson("/api/bootstrap");
      setCourses(data.courses);
      setRuntime(data.runtime);
      setError("");

      for (const notification of data.runtime.recentNotifications) {
        seenNotificationIds.current.add(notification.id);
      }
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadState();

    const clockTimer = window.setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);
    const events = new EventSource("/api/events");

    events.addEventListener("alarm", (event) => {
      applyNotification(JSON.parse(event.data));
    });
    events.addEventListener("error", () => {
      setError("Alarm event connection interrupted.");
    });
    events.addEventListener("open", () => {
      setError("");
    });

    return () => {
      window.clearInterval(clockTimer);
      events.close();
    };
  }, [applyNotification, loadState]);

  useEffect(() => {
    if (!toast) {
      return undefined;
    }

    const toastTimer = window.setTimeout(() => setToast(null), 5000);
    return () => window.clearTimeout(toastTimer);
  }, [toast]);

  const nextAlarmCourseId = runtime?.nextAlarm?.courseId ?? null;
  const nextAlarmCourse = useMemo(
    () => courses.find((course) => course.id === nextAlarmCourseId) ?? courses[0],
    [courses, nextAlarmCourseId],
  );


  async function handleAddCourse(event) {
    event.preventDefault();
    const formData = new FormData(event.target);
    try {
      const data = await requestJson("/api/courses", {
        method: "POST",
        body: JSON.stringify({
          name: formData.get("name"),
          day_of_week: Number(formData.get("day_of_week")),
          start_time: formData.get("start_time"),
          end_time: formData.get("end_time"),
        }),
      });
      setCourses(data.courses);
      setRuntime(data.runtime);
      setShowAddModal(false);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleDeleteCourse(courseId) {
    try {
      const data = await requestJson(`/api/courses/${courseId}`, {
        method: "DELETE",
      });
      setCourses(data.courses);
      setRuntime(data.runtime);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleToggleRisk(courseId, isRisky) {
    try {
      const data = await requestJson(`/api/courses/${courseId}/risk`, {
        method: "POST",
        body: JSON.stringify({ is_risky: isRisky }),
      });
      setCourses(data.courses);
      setRuntime(data.runtime);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  async function triggerTestAlarm(courseId) {
    setTestingCourseId(courseId ?? "next");

    try {
      const data = await requestJson("/api/alarms/test", {
        method: "POST",
        body: JSON.stringify({ courseId }),
      });
      applyNotification(data.notification);
      setError("");
    } catch (testError) {
      setError(testError.message);
    } finally {
      setTestingCourseId(null);
    }
  }

  async function enableDesktopAlerts() {
    if (!("Notification" in window)) {
      setNotificationPermission("unsupported");
      return;
    }

    const permission = await Notification.requestPermission();
    setNotificationPermission(permission);
  }

  const desktopAlertsLabel =
    notificationPermission === "granted"
      ? "Desktop alerts on"
      : "Enable desktop alerts";

  return (
    <div className="app-shell">
      <aside className="nav-rail">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            <AlarmClock size={23} strokeWidth={2.2} />
          </span>
          <span>
            <strong>Darwin</strong>
            <small>Class Alarm</small>
          </span>
        </div>

        <nav className="primary-nav" aria-label="Primary navigation">
          <a className="nav-item active" href="#schedule">
            <CalendarDays size={18} />
            Schedule
          </a>
          <a className="nav-item" href="#activity">
            <Activity size={18} />
            Activity
          </a>
        </nav>

        <div className="core-status">
          <ShieldCheck size={19} />
          <span>
            <strong>Protected core</strong>
            <small>Boundary checks active</small>
          </span>
        </div>
      </aside>

      <div className="app-main">
        <Topbar />
        <header className="topbar">
          <div>
            <p className="date-label">{DATE_FORMATTER.format(currentTime)}</p>
            <h1>Weekly timetable</h1>
          </div>

          <div className="topbar-actions">
            <span className="live-clock" aria-label="Current local time">
              <Clock3 size={17} />
              {TIME_FORMATTER.format(currentTime)}
            </span>
            <button
              className="icon-button"
              type="button"
              title="Refresh runtime state"
              aria-label="Refresh runtime state"
              disabled={refreshing}
              onClick={() => loadState({ quiet: true })}
            >
              <RefreshCw
                size={18}
                className={refreshing ? "spin" : undefined}
              />
            </button>
            <button
              className="secondary-button"
              type="button"
              disabled={notificationPermission === "granted"}
              onClick={enableDesktopAlerts}
            >
              {notificationPermission === "granted" ? (
                <CheckCircle2 size={18} />
              ) : (
                <Bell size={18} />
              )}
              {desktopAlertsLabel}
            </button>
          </div>
        </header>

        <main className="workspace">
          <section className="runtime-strip" aria-label="Alarm runtime status">
            <div className="runtime-stat">
              <span className="status-dot" aria-hidden="true" />
              <span>
                <small>Alarm runtime</small>
                <strong>{runtime?.status ?? "Connecting"}</strong>
              </span>
            </div>
            <div className="runtime-stat">
              <CalendarDays size={19} />
              <span>
                <small>Courses</small>
                <strong>{courses.length}</strong>
              </span>
            </div>
            <div className="runtime-stat">
              <BellRing size={19} />
              <span>
                <small>Scheduled today</small>
                <strong>{runtime?.scheduledAlarms.length ?? 0}</strong>
              </span>
            </div>
            <div className="runtime-stat next-alarm-stat">
              <Clock3 size={19} />
              <span>
                <small>Next alarm</small>
                <strong>{formatAlarmTime(runtime?.nextAlarm?.fireAt)}</strong>
              </span>
            </div>
          </section>

          {error ? (
            <div className="error-banner" role="alert">
              {error}
            </div>
          ) : null}

          <div className="content-grid">
            <section className="panel schedule-panel" id="schedule">
              <div className="panel-heading">
                <div>
                  <p className="section-label">Timetable</p>
                  <h2>Upcoming classes</h2>
                </div>
                <div className="panel-actions">
                  <button className="primary-button small-button" type="button" onClick={() => setShowAddModal(true)}>
                    <Plus size={16} />
                    Add class
                  </button>
                  <span className="count-badge">{courses.length} courses</span>
                </div>
              </div>

              {loading ? (
                <div className="loading-state">Loading timetable...</div>
              ) : (
                <CourseList
                  courses={courses}
                  nextAlarmCourseId={nextAlarmCourseId}
                  testingCourseId={testingCourseId}
                  onTestAlarm={triggerTestAlarm}
                  onDeleteCourse={handleDeleteCourse}
                  onToggleRisk={handleToggleRisk}
                />
              )}
            </section>

            <aside className="side-stack">
              <section className="panel alarm-panel">
                <div className="panel-heading compact">
                  <div>
                    <p className="section-label">Runtime</p>
                    <h2>Next alarm</h2>
                  </div>
                  <span className="runtime-badge">
                    <span className="status-dot" aria-hidden="true" />
                    Live
                  </span>
                </div>

                <div className="next-alarm-display">
                  <span className="alarm-time">
                    {formatAlarmTime(runtime?.nextAlarm?.fireAt)}
                  </span>
                  <strong>{runtime?.nextAlarm?.courseName ?? "No class queued"}</strong>
                  <span>
                    {runtime?.nextAlarm
                      ? DATE_FORMATTER.format(new Date(runtime.nextAlarm.fireAt))
                      : "Schedule is clear"}
                  </span>
                </div>

                <button
                  className="primary-button"
                  type="button"
                  disabled={!nextAlarmCourse || Boolean(testingCourseId)}
                  onClick={() => triggerTestAlarm(nextAlarmCourse?.id)}
                >
                  <BellRing size={18} />
                  {testingCourseId ? "Sending..." : "Send test alarm"}
                </button>
              </section>

              <section className="panel activity-panel" id="activity">
                <div className="panel-heading compact">
                  <div>
                    <p className="section-label">Delivery</p>
                    <h2>Recent activity</h2>
                  </div>
                  <Activity size={19} />
                </div>

                <div className="activity-list">
                  {runtime?.recentNotifications.length ? (
                    runtime.recentNotifications.map((notification) => (
                      <article className="activity-item" key={notification.id}>
                        <span
                          className={`activity-icon ${notification.source}`}
                          aria-hidden="true"
                        >
                          <Bell size={15} />
                        </span>
                        <span>
                          <strong>{notification.title}</strong>
                          <small>
                            {notification.source === "test" ? "Test" : "Scheduled"}
                            {" ? "}
                            {TIME_FORMATTER.format(
                              new Date(notification.deliveredAt),
                            )}
                          </small>
                        </span>
                      </article>
                    ))
                  ) : (
                    <div className="empty-activity">No alarms delivered yet.</div>
                  )}
                </div>
              </section>
            </aside>
          </div>
        </main>
      </div>

      {toast ? (
        <div className="alarm-toast" role="status" aria-live="polite">
          <span className="toast-icon" aria-hidden="true">
            <BellRing size={20} />
          </span>
          <span>
            <strong>{toast.title}</strong>
            <small>{toast.body}</small>
          </span>
        </div>
      ) : null}

      {showAddModal ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal-card">
            <div className="panel-heading">
              <div>
                <p className="section-label">Schedule</p>
                <h2>Add new class</h2>
              </div>
              <button className="secondary-button" type="button" onClick={() => setShowAddModal(false)}>
                Cancel
              </button>
            </div>
            <form onSubmit={handleAddCourse} className="add-course-form">
              <label>
                Course name
                <input type="text" name="name" required placeholder="e.g. Advanced Physics" />
              </label>
              <label>
                Day of week
                <select name="day_of_week" defaultValue="1">
                  <option value="0">Sunday</option>
                  <option value="1">Monday</option>
                  <option value="2">Tuesday</option>
                  <option value="3">Wednesday</option>
                  <option value="4">Thursday</option>
                  <option value="5">Friday</option>
                  <option value="6">Saturday</option>
                </select>
              </label>
              <div className="time-row">
                <label>
                  Start time
                  <input type="time" name="start_time" required defaultValue="09:00" />
                </label>
                <label>
                  End time
                  <input type="time" name="end_time" required defaultValue="10:30" />
                </label>
              </div>
              <button className="primary-button" type="submit">
                Save and schedule alarm
              </button>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}
