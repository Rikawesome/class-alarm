import React, { useState } from 'react';

const DAYS = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];

export default function AddCourseModal({ onAdd, onClose }) {
  const [form, setForm] = useState({
    name: '',
    day_of_week: 1,
    start_time: '09:00',
    end_time: '10:00',
    recurrence: 'weekly',
  });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  function set(field, value) {
    setForm(f => ({ ...f, [field]: value }));
    setError('');
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      await onAdd({ ...form, day_of_week: Number(form.day_of_week) });
      onClose();
    } catch (err) {
      setError(err.message || 'Failed to add course.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-card">
        <h2 style={{ margin: '0 0 4px', fontSize: 18 }}>Add Course</h2>
        <p style={{ margin: '0 0 16px', color: '#6e7772', fontSize: 12 }}>Add a new course to your timetable.</p>
        {error && <div className="error-banner">{error}</div>}
        <form className="add-course-form" onSubmit={handleSubmit}>
          <label>
            Course name
            <input required value={form.name} onChange={e => set('name', e.target.value)} placeholder="e.g. Calculus" />
          </label>
          <label>
            Day
            <select value={form.day_of_week} onChange={e => set('day_of_week', e.target.value)}>
              {DAYS.map((d, i) => <option key={i} value={i}>{d}</option>)}
            </select>
          </label>
          <div className="time-row">
            <label>
              Start time
              <input type="time" required value={form.start_time} onChange={e => set('start_time', e.target.value)} />
            </label>
            <label>
              End time
              <input type="time" required value={form.end_time} onChange={e => set('end_time', e.target.value)} />
            </label>
          </div>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 4 }}>
            <button type="button" className="secondary-button small-button" onClick={onClose}>Cancel</button>
            <button type="submit" className="primary-button small-button" disabled={saving} style={{ width: 'auto' }}>
              {saving ? 'Adding...' : 'Add Course'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
