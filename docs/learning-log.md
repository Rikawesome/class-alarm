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
