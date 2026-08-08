# Evolvable Personal Storage Contract

This document defines the Step 6 storage contract. The locked host and
controlled API are implemented; recovery and rollback are covered by later
Step 6 sub-steps.

## Purpose

Evolvable features may persist feature-owned personal data without receiving
access to the protected timetable database or to general filesystem/database
capabilities.

## Ownership And Boundary

- The host capability lives in the locked module at `locked/personal-data/`.
- `app/` remains the composition boundary. It creates a capability for a
  specific feature and passes that capability explicitly to the feature.
- `locked/core-data/` remains the sole owner of timetable storage.
- Evolvable modules receive capability methods only. They do not receive a
  database connection, SQL interface, ORM, filesystem path, or shared storage
  object.
- The storage host never imports an evolvable module. Feature code never imports
  the storage implementation or any other locked implementation directly.
- The composition root creates the capability and injects it into the feature;
  feature code never constructs or broadens its own storage authority.

## Capability API

Each feature receives a namespace-bound capability with this deliberately small
interface:

```text
get(key) -> value | null
set(key, value) -> value
delete(key) -> boolean
list() -> { key, value }[]
```

Rules:

- `key` is a non-empty, bounded string and is interpreted only inside the
  capability's namespace.
- `value` is JSON-compatible data: null, boolean, number, string, arrays, and
  plain objects. Functions, database handles, class instances, and binary data
  are rejected.
- `get`, `set`, `delete`, and `list` cannot accept a namespace argument.
- The capability exposes no query language, namespace selector, path, transaction handle, or raw
  storage object.
- `list()` returns only records belonging to the bound feature.
- Invalid input is rejected without modifying stored data.

## Namespace Isolation

The host binds a namespace before a feature is invoked. The public host factory
accepts a registered module ID, resolves that module's `storage_namespace` from
`registry/modules.json`, and rejects locked, unknown, or unregistered modules.
The feature never supplies a raw namespace string. For example, `weekly-goals`
and `revision-planner` will receive different registered capabilities and cannot
address one another's records.

The underlying storage may use one physical database, but namespace ownership
must be enforced by the host on every operation. Physical co-location must not
be treated as permission to share data.

## Schema And Versioning

Each namespace has an explicit schema version and an owning module identity in
the canonical registry and colocated module contract. Stored records are
validated against the namespace's schema before being returned or written.

- A version mismatch is handled by an explicit migration or a safe refusal.
- No silent coercion, destructive reset, or best-effort interpretation is
  allowed.
- Migrations are owned by the locked host and are versioned, deterministic, and
  tested before activation.
- Unknown fields are rejected unless the namespace schema explicitly permits
  them.
- Schema authority comes from registered module metadata; feature callers cannot
  select a schema version or bypass record-shape validation.

## Recovery And Rollback

Writes are atomic from the feature's perspective. Before replacing or deleting
records, the locked host retains one recoverable snapshot for that namespace.
Recovery is initiated by the trusted host using the registered module ID. A
malformed backup or failed recovery validation is refused before live records
are changed.

Recovery is namespace-scoped: restoring one feature's data cannot overwrite the
protected timetable database or another feature's namespace. Removing or
rolling back a feature removes or restores only that feature's namespace.

## Security Invariants For Later Steps

The implementation and tests must prove that:

1. Data survives an application restart.
2. A feature cannot read, list, overwrite, or delete another feature's data.
3. Evolvable code cannot access `locked/core-data/` or its database directly.
4. Invalid keys and values do not alter stored state.
5. Schema mismatches are handled explicitly.
6. Malformed data can be rejected or recovered without damaging unrelated
   namespaces or protected timetable data.
