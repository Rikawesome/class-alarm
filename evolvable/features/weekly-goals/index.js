export function createExtension({ moduleId, capabilities: { personalStorage } }) {
  function getState() {
    return personalStorage.get('goals') || [];
  }

  function execute(action, input) {
    const goals = getState();
    if (action === 'add') {
      const newGoal = { id: 'goal_' + Date.now(), title: input.title, completed: false };
      const updated = [...goals, newGoal];
      personalStorage.set('goals', updated);
      return updated;
    }
    if (action === 'toggle') {
      const updated = goals.map(g => g.id === input.id ? { ...g, completed: !g.completed } : g);
      personalStorage.set('goals', updated);
      return updated;
    }
    if (action === 'delete') {
      const updated = goals.filter(g => g.id !== input.id);
      personalStorage.set('goals', updated);
      return updated;
    }
    return goals;
  }

  return { getState, execute };
}
