# Project Darwin — MVP Scaffold (Timetable Alarm App)

This is the first physical version of the locked/evolvable split. It's deliberately
small — one Claude call plays "central agent + module agent," triage is a simple
rule, and there's no resolver or misuse-check pipeline yet. The point of this version
is to test whether the *shape* of the architecture (contracts, diffs, logs) holds up
against a real build, not to be feature-complete.

Architectural lessons from each implementation step are recorded in
[`docs/learning-log.md`](docs/learning-log.md). Every meaningful change should update
that log with:

1. What the change teaches the system.
2. How the lesson was implemented and verified.
3. How the lesson transfers to similar features, applications, or domains.

## Folder structure

```
locked/                  # Never touched by evolution requests, ever
  core-data/             # Course schema, the only source of truth for timetable data
  alarm-engine/          # The scheduling/firing logic itself
  config/                # Env vars, API keys, build config

evolvable/                # What evolution requests are allowed to touch
  ui/                     # Presentation only — layout, colors, labels, toggles
  features/               # Additive capability — new views, new rules, new widgets
  preferences/             # Per-user settings that don't touch shared/core data

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
```

## The rule that matters most

**Nothing in `evolvable/` may write to `locked/core-data` directly.** If a feature
needs core data, it reads through a defined accessor (see `locked/core-data/access.js`),
never by importing the schema or database client directly. That one rule is what
makes the fast-path/full-path triage in `server/triage.py` actually checkable —
it's a static import-graph check, not a judgment call.

The dependency boundary also works in the other direction: **nothing in `locked/`
may import from `evolvable/`.** Locked modules expose stable injection points and
provide safe defaults. Evolvable modules may implement those interfaces, but a
missing, invalid, or failing implementation cannot prevent protected behavior from
running. The alarm engine follows this rule by accepting an optional display
formatter while retaining locked fallback display data.

## Fast path vs full path, MVP-sized

A request is fast-path eligible only if the generated diff:
- touches only files under `evolvable/ui/`
- adds/modifies no new fields in any `registry/contracts/*.json`
- contains no new imports of `locked/core-data` beyond the existing accessor

Anything else is full-path: the diff gets written to `server/pending/`, not applied,
and waits for you to review and merge it by hand. No resolver, no misuse-check yet —
that's intentionally deferred until there's a second user or real stakes.
