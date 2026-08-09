import React, { useState, useEffect } from 'react';
import { CheckSquare, Plus, Trash2 } from 'lucide-react';

export default function WeeklyGoals() {
  const [goals, setGoals] = useState([]);
  const [title, setTitle] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch('/api/extensions/weekly-goals')
      .then(res => res.json())
      .then(data => { if (data.state) setGoals(data.state); })
      .catch(() => {});
  }, []);

  async function handleAdd(e) {
    e.preventDefault();
    if (!title.trim() || loading) return;
    setLoading(true);
    try {
      const res = await fetch('/api/extensions/weekly-goals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'add', input: { title } }),
      });
      const data = await res.json();
      if (res.ok) {
        setGoals(data.result);
        setTitle('');
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleToggle(id) {
    const res = await fetch('/api/extensions/weekly-goals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'toggle', input: { id } }),
    });
    const data = await res.json();
    if (res.ok) setGoals(data.result);
  }

  async function handleDelete(id) {
    const res = await fetch('/api/extensions/weekly-goals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'delete', input: { id } }),
    });
    const data = await res.json();
    if (res.ok) setGoals(data.result);
  }

  return (
    <div className="panel" style={{ marginTop: '20px' }}>
      <div className="panel-heading">
        <h2>Weekly Goals</h2>
        <span className="count-badge">{goals.length} goals</span>
      </div>
      <div style={{ padding: '16px 20px' }}>
        <form onSubmit={handleAdd} style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
          <input
            type="text"
            placeholder="Add a new goal..."
            value={title}
            onChange={e => setTitle(e.target.value)}
            style={{ flex: 1, padding: '8px 12px', border: '1px solid #cbd5e1', borderRadius: '6px', fontSize: '13px' }}
          />
          <button type="submit" className="primary-button small-button" disabled={loading} style={{ width: 'auto' }}>
            <Plus size={15} /> Add
          </button>
        </form>
        {goals.length === 0 ? (
          <div className="empty-schedule">No goals set for this week yet.</div>
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {goals.map(g => (
              <li key={g.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', background: '#fafbfa', border: '1px solid #e5e9e7', borderRadius: '6px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', flex: 1, textDecoration: g.completed ? 'line-through' : 'none', color: g.completed ? '#78817c' : 'inherit' }}>
                  <input
                    type="checkbox"
                    checked={g.completed}
                    onChange={() => handleToggle(g.id)}
                    style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                  />
                  <span style={{ fontSize: '13px', fontWeight: 500 }}>{g.title}</span>
                </label>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => handleDelete(g.id)}
                  style={{ width: '30px', height: '30px' }}
                  title="Delete goal"
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
