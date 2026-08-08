# Project Darwin — Runnable MVP Baseline

Project Darwin starts with a fully functional, interactive timetable alarm application whose protected behavior is separated from the modules that may evolve later. The current baseline persists courses, supports adding and deleting timetable entries with strict core schema validation, schedules alarms while the application process is running, and exposes a browser interface for timetable management, risk flags, and notification state.

## Run the application

Requirements: Node.js 24 or newer.

```bash
npm install
npm run dev
```

Open `http://127.0.0.1:4173`.

```bash
npm test
npm run build
```

The Python evolution backend is not required to run the baseline application. It
provides the separate proposal, validation, approval, and application control
plane when its dependencies and API key are configured.

Architectural lessons from each implementation step are recorded in
[`docs/learning-log.md`](docs/learning-log.md). Every meaningful change should update
that log with:

1. What the change teaches the system.
2. How the lesson was implemented and verified.
3. How the lesson transfers to similar features, applications, or domains.

## Folder structure

```
locked/                  # Never touched by evolution requests, ever
  core-data/             # Course schema and validated core accessors (CRUD)
  alarm-engine/          # The scheduling/firing logic itself
  personal-data/         # Feature-private persistence host and capabilities
  config/                # Env vars, API keys, build config

app/                     # Human-reviewed composition root and HTTP host
                          # The only layer allowed to wire locked and evolvable modules

evolvable/                # What evolution requests are allowed to touch
  ui/                     # Presentation only — layout, colors, labels, toggles, interactive forms
  features/               # Additive capability — new views, new rules, new widgets
  preferences/             # Per-user settings that don't touch shared/core data

web/                      # Browser entry document; renders evolvable/ui

registry/
  modules.json            # Canonical module index: ownership, contract paths,
                           # evolution policy, and governed artifacts.

*/module.json             # Colocated contract for each registered module —
                           # what it owns, exposes, depends on, and protects.

server/                   # The Starlette evolution control plane — loads canonical
                           # contracts, calls Gemini, validates structured output,
                           # and stores proposals without modifying application files.

logs/
  evolution-log.json      # Every request, whether it was fast/full path, what
                           # was generated, and what happened. This is the "I wish
                           # this did X" journal, structured — feeds v0.3 later.

*/tests/                  # Colocated protected-boundary, persistence, scheduler,
                           # host, governance, and evolution-server tests.
```

## The rules that matter most

1. **Baseline Completeness:** A robust baseline must be fully usable out-of-the-box for its core product domain. Core operations (such as course creation and deletion) are safely governed by validated accessors in `locked/core-data/access.js`, ensuring evolution tests true capability enhancements rather than patching missing core features.
2. **No Protected Imports from Evolvable Modules:** **Nothing in `evolvable/` may import from `locked/`.** Evolvable UI and feature modules communicate through defined host APIs (`app/`) or implement narrow interfaces injected by the composition root.
3. **Locked Isolation:** **Nothing in `locked/` may import from `evolvable/`.** Locked modules expose stable injection points and provide safe defaults.

## Fast path vs full path, MVP-sized

A request is fast-path eligible only if the generated proposal:
- touches only files under `evolvable/ui/`
- changes only stylesheets (`.css`, `.scss`, `.sass`, or `.less`)
- modifies no colocated `module.json` contract
- contains no unresolved or protected-boundary imports

Anything else is full-path. Both paths create reviewable artifacts under
`server/pending/`. Fast-path proposals use structural and governance checks;
code-changing proposals use isolated syntax, build, and test validation.
Transactional application and rollback are implemented in the evolution server.

## The Upgraded Evolution Pipeline (Engineered Workflow)

Project Darwin shifts the focus from *"Can AI generate software?"* to *"Can software evolution become an engineered workflow?"*

The complete evolution pipeline follows these stages:
1. **Intent**: Natural-language evolution request from the user/client.
2. **Context Assembly**: The evolution engine scopes the request to specific modules using `registry/modules.json` and injects relevant file context (e.g., `App.jsx`, target components).
3. **Step 3A (Evolution Plan)**: The AI acts as an Evolution Planner, drafting a structured multi-file change strategy.
4. **Plan Validation**: Inspects the plan against architectural invariants and module boundaries.
5. **Step 3B (Code Proposal)**: Generates precise operations (`create`, `modify`, `delete`) matching the validated plan.
6. **Code Validation (Step 4)**: Deterministic validation gates check path safety, ownership, dependency imports, and content integrity. Code-changing proposals additionally run isolated syntax (`node --check`), test suite (`node --test`), and production build (`npm run build`) checks.
7. **Transactional Apply (Step 5)**: Atomically applies the validated change with automatic rollback on post-application failure.
