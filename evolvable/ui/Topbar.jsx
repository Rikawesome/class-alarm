import React, { useState, useEffect } from 'react';
import './Topbar.css';

export function Topbar() {
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

  return (
    <header className="schedule-topbar">
      <h1>Class Alarm Schedule</h1>
      <button 
        className="theme-toggle-btn" 
        onClick={() => setDarkMode(!darkMode)}
        aria-label="Toggle dark mode"
      >
        {darkMode ? '☀️ Light' : '🌙 Dark'}
      </button>
    </header>
  );
}