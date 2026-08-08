const defaultFlaggedCourseIds = new Set(["course-systems-design"]);

export function createRiskFlag({ storage } = {}) {
  function isRisky(courseId) {
    if (!storage) return defaultFlaggedCourseIds.has(courseId);
    const record = storage.get(`course-${courseId}`);
    return record?.isRisky ?? courseId === "course-systems-design";
  }

  function setRisky(courseId, risky) {
    if (!storage) {
      if (risky) defaultFlaggedCourseIds.add(courseId);
      else defaultFlaggedCourseIds.delete(courseId);
      return;
    }
    if (risky) storage.set(`course-${courseId}`, { isRisky: true });
    else storage.delete(`course-${courseId}`);
  }

  function getAlarmDisplayData(course) {
    return {
      title: course.name,
      body: isRisky(course.id)
        ? `Risky to skip - ${course.name} now`
        : `${course.name} now`,
    };
  }

  return { getAlarmDisplayData, isRisky, setRisky };
}

const defaultRiskFlag = createRiskFlag();
export const { getAlarmDisplayData, isRisky, setRisky } = defaultRiskFlag;
