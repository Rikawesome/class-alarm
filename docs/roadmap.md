# Project Darwin Roadmap

This is the session-independent plan for Project Darwin. Use it with:

- `README.md` for architecture and run instructions.
- `docs/learning-log.md` for lessons from completed work.
- `registry/modules.json` and each registered module's colocated `module.json`
  for active module boundaries.

## Product Thesis

Project Darwin explores software that is designed to evolve from the beginning.
Natural-language requests may add or modify capabilities, but only within declared
module boundaries and without compromising the protected core.

The timetable alarm is the first host application. It is intentionally small enough
to make architectural successes and failures visible.

Version 1 should demonstrate:

> A deliberately modular application gaining meaningful user-facing capabilities
> through natural language while mechanically preserving protected behavior and
> data.

## Architectural Invariants

1. Evolution requests never modify files under `locked/`.
2. Modules under `locked/` never import modules under `evolvable/`.
3. Evolvable modules never import modules under `locked/`; they use declared host
   APIs or injected interfaces.
4. Protected capabilities use narrow contracts or injection points.
5. Evolvable behavior cannot suppress protected fallback behavior.
6. The `app/` composition root is human-reviewed and controls how both sides connect.
7. Generated changes remain untrusted until boundaries, contracts, builds, and tests
   pass.
8. Every meaningful step updates `docs/learning-log.md`.

## Current State

### Step 1 - Protect the alarm boundary

Status: **Complete**

- Removed the alarm engine's direct dependency on evolvable risk logic.
- Added a stable formatter injection point and locked fallback behavior.
- Added tests preventing locked-to-evolvable imports.
- Added alarm-engine and risk-feature contracts.

### Step 2 - Establish a runnable seed application

Status: **Complete**

- Added persistent SQLite course storage and one-time sample seeding.
- Added protected scheduling with cancellable runtime metadata.
- Added a human-reviewed application composition layer.
- Added read-only course/runtime APIs and test-alarm delivery.
- Added a React timetable and notification interface.
- Added persistence, scheduler, API, boundary, and build verification.

Current commands:

```bash
npm run dev
npm test
npm run build
```

## Version 1 Roadmap

### Step 3 - Produce trustworthy change proposals

Status: **Complete**

- Replaced free-form output with validated Pydantic schemas using Google Gemini
  (configurable with `DARWIN_MODEL`; current default `gemini-3.5-flash-lite`).
- Made model identifier and API key configurable (`DARWIN_MODEL`, `GEMINI_API_KEY`).
- Required explicit plans, file operations, contract effects, and test effects.
- Added path traversal checks and explicit fast-path/full-path classification.
- Stored every proposal under a unique request ID in `server/pending/` without modifying working application files.
- Recorded generation failures in `logs/evolution-log.json`.
- Exposed proposals and health check endpoints through the evolution control plane server.

### Step 4 - Build deterministic validation gates

Status: **Next**

Goal:

Mechanically determine whether a proposal respects the architecture.

Deliverables:

- Validate changed paths against module ownership.
- Reject traversal and files outside the workspace.
- Reject modifications under `locked/`.
- Scan imports in both dependency directions.
- Compare changed interfaces with contracts.
- Run syntax checks, tests, and the production build.
- Produce a structured pass/fail validation report.

Acceptance criteria:

- A presentation-only UI change can pass.
- A direct database import from `evolvable/` is rejected.
- A locked scheduler modification is rejected.
- A broken build or protected test is rejected.

### Step 5 - Apply changes transactionally

Status: **Pending**

Goal:

Apply validated changes without risking the last known-good application.

Deliverables:

- Use structured file operations or a proper patch parser.
- Snapshot the pre-change state.
- Validate in isolation before replacing the working state.
- Restore the previous state after failed validation.
- Record before/after hashes and validation evidence.
- Keep high-risk proposals pending for human review.

Acceptance criteria:

- A valid fast-path UI change applies successfully.
- A failed change leaves the previous application recoverable.
- Every apply, rejection, and rollback appears in the evolution log.

### Step 6 - Add constrained evolvable persistence

Status: **Pending**

Goal:

Allow new personal capabilities to store data without accessing protected timetable
storage.

Deliverables:

- Create an evolvable personal-data capability.
- Define module-specific storage namespaces.
- Expose controlled read/write operations through the composition layer.
- Prevent modules from reading another module's private state.
- Version evolvable storage schemas.
- Add backup and rollback behavior for feature-owned data.

Acceptance criteria:

- An evolvable feature persists its records across restarts.
- It cannot modify or query the protected course database directly.
- Removing a feature does not damage timetable data.

### Step 7 - Evolve a weekly goals capability

Status: **Pending**

Target request:

> Add a weekly goals page.

Expected result:

- A new feature module and contract.
- Feature-owned persistent goal data.
- A view registered through a controlled UI extension point.
- Create, complete, and review weekly goals.
- No modification to protected scheduling or course storage.

Acceptance criteria:

- The feature is proposed, validated, reviewed or applied, and logged.
- Goal data survives restart.
- All protected baseline tests still pass.

### Step 8 - Evolve a revision planner capability

Status: **Pending**

Target request:

> Create a revision planner.

Expected result:

- Revision sessions reference courses through read-only IDs.
- Planning records use feature-owned storage.
- Suggestions cannot modify protected alarm timing.
- The view uses the same extension mechanism as weekly goals.

Acceptance criteria:

- The second feature needs fewer architectural changes than the first.
- Weekly goals and class alarms continue working.
- Cross-feature dependencies are declared and validated.

### Step 9 - Turn validated lessons into system policy

Status: **Pending**

Goal:

Convert proven lessons from documentation into inputs used by the evolution process.

Deliverables:

- Separate observations from validated policies.
- Store validated policies in a machine-readable format.
- Load relevant policies before generation and validation.
- Link each policy to the tests that established it.
- Version policy changes and detect contradictions.

Acceptance criteria:

- The evolution agent receives applicable policies automatically.
- Contradicting or removing a policy requires human review.
- The human-readable learning log remains understandable independently.

### Step 10 - Complete the Version 1 demonstration

Status: **Pending**

Demonstration sequence:

1. Start from the protected class-alarm baseline.
2. Apply a low-risk presentation evolution.
3. Add weekly goals.
4. Add a revision planner.
5. Reject an attempted protected-core modification.
6. Reject or roll back a change that breaks tests.
7. Show the complete proposal, validation, application, and failure history.

Version 1 is complete when:

- The application gains at least two meaningful capabilities.
- Protected alarm and course-data behavior remains intact.
- Successful and failed evolutions are reproducible.
- Every decision has contracts, validation evidence, and logs.
- The process does not rely on undocumented manual repair.

## Deferred Long-Term Scope

- Arbitrary module generation without predefined extension points.
- Autonomous protected-schema migrations.
- Multi-agent proposal, review, and conflict resolution.
- Runtime hot-loading.
- Cross-user evolution and feature marketplaces.
- Automatic contract negotiation.
- Production identity, authorization, and secret management.
- Remote synchronization and multi-device background alarms.
- General-purpose Darwin support for unrelated host applications.

## Working Agreement

To reduce unnecessary command output and session usage:

- Codex handles code analysis, file edits, architecture, and focused verification.
- The user normally runs dependency installation commands.
- The user normally runs routine Git commands such as status, add, commit, pull,
  push, branch creation, and tags.
- Codex provides Git Bash-compatible commands for those actions.
- Codex may run commands when their output is required for diagnosis or verification,
  or when the user explicitly asks.
- Generated databases, build output, screenshots, and server logs are not committed.

## Resuming In A New Session

Use this prompt:

> Read `docs/roadmap.md`, `docs/learning-log.md`, `README.md`,
> `registry/modules.json`, and every registered module's colocated `module.json`.
> Inspect the working tree, identify the first incomplete roadmap step, and
> continue without changing completed architectural invariants.

Before new implementation, confirm:

1. The current roadmap step.
2. The protected invariants affected by it.
3. The acceptance tests required to call it complete.
