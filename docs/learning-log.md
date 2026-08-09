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

## 2026-08-09 - Complete the first end-to-end registered feature

**1. What this teaches the system**

Passing an extension contract and compiling a UI is not enough to prove that a
feature works. A complete evolution must connect the generated feature to the
visible UI and provide a generic host transport for its actions. Integration
metadata must be checked against actual proposed file content, not just against
`files_touched` declarations.

**2. How we implemented it**

The Weekly Goals request was generated, registered, approved, applied, and
refined through Darwin. The feature uses the generic `getState`/`execute`
runtime contract and namespace-bound personal storage. The application host now
serves generic `GET` and `POST /api/extensions/<module-id>` endpoints. The
evolution engine requires `ui_integration`, verifies that the declared UI entry
file renders the declared feature marker, and verifies applied files against the
approved operations. The full JavaScript suite passes 32 tests and the Python
server suite passes 21 tests.

**3. How it applies elsewhere**

Plugin, workflow, and automation systems should test the entire path from user
surface to capability host. A generated adapter that is visible but cannot reach
its action boundary is incomplete, just as a working backend with no rendered
entry point is incomplete. Generic transport and semantic integration gates
make those failures reusable and detectable for future features.

---

## 2026-08-09 - Separate extension registration from evolution authority

**1. What this teaches the system**

A generic loader is safe only when discovery, activation, entry selection, and
capability grants all come from protected metadata. A new module also needs a
trusted bootstrap transaction: ordinary evolution cannot be allowed to create
its own registry authority, but human approval must be able to establish that
authority without manually repairing ownership rules.

**2. How we implemented it**

Step 7.0c adds typed registration requests to the evolution server. Validation
materializes the proposed protected descriptor and human-reviewed manifest only
inside the isolated workspace, verifies the runtime factory through the real
host loader, and still rejects registry or module-contract file operations.
Explicit approval installs the manifest and protected registry entry; apply
then revalidates feature code against the registered owner.

The protected composition root now loads enabled descriptors generically,
checks registry and manifest agreement, enforces real-path containment, maps
the closed `personal-storage` capability without feature IDs, freezes the
injected context, validates JSON boundaries, and isolates feature load
failures. Existing risk-flag composition remains unchanged until a separately
reviewed migration is needed.

**3. How it applies elsewhere**

Plugin and agent systems can bootstrap new extensions through a reviewed
control-plane transaction while keeping ordinary code generation unable to
grant authority. Running the same loader during isolated validation catches
descriptor drift and invalid factories before protected registration becomes
durable.

---

## 2026-08-08 - Define protected authority for generic extensions

**1. What this teaches the system**

Discovery and dependency injection are safe only when an evolvable feature
cannot make itself loadable or expand its own authority. Feature manifests may
state what code expects, but a protected registry must independently authorize
identity, entry points, enablement, and capabilities. Exact agreement detects
contract drift without treating evolvable metadata as permission.

**2. How we implemented it**

Step 7.0b adds a documentation-only generic extension contract. It defines an
exact protected registry descriptor, a mirrored feature request, the initial
`personal-storage` capability vocabulary, a minimal `createExtension` factory,
strict entry-path containment, registry-only enablement, human-reviewed
registration, and fail-closed behavior. Runtime discovery, registry tooling,
dependency metadata correction, and Weekly Goals remain unimplemented.

**3. How it applies elsewhere**

Plugin hosts, automation systems, and agent tool registries should separate
requested authority from granted authority. A protected allowlist should grant
the minimum capability set, require declared code to match it, and prevent
untrusted code from choosing its own loader path or activation state.

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

We integrated a configurable Google Gemini model using the Google GenAI SDK with structured response validation (`response_schema=ProposalOutput`). The current default is `gemini-2.5-flash`, and deployments may override it with `DARWIN_MODEL`. The evolution server (`server/main.py`) validates requested file paths against path traversal attacks, evaluates fast-path vs. full-path eligibility, stores pending proposals in `server/pending/{id}.json`, records all successes and failures in `logs/evolution-log.json`, and leaves working application files untouched during generation. A comprehensive test suite (`server/tests/test_server.py`) verifies proposal generation, schema enforcement, failure logging, and inspection APIs.

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

## 2026-08-06 - First live end-to-end evolution cycle confirmed; three engine bugs found and fixed

**1. What this teaches the system**

A validation pipeline that only runs in tests is not the same as one that runs against a real browser, a real build tool, and a real OS. Three bugs that were invisible in unit tests became immediately apparent the first time a live proposal attempted to apply against the actual codebase on Windows:

1. **npm package imports flagged as boundary violations.** `find_imports()` + `resolve_import_path()` correctly flags non-relative imports that could reference locked paths — but it incorrectly treated bare package names like `react` and `lucide-react` the same way. Every JSX file in the codebase imports `react`, so every proposal touching any `.jsx` file failed dependency analysis.

2. **`node --check` cannot parse `.jsx` files.** Node's syntax checker only understands plain JS/ESM. Passing a `.jsx` file to `node --check` throws `ERR_UNKNOWN_FILE_EXTENSION` regardless of the file's content. Since Vite's build step already catches JSX syntax errors, this check was redundant for `.jsx` and always wrong.

3. **`npm` is not a binary on Windows.** With `shell=False`, `subprocess.run(["npm", ...])` raises `[WinError 2]` because `npm` on Windows is `npm.cmd`. Node is a real `.exe` and works fine; npm is a shell script wrapper and requires either `shell=True` or the `.cmd` extension.

The rollback mechanism proved itself: on both failed proposals, files were written to disk, the validation pipeline detected the failure, and every modified file was restored before the error was returned. The app reloaded cleanly to its prior state both times.

**2. How we implemented it**

- **npm import fix**: `validate_proposal` now skips dependency flagging for bare package names (`/` not in import) and scoped packages (`@org/pkg` shape). Only slash-containing non-scoped imports (potential aliased repo paths) are still flagged.
- **JSX syntax check fix**: `node --check` is now only invoked on files ending in `.js` and explicitly not `.jsx`. The Vite build in the same validation run already covers JSX syntax.
- **Windows npm fix**: Added `npm_cmd()` helper that returns `"npm.cmd"` on Windows and `"npm"` elsewhere. Both `validate_proposal` and `apply_proposal` now use it.
- **CORS**: Added `CORSMiddleware` to the Starlette app so the browser UI (localhost:4173) can reach the evolution server (localhost:8000) without preflight failures.
- **Full UI composition**: `App.jsx` was wired up to compose `CourseList`, `AddCourseModal`, `ApprovalModal`, and `ChatInterface`. The app now fetches live data, handles SSE alarm events, and the chat FAB posts directly to `/evolve`.

**3. How it applies elsewhere**

Platform-specific subprocess behavior is a systemic risk in any cross-OS validation pipeline. The lesson: never assume CLI tool names are OS-agnostic when using `shell=False`. Always resolve executable names at runtime based on platform. The same issue would affect `python` vs `python3`, `pip` vs `pip3`, or any tool that ships as a shell wrapper on one OS and a binary on another.

The rollback validation also demonstrates a broader principle: the correct mental model for transactional apply is not "write then check" but "check in a dry-run, then write only if clean." The current implementation writes first and rolls back on failure — which works, but leaves a window where the filesystem is in a mixed state. A future hardening step could move to a true atomic swap (write to temp, rename on success).

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

---

## 2026-08-08 - Reduce validation latency without weakening isolation

**1. What this teaches the system**

Validation cost must be proportional to proposal risk. Recreating a complete
temporary repository for every proposal can dominate total latency on Windows,
while removing isolation would reintroduce live-file and rollback hazards.

**2. How we implemented it**

Stylesheet-only UI proposals now stop after path, ownership, dependency, and
content-integrity checks. Code-changing proposals continue through isolated
syntax, build, and test gates, but reuse one process-local validation workspace,
link the existing dependency tree, synchronize changed source files, and restore
proposal files after each run. Apply recalculates the proposal path from its
contents so stale metadata cannot bypass full-path approval.

The live JSX test exposed a separate concurrency issue: Node ran SQLite-backed
test files in parallel, and simultaneous WAL initialization caused a transient
`database is locked` failure. Validation and apply now invoke Node with
`--test-concurrency=1`, keeping the isolated database fixture deterministic.
The obsolete Python tests for removed planner endpoints were deleted, and the
remaining server tests were updated for the current proposal schema, CSS-only
fast path, and protected import boundary. The focused server suite now passes
10/10, while the application suite passes 14/14.

**3. How it applies elsewhere**

Build systems, migration tools, and infrastructure agents should separate cheap
policy checks from expensive execution checks, cache stable environments, and
retain isolation around untrusted changes. The transferable rule is to optimize
the validation boundary rather than weakening it. Test suites must also evolve
with route and contract changes; otherwise stale tests create noise instead of
detecting regressions.

---

## 2026-08-08 - Define the constrained personal-storage contract

**1. What this teaches the system**

Persistence for evolvable features must be exposed as a narrow, namespace-bound
capability rather than as a general database service. The composition root must
decide which feature receives which capability, while the protected host owns
storage, validation, versioning, and recovery.

**2. How we implemented it**

Step 6.1 was completed as a design-only change in
`docs/storage-contract.md`. The contract defines `get`, `set`, `delete`, and
`list` operations over JSON-compatible values, forbids namespace selection by
feature code, separates personal storage from `locked/core-data/`, and requires
explicit schema versions, migrations, atomic writes, and namespace-scoped
recovery. No runtime storage implementation was added.

**3. How it applies elsewhere**

The same capability model applies to plugins, browser extensions, workflow
automation, and multi-tenant services: give untrusted code the smallest
resource-specific interface needed for its task, and keep ownership and
recovery in a trusted host.

---

## 2026-08-08 - Bind personal storage to registered module namespaces

**1. What this teaches the system**

A namespace string is not an authorization boundary if feature code can choose
it freely. Namespace ownership must come from the canonical module registry and
be checked by the trusted storage host.

**2. How we implemented it**

Evolvable contracts and registry entries now declare `storage_namespace`. The
personal-data host accepts a registered module ID, rejects unknown or locked
modules, resolves the namespace itself, and exposes no public raw-namespace
factory. Governance tests require registry and colocated-contract agreement;
personal-data tests prove separate registered modules cannot access each other's
records.

**3. How it applies elsewhere**

The same pattern applies to plugin permissions, tenant data stores, and scoped
API tokens: resolve authority from trusted registration metadata and issue
handles that cannot be widened by untrusted callers.

---

## 2026-08-08 - Implement the locked personal-storage host

**1. What this teaches the system**

The persistence boundary becomes enforceable only when the trusted host owns
the database and gives features a namespace-bound capability instead of a raw
storage primitive.

**2. How we implemented it**

Step 6.2 added the locked `personal-data` module and registered its colocated
contract. It owns a separate `data/personal-data.db`, exposes only `get`, `set`,
`delete`, and `list` through a frozen capability, validates identifiers and
JSON-compatible values, and rejects schema-version mismatches. Tests verify
restart persistence, namespace separation, invalid-value rejection, and safe
database teardown. The application composition root does not wire this into a
feature yet; controlled feature access is reserved for Step 6.4.

**3. How it applies elsewhere**

Plugin systems and multi-tenant services should issue resource-scoped handles
from a trusted host. A handle that cannot name another tenant, open a database,
or access a filesystem path makes the intended authority boundary concrete.

---

## 2026-08-08 - Add namespace-scoped personal-data recovery

**1. What this teaches the system**

Recovery must be owned by the trusted host and scoped to one feature namespace.
An extension must not be able to restore arbitrary data, and a malformed backup
must fail before it can damage valid state.

**2. How we implemented it**

Step 6.6 added namespace snapshots to the locked personal-data store. Every
mutating write or delete captures the prior namespace state inside the same
`BEGIN IMMEDIATE` transaction. Trusted recovery resolves a registered module ID,
validates the backup's JSON and schema version, and restores only that namespace.
Tests prove recovery leaves another namespace unchanged and refuses malformed
backups without changing live records.

**3. How it applies elsewhere**

Tenant stores, plugin state, and user settings should use scoped snapshots and
validate recovery inputs before replacement. The same rule protects unrelated
tenants and core data during rollback.

---

## 2026-08-08 - Prove constrained persistence invariants end to end

**1. What this teaches the system**

Persistence is only constrained when its guarantees are tested together with the
existing protected application. Feature persistence, authority boundaries,
schema checks, recovery, and the original timetable behavior must be verified
as one system.

**2. How we implemented it**

Step 6.7 added explicit tests for:

- personal data surviving a fresh process;
- bidirectional `risk-flag` and `ui` namespace isolation;
- operation-only capabilities with no database or filesystem primitives;
- invalid fields, types, and stored versions being rejected;
- malformed recovery snapshots not overwriting valid live data;
- personal storage leaving the protected course database unchanged; and
- the full previous application, scheduler, persistence, boundary, governance,
  and build behavior remaining intact.

The serialized Node suite passes 25/25, the Python evolution-server suite passes
10/10, and the production build passes.

**3. How it applies elsewhere**

Security-sensitive feature work should finish with an invariant matrix that
proves both the new capability and the old protected behavior. This catches
boundary regressions that feature-local tests alone cannot see.

---

## 2026-08-08 - Inject the controlled storage API through the composition root

**1. What this teaches the system**

Declaring a capability is not enough; the host must be the only place that
creates and assigns it. Evolvable code should receive a narrow handle and use
that handle without importing the protected storage implementation.

**2. How we implemented it**

Step 6.4 wires the registry-bound `risk-flag` capability through `app/runtime.js`
into a feature factory. Risk state now uses only namespace-bound `get`, `set`,
and `delete` operations, and survives creation of a fresh runtime. The feature
has no import path to `locked/personal-data/`, its database, or the filesystem.
Application, governance, and personal-storage tests pass 11/11 together.

**3. How it applies elsewhere**

Composition roots in plugin and automation systems should construct scoped
capabilities at startup and pass them explicitly. This makes authority visible,
reviewable, and difficult for an extension to expand accidentally.

---

## 2026-08-08 - Enforce registered personal-storage schemas

**1. What this teaches the system**

A stored version number without a trusted record schema does not protect data
integrity. Schema authority must come from registered module metadata, and
callers must not select a version or bypass shape validation.

**2. How we implemented it**

Step 6.5 added `storage_schema` metadata for evolvable modules and required the
registry and colocated contracts to agree. The locked host validates required
fields, types, and unknown-field policy on both writes and reads. It rejects
schema-version mismatches explicitly, with no silent reset or migration. The
application, governance, and personal-storage suites pass 12/12 together.

**3. How it applies elsewhere**

Configuration stores, plugin state, and API payloads should validate against a
versioned trusted schema at every boundary. Explicit refusal is safer than
silently interpreting data under a newer or incompatible shape.
