import React, { useState, useRef, useEffect } from 'react';
import './ChatInterface.css';

export default function ChatInterface({ onProposal }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([
    { role: 'system', text: 'Ask me to evolve the app â€” e.g. "Add a countdown timer to each course row".' }
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
    
    // Add user message
    setMessages(m => [...m, { role: 'user', text }]);
    setLoading(true);
    
    // Add a temporary status message to show we're working
    const tempId = Date.now();
    setMessages(m => [...m, { role: 'status', text: 'Working on your request...', id: tempId }]);
    
    try {
      const res = await fetch('http://localhost:8000/evolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, auto_retry: true }), // Use auto_retry for self-healing
      });
      const data = await res.json();
      
      // Remove the temporary status message
      setMessages(m => m.filter(msg => msg.id !== tempId));
      
      if (!res.ok) {
        setMessages(m => [...m, { role: 'error', text: data.error || 'Server error.' }]);
      } else {
        // Handle different response types from the auto_retry endpoint
        if (data.status === 'pending_review') {
          // Success (either first attempt or after retries)
          const attemptCount = data.attempts || 1;
          if (attemptCount > 1) {
            setMessages(m => [...m, {
              role: 'status',
              text: "I've successfully implemented your request after " + attemptCount + " attempt(s). You can review the changes below."
            }]);
          } else {
            setMessages(m => [...m, { role: 'status', text: 'Your request has been successfully implemented!' }]);
          }
          
          // Show the proposal
          setMessages(m => [...m, {
            role: 'proposal',
            text: data.plan,
            id: data.id,
            path: data.path,
            files: data.files_touched,
            attempts: data.attempts,
            failure_chain: data.failure_chain
          }]);
          
          if (onProposal) onProposal(data);
        } else if (data.status === 'escalated') {
          // Escalated to developer
          let userMessage = '';
          if (data.classification === 'UNFIXABLE') {
            userMessage = "I've run into an issue that requires developer attention. The problem has been logged and the developers will look into it soon.";
          } else if (data.classification === 'RETRY_EXHAUSTED') {
            userMessage = "I've tried " + data.attempts + " times to fix the issue but couldn't succeed. The problem has been logged for the developers to address.";
          } else {
            userMessage = "I've encountered an unexpected issue. The developers have been notified and will look into it.";
          }
          
          setMessages(m => [...m, { role: 'status', text: userMessage }]);
          // Optionally, we can still show the proposal if there is one (though it failed validation)
          if (data.plan) {
            setMessages(m => [...m, {
              role: 'proposal',
              text: data.plan,
              id: data.id,
              path: data.path,
              files: data.files_touched,
              attempts: data.attempts,
              failure_chain: data.failure_chain
            }]);
          }
        } else if (data.status === 'promoted') {
          // Needs human approval as a full path proposal
          setMessages(m => [...m, {
            role: 'status',
            text: 'Your request requires a bigger change that needs approval. I\'ve flagged it for review. Once approved, you can apply it.'
          }]);
          setMessages(m => [...m, {
            role: 'proposal',
            text: data.plan,
            id: data.id,
            path: data.path,
            files: data.files_touched,
            attempts: data.attempts,
            failure_chain: data.failure_chain
          }]);
        } else {
          // Fallback for any other status
          setMessages(m => [...m, { role: 'proposal', text: data.plan, id: data.id, path: data.path, files: data.files_touched }]);
          if (onProposal) onProposal(data);
        }
      }
    } catch (err) {
      // Remove the temporary status message
      setMessages(m => m.filter(msg => msg.id !== tempId));
      setMessages(m => [...m, { role: 'error', text: 'Could not reach evolution server. Please try again later.' }]);
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
        âœ�������¦
      </button>
    );
  }

  return (
    <div className="chat-container">
      <div className="chat-header">
        <span>Evolution Chat</span>
        <button onClick={() => setOpen(false)} aria-label="Close chat">âœ•</button>
      </div>
      <div className="chat-messages">
        {messages.map((msg, i) => {
          // Determine the message role for styling
          const role = msg.role || 'system';
          return (
            <div key={i} className={"chat-msg chat-msg--" + role}>
              {msg.role === 'proposal' ? (
                <div>
                  <div className="chat-proposal-label">Proposal ({msg.path} path){msg.attempts && msg.attempts > 1 ? " (after " + msg.attempts + " attempt(s))" : ""}</div>
                  <div className="chat-proposal-plan">{msg.text}</div>
                  {msg.files?.length > 0 && (
                    <div className="chat-proposal-files">{msg.files.join(', ')}</div>
                  )}
                </div>
              ) : (
                <span>{msg.text}</span>
              )}
            </div>
          );
        })}
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
