import React, { useState, useRef, useEffect } from 'react';
import './ChatInterface.css';

export default function ChatInterface({ onProposal }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([
    { role: 'system', text: 'Ask me to evolve the app — e.g. "Add a countdown timer to each course row".' }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function handleSend(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    setMessages(m => [...m, { role: 'user', text }]);
    setLoading(true);
    try {
      const res = await fetch('http://localhost:8000/evolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessages(m => [...m, { role: 'error', text: data.error || 'Server error.' }]);
      } else {
        setMessages(m => [...m, {
          role: 'proposal',
          text: data.plan,
          id: data.id,
          path: data.path,
          files: data.files_touched,
        }]);
        if (onProposal) onProposal(data);
      }
    } catch (err) {
      setMessages(m => [...m, { role: 'error', text: 'Could not reach evolution server.' }]);
    } finally {
      setLoading(false);
    }
  }

  if (!open) {
    return (
      <button
        className="chat-fab"
        onClick={() => setOpen(true)}
        title="Open Evolution Chat"
        aria-label="Open evolution chat"
      >
        ✦
      </button>
    );
  }

  return (
    <div className="chat-container">
      <div className="chat-header">
        <span>Evolution Chat</span>
        <button onClick={() => setOpen(false)} aria-label="Close chat">✕</button>
      </div>
      <div className="chat-messages">
        {messages.map((msg, i) => (
          <div key={i} className={"chat-msg chat-msg--" + msg.role}>
            {msg.role === 'proposal' ? (
              <div>
                <div className="chat-proposal-label">Proposal ({msg.path} path)</div>
                <div className="chat-proposal-plan">{msg.text}</div>
                {msg.files?.length > 0 && (
                  <div className="chat-proposal-files">{msg.files.join(', ')}</div>
                )}
              </div>
            ) : (
              <span>{msg.text}</span>
            )}
          </div>
        ))}
        {loading && <div className="chat-msg chat-msg--system">Thinking...</div>}
        <div ref={bottomRef} />
      </div>
      <form className="chat-input-row" onSubmit={handleSend}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Describe a change..."
          disabled={loading}
          autoFocus
        />
        <button type="submit" disabled={loading || !input.trim()}>Send</button>
      </form>
    </div>
  );
}
