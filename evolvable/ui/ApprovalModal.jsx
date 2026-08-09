import React, { useState } from 'react';

export default function ApprovalModal({ proposal, onApprove, onDismiss }) {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');

  async function handleApprove() {
    setLoading(true);
    setError('');
    try {
      const approveRes = await fetch('http://localhost:8000/proposals/' + proposal.id + '/approve', { method: 'POST' });
      if (!approveRes.ok) throw new Error('The evolution could not be approved safely.');
      const applyRes = await fetch('http://localhost:8000/proposals/' + proposal.id + '/apply', { method: 'POST' });
      const applyData = await applyRes.json();
      if (!applyRes.ok || !applyData.success) throw new Error('The evolution could not take root. ' + (applyData.error || 'Please review the proposal and try again.'));
      setStatus('applied');
      if (onApprove) onApprove(applyData);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && onDismiss()}>
      <div className="modal-card">
        <h2 style={{ margin: '0 0 4px', fontSize: 18 }}>Approve Evolution Proposal</h2>
        <p style={{ margin: '0 0 4px', color: '#6e7772', fontSize: 12 }}>Path: <strong>{proposal.path}</strong></p>

        <div style={{ margin: '12px 0', padding: '12px 14px', background: '#f3f8f5', borderRadius: 8, fontSize: 13, lineHeight: 1.6 }}>
          {proposal.plan}
        </div>

        {proposal.files_touched?.length > 0 && (
          <div style={{ marginBottom: 14, fontSize: 12, color: '#57615c' }}>
            Files: {proposal.files_touched.join(', ')}
          </div>
        )}

        {error && <div className="error-banner">{error}</div>}

        {status === 'applied' ? (
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button className="primary-button small-button" style={{ width: 'auto' }} onClick={onDismiss}>Done</button>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button className="secondary-button small-button" onClick={onDismiss} disabled={loading}>Dismiss</button>
            <button className="primary-button small-button" style={{ width: 'auto' }} onClick={handleApprove} disabled={loading}>
              {loading ? 'Helping it take root…' : 'Approve & Apply'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
