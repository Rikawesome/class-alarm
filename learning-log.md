# Learning Log

## 2026-07-31 - Refactor tests to enforce module boundaries and colocate with locked modules

**1. What this teaches the system**
The system now enforces a strict architectural boundary where locked modules (protected-core) must not import evolvable code. By moving tests into the locked module directories and updating import paths, we ensure that tests validate the locked modules' behavior without evolving dependencies, and we prevent accidental coupling to evolvable code. This establishes an invariant: locked modules are self-contained and only depend on other locked modules or node built-ins.

**2. How we implemented it**
- Moved test files from the root 	ests/ directory into the appropriate locked module directories:
  - 	ests/alarm-display.test.js ? locked/alarm-engine/tests/alarm-display.test.js`n  - 	ests/scheduler.test.js ? locked/alarm-engine/tests/scheduler.test.js
  - 	ests/core-data.test.js ? locked/core-data/tests/core-data.test.js
- Created new test suites:
  - pp/tests/application-server.test.js (integration test for the composed runtime and server)
  - governance/tests/dependency-boundaries.test.js (validates that no locked module imports evolvable code via a regex scan)
  - governance/tests/registry-integrity.test.js (ensures the module registry entries resolve to correct local contracts and have no duplicate contracts)
- Updated import paths in pp/runtime.js and pp/server.js to use correct relative paths after moving the app source from data/app to pp root.
- Removed the old 	ests/ directory and the temporary data/app location.
- All tests now pass, confirming the architectural constraints hold.

**3. How it applies elsewhere**
This pattern of colocating tests with the modules they test, especially for locked/core modules, can be applied to other subsystems (e.g., the evolution server, web shell, or UI features). For any module that has a strict evolution policy (locked or evolvable), placing its tests alongside its source encourages developers to think about the module's public contract and prevents tests from depending on unstable internals. Additionally, the governance test for dependency boundaries can be extended to enforce other constraints, such as forbidding certain imports or requiring specific file policies, making it a scalable guardrail for the architecture.

---
