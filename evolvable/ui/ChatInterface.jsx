import React, { useState, useRef, useEffect } from 'react';
import { Sparkles, X } from 'lucide-react';
import './ChatInterface.css';

export default function ChatInterface({ onProposal, personalMode = false }) {
  const progressMessages = [
    'Listening to your idea…',
    'Tracing where this belongs…',
    'Checking the protected boundaries…',
    'Growing the new capability…',
    'Testing the evolution…',
    'Preparing it for your review…',
  ];
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([
    { role: 'system', text: 'Ask me to evolve the app - e.g. "Add a countdown timer to each course row".' }
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
    setMessages(m => [...m, { role: 'status', text: progressMessages[0], id: tempId }]);
    let progressIndex = 0;
    const progressTimer = setInterval(() => {
      progressIndex = (progressIndex + 1) % progressMessages.length;
      setMessages(m => m.map(msg =>
        msg.id === tempId ? { ...msg, text: progressMessages[progressIndex] } : msg,
      ));
    }, 2200);

    try {
      const userId = personalMode
        ? (localStorage.getItem('darwin_user_id') || (() => {
          const id = crypto.randomUUID();
          localStorage.setItem('darwin_user_id', id);
          return id;
        })())
        : null;
      const res = await fetch(personalMode ? 'http://localhost:8000/personal/evolve' : 'http://localhost:8000/evolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(userId ? { 'X-Darwin-User-Id': userId } : {}) },
        body: JSON.stringify({ text, auto_retry: true }),
      });
      const data = await res.json();

      // Remove the temporary status message
      setMessages(m => m.filter(msg => msg.id !== tempId));

      if (!res.ok) {
        setMessages(m => [...m, { role: 'error', text: 'This evolution could not safely take root. ' + (data.error || 'Please try a different request.') }]);
      } else {
        // Personal requests return a validated draft artifact.
        if (data.status === 'draft') {
          setMessages(m => [...m, {
            role: 'proposal',
            text: 'A private artifact is ready for your approval.',
            id: data.artifact?.artifact_id,
            scope: 'personal',
            target: data.branch?.user_id,
            artifact: data.artifact,
          }]);
          if (onProposal) onProposal({ ...data, id: data.artifact?.artifact_id, scope: 'personal', path: 'personal' });
        } else if (data.status === 'pending_review') {
          // Success (either first attempt or after retries)
          const attemptCount = data.attempts || 1;
          if (attemptCount > 1) {
            setMessages(m => [...m, {
              role: 'status',
              text: "I've successfully implemented your request after " + attemptCount + " attempt(s). You can review the changes below."
            }]);
          } else {
            setMessages(m => [...m, { role: 'status', text: 'The evolution is ready for your review.' }]);
          }

          // Show the proposal
          setMessages(m => [...m, {
            role: 'proposal',
            text: data.plan,
            id: data.id,
            path: data.path,
            files_touched: data.files_touched,
            scope: data.scope,
            target: data.target,
            validation: data.validation,
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
              files_touched: data.files_touched,
              scope: data.scope,
              target: data.target,
              attempts: data.attempts,
              failure_chain: data.failure_chain
            }]);
          }
        } else if (data.status === 'promoted') {
          // Needs human approval as a full path proposal
          setMessages(m => [...m, {
            role: 'status',
            text: "Your request requires a bigger change that needs approval. I've flagged it for review. Once approved, you can apply it."
          }]);
          setMessages(m => [...m, {
            role: 'proposal',
            text: data.plan,
            id: data.id,
            path: data.path,
            files_touched: data.files_touched,
            scope: data.scope,
            target: data.target,
            attempts: data.attempts,
            failure_chain: data.failure_chain
          }]);
          if (onProposal) onProposal(data);
        } else {
          // Fallback for any other status
          setMessages(m => [...m, { role: 'proposal', text: data.plan, id: data.id, path: data.path, files_touched: data.files_touched, scope: data.scope, target: data.target }]);
          if (onProposal) onProposal(data);
        }
      }
    } catch (err) {
      // Remove the temporary status message
      setMessages(m => m.filter(msg => msg.id !== tempId));
          setMessages(m => [...m, { role: 'error', text: 'The evolution server is out of reach right now. Please try again in a moment.' }]);
    } finally {
      clearInterval(progressTimer);
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
        <Sparkles size={22} />
      </button>
    );
  }

  return (
    <div className="chat-container">
      <div className="chat-header">
        <span>Evolution Chat</span>
        <button onClick={() => setOpen(false)} aria-label="Close chat">
          <X size={16} />
        </button>
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
                  {msg.artifact && <div className="chat-proposal-files">{msg.artifact.manifest_json}</div>}
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
