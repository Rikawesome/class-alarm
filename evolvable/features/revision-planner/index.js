export function createExtension({ moduleId, capabilities: { personalStorage } }) {
  function getState() {
    return personalStorage.get('revisions') || [];
  }

  function execute(action, input) {
    const revisions = getState();
    if (action === 'add') {
      const newRev = {
        id: 'rev_' + Date.now(),
        courseId: input.courseId,
        topic: input.topic,
        date: input.date,
        completed: false
      };
      const updated = [...revisions, newRev];
      personalStorage.set('revisions', updated);
      return updated;
    }
    if (action === 'toggle') {
      const updated = revisions.map(r => r.id === input.id ? { ...r, completed: !r.completed } : r);
      personalStorage.set('revisions', updated);
      return updated;
    }
    if (action === 'delete') {
      const updated = revisions.filter(r => r.id !== input.id);
      personalStorage.set('revisions', updated);
      return updated;
    }
    return revisions;
  }

  return { getState, execute };
}
