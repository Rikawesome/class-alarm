import React, { useState, useEffect, useCallback } from 'react';
import { BookOpen, Clock, AlarmClock, Zap, Plus, Sun, Moon, CheckSquare } from 'lucide-react';
import CourseList from './CourseList.jsx';
import AddCourseModal from './AddCourseModal.jsx';
import ApprovalModal from './ApprovalModal.jsx';
import ChatInterface from './ChatInterface.jsx';
import WeeklyGoals from './WeeklyGoals.jsx';
import RevisionPlanner from './RevisionPlanner.jsx';
import TodayOverview from './TodayOverview.jsx';

function LiveClock() {
  const [time, setTime] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="modern-live-clock">
      <div className="clock-icon-glow">
        <Clock size={16} />
      </div>
      <div className="clock-time-display">
        <span className="time-main">{time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
        <span className="time-date-sub">{time.toLocaleDateString([], { month: 'short', day: 'numeric' })}</span>
      </div>
    </div>
  );
}

export default function App() {
  const [courses, setCourses] = useState([]);
  const [runtime, setRuntime] = useState(null);
  const [error, setError] = useState('');
  const [testingCourseId, setTestingCourseId] = useState(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [pendingProposal, setPendingProposal] = useState(null);
  const [darkMode, setDarkMode] = useState(() => {
    return localStorage.getItem('class_alarm_theme') === 'dark';
  });

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark-theme');
      localStorage.setItem('class_alarm_theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark-theme');
      localStorage.setItem('class_alarm_theme', 'light');
    }
  }, [darkMode]);

  const applySnapshot = useCallback(({ courses: c, runtime: r }) => {
    if (c) setCourses(c);
    if (r) setRuntime(r);
  }, []);

  useEffect(() => {
    fetch('/api/bootstrap')
      .then(r => r.json())
      .then(applySnapshot)
      .catch(() => setError('Could not load data from server.'));
  }, [applySnapshot]);

  const refreshSnapshot = useCallback(() => {
    fetch('/api/bootstrap')
      .then(r => r.json())
      .then(applySnapshot)
      .catch(() => setError('The app changed, but the latest state could not be loaded.'));
  }, [applySnapshot]);

  useEffect(() => {
    const es = new EventSource('/api/events');
    es.addEventListener('alarm', e => {
      const data = JSON.parse(e.data);
      setRuntime(prev => prev ? {
        ...prev,
        recentNotifications: [data, ...(prev.recentNotifications || [])].slice(0, 20),
      } : prev);
    });
    return () => es.close();
  }, []);

  async function handleAddCourse(courseData) {
    const res = await fetch('/api/courses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(courseData),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to add course');
    applySnapshot(data);
  }

  async function handleDeleteCourse(courseId) {
    const res = await fetch('/api/courses/' + courseId, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) { setError(data.error || 'Delete failed'); return; }
    applySnapshot(data);
  }

  async function handleToggleRisk(courseId, risky) {
    const res = await fetch('/api/courses/' + courseId + '/risk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_risky: risky }),
    });
    const data = await res.json();
    if (!res.ok) { setError(data.error || 'Failed to update risk'); return; }
    applySnapshot(data);
  }

  async function handleTestAlarm(courseId) {
    setTestingCourseId(courseId);
    try {
      await fetch('/api/alarms/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ courseId }),
      });
    } finally {
      setTimeout(() => setTestingCourseId(null), 1800);
    }
  }

  const nextAlarm = runtime?.nextAlarm ?? null;
  const nextAlarmCourseId = nextAlarm?.courseId ?? null;
  const riskyCourses = courses.filter(c => c.is_risky);

  return (
    <div className="app-shell">
      <nav className="nav-rail">
        <div className="brand-lockup">
          <div className="brand-mark"><AlarmClock size={20} /></div>
          <span>
            <strong>Class Alarm</strong>
            <small>Project Darwin</small>
          </span>
        </div>
        <div className="primary-nav">
          <a className="nav-item active" href="#">
            <BookOpen size={16} /> Schedule
          </a>
        </div>
        <div className="core-status">
          <Zap size={14} />
          <span>
            <strong>Core locked</strong>
            <small>{runtime?.status ?? 'loading'}</small>
          </span>
        </div>
      </nav>

      <div className="app-main">
        <header className="topbar">
          <div>
            <p className="date-label">{new Date().toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })}</p>
            <h1>My Schedule</h1>
            <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#6e7772' }}>Stay ahead of every class.</p>
          </div>
          <div className="topbar-actions">
            <LiveClock />
            <button
              className="secondary-button"
              onClick={() => setDarkMode(!darkMode)}
              aria-label="Toggle dark mode"
              style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              {darkMode ? <Sun size={15} /> : <Moon size={15} />}
              {darkMode ? 'Light' : 'Dark'}
            </button>
            <button className="secondary-button" onClick={() => setShowAddModal(true)}>
              <Plus size={15} /> Add Course
            </button>
          </div>
        </header>

        <main className="workspace">
          {error && <div className="error-banner" onClick={() => setError('')}>{error}</div>}

          <div className="runtime-strip">
            <div className="runtime-stat">
              <AlarmClock size={18} />
              <span>
                <small>Next alarm</small>
                <strong>{nextAlarm ? nextAlarm.courseName : 'None scheduled'}</strong>
              </span>
            </div>
            <div className="runtime-stat">
              <BookOpen size={18} />
              <span>
                <small>Courses</small>
                <strong>{courses.length}</strong>
              </span>
            </div>
            <div className="runtime-stat">
              <Zap size={18} />
              <span>
                <small>Risk flagged</small>
                <strong>{riskyCourses.length}</strong>
              </span>
            </div>
            <div className="runtime-stat">
              <span className="runtime-badge">
                <span className="status-dot" />
                <span>
                  <small>Runtime</small>
                  <strong>{runtime?.status ?? 'connecting...'}</strong>
                </span>
              </span>
            </div>
          </div>

          <div className="panel">
            <div className="panel-heading">
              <h2>Timetable</h2>
              <div className="panel-actions">
                <span className="count-badge">{courses.length} courses</span>
                <button className="secondary-button small-button" onClick={() => setShowAddModal(true)}>
                  <Plus size={13} /> Add
                </button>
              </div>
            </div>
            <CourseList
              courses={courses}
              nextAlarmCourseId={nextAlarmCourseId}
              testingCourseId={testingCourseId}
              onTestAlarm={handleTestAlarm}
              onDeleteCourse={handleDeleteCourse}
              onToggleRisk={handleToggleRisk}
            />
          </div>

          <TodayOverview courses={courses} nextAlarm={nextAlarm} />
          <WeeklyGoals />
          <RevisionPlanner courses={courses} />
        </main>
      </div>

      {showAddModal && (
        <AddCourseModal onAdd={handleAddCourse} onClose={() => setShowAddModal(false)} />
      )}

      {pendingProposal && (
        <ApprovalModal
          proposal={pendingProposal}
          onApprove={() => {
            setPendingProposal(null);
            refreshSnapshot();
          }}
          onDismiss={() => setPendingProposal(null)}
        />
      )}

      <ChatInterface onProposal={proposal => {
        if (proposal.path === 'fast') {
          setPendingProposal(proposal);
        } else {
          setPendingProposal(proposal);
        }
      }} />
    </div>
  );
}
