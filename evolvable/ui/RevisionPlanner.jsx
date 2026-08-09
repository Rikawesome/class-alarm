import React, { useState, useEffect } from 'react';
import { Calendar, Plus, Trash2, CheckCircle2 } from 'lucide-react';

export default function RevisionPlanner({ courses }) {
  const [revisions, setRevisions] = useState([]);
  const [topic, setTopic] = useState('');
  const [courseId, setCourseId] = useState(courses[0]?.id || '');
  const [date, setDate] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch('/api/extensions/revision-planner')
      .then(res => res.json())
      .then(data => { if (data.state) setRevisions(data.state); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!courseId && courses.length > 0) {
      setCourseId(courses[0].id);
    }
  }, [courses, courseId]);

  async function handleAdd(e) {
    e.preventDefault();
    if (!topic.trim() || !date || loading) return;
    setLoading(true);
    try {
      const res = await fetch('/api/extensions/revision-planner', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'add', input: { topic, courseId, date } }),
      });
      const data = await res.json();
      if (res.ok) {
        setRevisions(data.result);
        setTopic('');
        setDate('');
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleToggle(id) {
    const res = await fetch('/api/extensions/revision-planner', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'toggle', input: { id } }),
    });
    const data = await res.json();
    if (res.ok) setRevisions(data.result);
  }

  async function handleDelete(id) {
    const res = await fetch('/api/extensions/revision-planner', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'delete', input: { id } }),
    });
    const data = await res.json();
    if (res.ok) setRevisions(data.result);
  }

  const getCourseName = (cid) => {
    const c = courses.find(item => item.id === cid);
    return c ? c.name : 'General Study';
  };

  return (
    <div className="panel" style={{ marginTop: '20px' }}>
      <div className="panel-heading">
        <h2>Revision Planner</h2>
        <span className="count-badge">{revisions.length} sessions</span>
      </div>
      <div style={{ padding: '16px 20px' }}>
        <form onSubmit={handleAdd} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr auto', gap: '8px', marginBottom: '16px' }}>
          <input
            type="text"
            placeholder="Revision topic..."
            value={topic}
            onChange={e => setTopic(e.target.value)}
            style={{ padding: '8px 12px', border: '1px solid #cbd5e1', borderRadius: '6px', fontSize: '13px' }}
          />
          <select
            value={courseId}
            onChange={e => setCourseId(e.target.value)}
            style={{ padding: '8px 12px', border: '1px solid #cbd5e1', borderRadius: '6px', fontSize: '13px' }}
          >
            {courses.map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <input
            type="date"
            value={date}
            onChange={e => setDate(e.target.value)}
            style={{ padding: '8px 12px', border: '1px solid #cbd5e1', borderRadius: '6px', fontSize: '13px' }}
          />
          <button type="submit" className="primary-button small-button" disabled={loading} style={{ width: 'auto' }}>
            <Plus size={15} /> Schedule
          </button>
        </form>

        {revisions.length === 0 ? (
          <div className="empty-schedule">No revision sessions scheduled yet.</div>
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {revisions.map(r => (
              <li key={r.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: '#fafbfa', border: '1px solid #e5e9e7', borderRadius: '6px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1 }}>
                  <input
                    type="checkbox"
                    checked={r.completed}
                    onChange={() => handleToggle(r.id)}
                    style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                  />
                  <div>
                    <span style={{ fontSize: '13px', fontWeight: 600, textDecoration: r.completed ? 'line-through' : 'none', color: r.completed ? '#78817c' : 'inherit', display: 'block' }}>
                      {r.topic}
                    </span>
                    <small style={{ color: '#78817c', fontSize: '11px' }}>
                      {getCourseName(r.courseId)} &bull; {r.date}
                    </small>
                  </div>
                </div>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => handleDelete(r.id)}
                  style={{ width: '30px', height: '30px' }}
                  title="Delete session"
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
