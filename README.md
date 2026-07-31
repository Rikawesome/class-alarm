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
will be connected when the patch-generation pipeline is implemented.

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
  config/                # Env vars, API keys, build config

app/                     # Human-reviewed composition root and HTTP host
                          # The only layer allowed to wire locked and evolvable modules

evolvable/                # What evolution requests are allowed to touch
  ui/                     # Presentation only — layout, colors, labels, toggles, interactive forms
  features/               # Additive capability — new views, new rules, new widgets
  preferences/             # Per-user settings that don't touch shared/core data

web/                      # Browser entry document; renders evolvable/ui

registry/
  contracts/              # One JSON file per evolvable module — what it owns,
                           # exposes, depends on. This is read before every
                           # evolution request; it's also what the fast/full
                           # path triage checks against.

server/                   # The evolution backend (FastAPI) — takes a request,
                           # loads the relevant contract(s), calls Claude, decides
                           # fast-path (auto-apply) vs full-path (write a diff,
                           # wait for manual review).

logs/
  evolution-log.json      # Every request, whether it was fast/full path, what
                           # was generated, and what happened. This is the "I wish
                           # this did X" journal, structured — feeds v0.3 later.

tests/                    # Protected-boundary, persistence, scheduler, and host tests
```

## The rules that matter most

1. **Baseline Completeness:** A robust baseline must be fully usable out-of-the-box for its core product domain. Core operations (such as course creation and deletion) are safely governed by validated accessors in `locked/core-data/access.js`, ensuring evolution tests true capability enhancements rather than patching missing core features.
2. **No Direct Core Writes from Evolvable Modules:** **Nothing in `evolvable/` may write to `locked/core-data` directly.** Evolvable UI and feature modules communicate through defined host APIs (`app/`), never by importing schemas or database clients directly.
3. **Locked Isolation:** **Nothing in `locked/` may import from `evolvable/`.** Locked modules expose stable injection points and provide safe defaults.

## Fast path vs full path, MVP-sized

A request is fast-path eligible only if the generated diff:
- touches only files under `evolvable/ui/`
- adds/modifies no new fields in any `registry/contracts/*.json`
- contains no new imports of `locked/core-data` beyond the existing accessor

Anything else is full-path: the diff gets written to `server/pending/`, not applied,
and waits for you to review and merge it by hand.
