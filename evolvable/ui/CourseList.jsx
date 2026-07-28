// EVOLVABLE MODULE — presentation only. This is the safest fast-path
// territory: color, layout, labels can all change here without touching
// any shared or persisted data. No import of locked/core-data/schema.js
// or a raw db client is allowed here — only the accessor, and only if
// a feature genuinely needs it for display.

import { isRisky } from "../features/risk-flag/index.js";

export default function CourseList({ courses }) {
  return (
    <ul className="course-list">
      {courses.map((course) => (
        <li key={course.id} className={isRisky(course.id) ? "risky" : ""}>
          {course.name} — {course.start_time}
        </li>
      ))}
    </ul>
  );
}
