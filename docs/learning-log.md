# Project Darwin Learning Log

This log records what each meaningful MVP change teaches us about constrained
software evolution. Update it in the same change as the code, contracts, and tests
so architectural decisions do not become detached from their evidence.

These notes are currently documentation for developers. They do not automatically
change the evolution agent's behavior. A later MVP step can turn validated lessons
into machine-readable policies that the agent loads before proposing changes.

## Entry Template

### YYYY-MM-DD - Change title

**1. What this teaches the system**

State the architectural lesson or newly established invariant.

**2. How we implemented it**

Record the concrete code, contract, validation, and test changes.

**3. How it applies elsewhere**

Explain how the lesson transfers to another feature, application, or domain.

---

## 2026-07-31 - Isolate alarm scheduling from evolvable display logic

**1. What this teaches the system**

Marking files as locked is not enough to protect them. Dependency direction must
also prevent protected modules from loading evolvable implementations directly.
Customization should enter through a narrow contract, and protected behavior must
retain a valid fallback when the customization fails.

This establishes the invariant that locked modules never import evolvable modules.
An evolvable alarm formatter may decide what an alarm says, but it cannot decide
whether or when the alarm fires.

**2. How we implemented it**

The alarm scheduler no longer imports the risk-flag feature. It accepts an optional
display formatter through dependency injection. A locked display boundary validates
the formatter's result and catches runtime errors, returning default alarm text when
the formatter is absent or invalid.

The alarm-engine contract now declares the injection point and its protected
invariants. Automated tests cover valid formatting, missing formatting, malformed
output, thrown errors, and the rule that no locked JavaScript module may import from
`evolvable/`.

**3. How it applies elsewhere**

The same pattern applies anywhere optional behavior surrounds critical behavior:

- A payment core may accept an evolvable receipt formatter without allowing it to
  control whether a charge succeeds.
- A health reminder may accept custom wording without allowing that customization
  to suppress the reminder.
- A workflow engine may accept evolvable dashboards while keeping state transitions
  inside its protected core.

The transferable rule is to inject optional policy or presentation behind a stable
contract, validate its output, and preserve a locked fallback.

---

## 2026-07-31 - Establish a runnable and persistent seed application

**1. What this teaches the system**

Safe evolution requires a concrete working state to preserve. Contracts alone cannot
show whether an evolution retained storage, scheduling, delivery, and user-facing
behavior. The baseline application therefore becomes the executable reference point
against which future changes are validated.

This step also establishes the composition-root pattern. Locked and evolvable
modules remain independent, while a small human-reviewed host is responsible for
wiring implementations together and deciding which protected capabilities are
available.

**2. How we implemented it**

The protected core now owns a file-backed SQLite database, creates the course table,
and inserts sample courses only when the table is empty. Course reads continue to
flow through the protected accessor. Automated tests modify the database between two
separate Node processes and verify that the modified value survives the restart.

The alarm engine now returns cancellable schedule metadata while retaining ownership
of timing and safe display fallback. The application runtime injects the evolvable
risk formatter, records delivered alarms, refreshes the schedule each day, and
exposes read-only state plus a test-alarm action through an HTTP API.

A React interface displays the weekly timetable, runtime state, next alarm, risk
flags, and recent deliveries. The interface receives data through the host API and
does not import protected storage or scheduling modules. Scheduler, persistence,
HTTP integration, module-boundary, and production-build checks provide the evidence
for this baseline.

**3. How it applies elsewhere**

The same baseline-first approach applies to other evolvable applications:

- A finance application needs a working ledger and reconciliation test before
  allowing reports or categorization rules to evolve.
- A health application needs a protected medication schedule and delivery record
  before allowing reminder wording or planning views to evolve.
- A project-management application needs stable task persistence and state
  transitions before allowing dashboards and planning modules to evolve.

The transferable rule is to make the protected behavior executable, persist its
state, expose it through narrow capabilities, and measure every later evolution
against that known-good baseline.



  ## 2026-07-31 - Refactor tests to enforce module boundaries and colocate with locked modules

  1. What this teaches the system

  The system now enforces a strict architectural boundary where locked modules (protected-core)
  must not import evolvable code. By moving tests into the locked module directories and updating
  import paths, we ensure that tests validate the locked modules' behavior without evolving
  dependencies, and we prevent accidental coupling to evolvable code. This establishes an
  invariant: locked modules are self-contained and only depend on other locked modules or node
  built-ins.

  2. How we implemented it

  - Moved test files from the root tests/ directory into the appropriate locked module
    directories:
      - tests/alarm-display.test.js → locked/alarm-engine/tests/alarm-display.test.js
      - tests/scheduler.test.js → locked/alarm-engine/tests/scheduler.test.js
      - tests/core-data.test.js → locked/core-data/tests/core-data.test.js

  - Created new test suites:
      - app/tests/application-server.test.js (integration test for the composed runtime and
        server)

      - governance/tests/dependency-boundaries.test.js (validates that no locked module imports
        evolvable code via a regex scan)

      - governance/tests/registry-integrity.test.js (ensures the module registry entries resolve
        to correct local contracts and have no duplicate contracts)

  - Updated import paths in app/runtime.js and app/server.js to use correct relative paths after
    moving the app source from data/app to app root.

  - Removed the old tests/ directory and the temporary data/app location.
  - All tests now pass, confirming the architectural constraints hold.

  3. How it applies elsewhere

  This pattern of colocating tests with the modules they test, especially for locked/core modules,
  can be applied to other subsystems (e.g., the evolution server, web shell, or UI features). For
  any module that has a strict evolution policy (locked or evolvable), placing its tests alongside
  its source encourages developers to think about the module's public contract and prevents tests
  from depending on unstable internals. Additionally, the governance test for dependency
  boundaries can be extended to enforce other constraints, such as forbidding certain imports or
  requiring specific file policies, making it a scalable guardrail for the architecture.
## 2026-07-31 - Ensure baseline completeness before testing software evolution

**1. What this teaches the system**

Evolution is meant for user-driven enhancements, customizations, and additive capabilities, not as a substitute for basic product usability. Treating core missing functionality (such as course creation or deletion) as an "evolution" misuses the architectural paradigm. A robust baseline application must be fully usable out-of-the-box for its core domain while keeping database access guarded by strict protected schema validation.

**2. How we implemented it**

We added validated `createCourse` and `deleteCourse` operations to the protected core (`locked/core-data/access.js`), complete with strict input checks for names, valid days (0–6), and 24-hour time formatting. The application composition root (`app/runtime.js` and `app/server.js`) exposed safe host endpoints (`POST /api/courses` and `DELETE /api/courses/:id`), which trigger automatic alarm rescheduling. The evolvable UI (`evolvable/ui/App.jsx` and `CourseList.jsx`) gained an interactive "Add class" modal and course deletion controls, communicating exclusively through the host API without directly importing database storage or schemas. Unit tests and production build verification confirm that core safety invariants and persistence remain fully intact.

**3. How it applies elsewhere**

This principle applies across all evolvable software architectures:
- A finance baseline must allow basic ledger transactions before testing custom reporting rules.
- A health reminder baseline must allow core medication management before testing custom motivation features.
- A project management baseline must allow basic task CRUD before testing automated workflow boards.

The transferable rule is to ensure the baseline satisfies its core product domain completeness safely through validated core accessors, ensuring that subsequent evolution cycles measure true capability growth rather than patching missing foundational features.

## 2026-07-31 - Produce trustworthy change proposals via structured Gemini validation gates

**1. What this teaches the system**

Natural language code evolution requires strict mechanical guardrails before proposals can touch code. Allowing unstructured LLM output risks unvalidated file modifications, path traversals, or accidental edits to protected core modules (`locked/`). By enforcing strict JSON schemas (via Pydantic) and zero-mutation proposal storage (`server/pending/`), generated changes remain completely untrusted until evaluated against boundaries and contracts.

**2. How we implemented it**

We integrated a configurable Google Gemini model using the Google GenAI SDK with structured response validation (`response_schema=ProposalOutput`). The current default is `gemini-3.5-flash-lite`, and deployments may override it with `DARWIN_MODEL`. The evolution server (`server/main.py`) validates requested file paths against path traversal attacks, evaluates fast-path vs. full-path eligibility, stores pending proposals in `server/pending/{id}.json`, records all successes and failures in `logs/evolution-log.json`, and leaves working application files untouched during generation. A comprehensive test suite (`server/tests/test_server.py`) verifies proposal generation, schema enforcement, failure logging, and inspection APIs.

---

## 2026-08-05 - Restore the registry as the proposal engine's source of truth

**1. What this teaches the system**

A module registry protects architectural boundaries only when every consumer loads
contracts through that registry. Keeping an obsolete secondary contract location in
code or documentation creates silent policy drift: the proposal engine can appear
healthy while receiving no actual module constraints.

**2. How we implemented it**

The evolution server now resolves every colocated `module.json` through
`registry/modules.json`, verifies that contract paths remain inside the workspace,
and checks that each contract identity matches its registry key. The generation
prompt now preserves the stronger rule that evolvable modules use declared
application APIs and never import from `locked/`.

The application, core-data, and evolution-server contracts were synchronized with
their implemented APIs. Roadmap and README references now point to the canonical
registry layout, and regression tests verify that all registered contracts are
loaded into the proposal prompt.

**3. How it applies elsewhere**

Any policy-driven system needs one canonical discovery mechanism. Authorization
rules, plugin manifests, schema registries, and deployment inventories become
unreliable when runtime code scans a stale directory or bypasses identity checks.
Consumers should resolve policy through the canonical index and fail explicitly
when indexed metadata is missing or inconsistent.

**3. How it applies elsewhere**

The same proposal-isolation pattern applies to any safe agentic architecture:
- An infrastructure automation agent must generate Terraform/Kubernetes change plans as inspectable review artifacts rather than applying live updates blindly.
- A database migration assistant must validate DDL statements against schema contracts before running migrations.
- A code refactoring copilot must output isolated unified diffs for review rather than modifying source files directly.

The transferable rule is to generate evolution requests as structured, reviewable artifacts with explicit validation schemas, keeping the working system immutable until review gates pass.

---

## 2026-08-05 - Step 5: Transactional Patch Application with Automatic Rollback

**1. What this teaches the system**

Validating a proposal in isolation is necessary, but applying it safely requires transactional execution. If a post-application check (syntax check, production build, or test suite) fails after file modifications, the system must atomically restore previous state rather than leaving the codebase in a broken state.

**2. How we implemented it**

We added `apply_proposal()` and the `POST /proposals/{request_id}/apply` endpoint to the evolution control plane (`server/main.py`). The implementation:
- Automatically validates the proposal against Step 4 gates.
- Snapshots target files before applying changes (`create`, `modify`, `delete`).
- Re-runs syntax verification (`node --check`), production bundle generation (`npm run build`), and the full test suite (`node --test`).
- Automatically rolls back workspace modifications and marks status as `rolled_back` if any check fails, or marks status as `applied` and logs success to `logs/evolution-log.json` if all checks pass.

**3. How it applies elsewhere**

Transactional deployment patterns with automatic rollback are standard in database migrations, container orchestration, and continuous deployment pipelines. Applying them to AI code generation ensures that automated self-evolution can never corrupt or break a stable runtime baseline.

---

## 2026-08-05 - Policy 001 & Upgraded Engineering Workflow Pipeline

**1. What this teaches the system**

AI code generation fails when treated as a single prompt-response black box. Generating isolated component files without mounting them in the composition root (`App.jsx`) results in functional "orphaned components" that compile successfully but fail to appear in the application. Furthermore, the core hypothesis shifts from *"Can AI generate software?"* to *"Can software evolution become an engineered workflow?"*

**2. How we implemented it**

- **Upgraded Evolution Pipeline**: Formalized the pipeline into distinct stages: `Intent -> Context Assembly -> Evolution Plan (Step 3A) -> Plan Validation -> Code Generation (Step 3B) -> Code Validation (Step 4) -> Transactional Apply (Step 5)`.
- **Policy 001**: Added explicit architectural policy: **"Any newly created file must be explicitly imported, mounted, or registered in an existing module or composition root. Orphaned files of any type are strictly forbidden."**
- **Evolution Planner Role**: The AI now acts as an Evolution Planner before writing any code, ensuring integration points and wiring paths are explicitly accounted for.

**3. How it applies elsewhere**

Engineering autonomous systems requires treating changes as multi-step compilation pipelines—intent analysis, architectural planning, static validation, isolated testing, and transactional deployment—rather than trusting raw LLM output.
