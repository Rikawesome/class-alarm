import React from 'react';
import { Calendar, Clock } from 'lucide-react';

export default function TodayOverview({ courses, nextAlarm }) {
  const todayIndex = new Date().getDay();
  const todaysCourses = courses.filter(c => c.day_of_week === todayIndex);
  
  return (
    <div className="panel" style={{ marginTop: '20px' }}>
      <div className="panel-heading">
        <h2>Today at a Glance</h2>
        <span className="count-badge">{todaysCourses.length} courses today</span>
      </div>
      <div style={{ padding: '16px 20px' }}>
        {todaysCourses.length === 0 ? (
          <div className="empty-schedule">No courses scheduled for today. Enjoy your free time!</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '13px', color: '#252c28' }}>
              <Calendar size={16} color="#28745b" />
              <span>You have <strong>{todaysCourses.length}</strong> course(s) scheduled for today.</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '13px', color: '#252c28' }}>
              <Clock size={16} color="#28745b" />
              <span>Next upcoming: <strong>{nextAlarm ? `${nextAlarm.courseName} at ${nextAlarm.startTime || 'soon'}` : 'None remaining today'}</strong></span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
