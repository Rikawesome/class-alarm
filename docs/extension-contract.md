# Generic Evolvable Extension Contract

This document defines the contract for registering, composing, and exposing
evolvable runtime features. Step 7.0c implements protected registration,
runtime discovery, capability injection, and failure isolation. Step 7.1 adds
the generic application transport used by feature UIs.

## Purpose

The host may discover approved evolvable features and inject narrow protected
capabilities without hardcoding feature IDs. The protected registry remains the
sole authority for whether a feature is loadable and which capabilities it may
receive.

This contract does not authorize evolvable code to modify `registry/`, import
protected implementations, or register itself at runtime.

## Protected Registry Descriptor

An approved runtime extension is represented by an `extension` object on its
canonical entry in `registry/modules.json`:

```json
{
  "modules": {
    "<module-id>": {
      "path": "evolvable/features/<module-id>",
      "contract": "evolvable/features/<module-id>/module.json",
      "role": "feature",
      "evolution_policy": "evolvable",
      "extension": {
        "contract_version": "1.0",
        "enabled": true,
        "runtime": {
          "entry": "index.js",
          "factory_export": "createExtension"
        },
        "authorized_capabilities": [
          "personal-storage"
        ]
      }
    }
  }
}
```

The descriptor fields are exact:

- `contract_version` must be `"1.0"`.
- `enabled` must be a boolean controlled only through human-reviewed registry
  changes.
- `runtime.entry` must be a repository-relative POSIX path relative to the
  module's registered `path`.
- `runtime.factory_export` must be a valid JavaScript identifier naming a
  function exported by the runtime entry.
- `authorized_capabilities` must be an array of unique capability names from
  the vocabulary in this contract, sorted lexicographically.

Only registry entries with `role: "feature"`, `evolution_policy: "evolvable"`,
and a valid `extension` object are runtime extensions. An entry without
`extension` remains a registered module but is not runtime-discoverable.

The registry module key is the canonical module ID. Neither the feature
manifest nor runtime code may replace or alias that identity.

## Feature Manifest Requirements

The colocated `module.json` for an approved extension must retain the existing
module contract fields and add this exact `extension` request:

```json
{
  "module": "<module-id>",
  "role": "feature",
  "evolution_policy": "evolvable",
  "extension": {
    "contract_version": "1.0",
    "runtime": {
      "entry": "index.js",
      "factory_export": "createExtension"
    },
    "requested_capabilities": [
      "personal-storage"
    ]
  }
}
```

The manifest requirements are:

- `module` must exactly equal the canonical registry module key.
- `role` and `evolution_policy` must exactly match the registry entry.
- `contract_version`, `runtime.entry`, and `runtime.factory_export` must exactly
  match the protected registry descriptor.
- `requested_capabilities` must contain unique recognized capability names,
  sorted lexicographically.
- The requested capability set must exactly equal the registry's
  `authorized_capabilities` set before the feature may load.
- The runtime entry must be covered by the manifest's existing `owns` and
  `file_policies` declarations.

The manifest records what the feature expects; it grants no authority. Editing
an evolvable manifest cannot enable a feature or expand its capabilities.

## Capability Vocabulary

Step 7.0 defines one capability:

| Capability name | Injected property | Protected provider | Additional requirements |
| --- | --- | --- | --- |
| `personal-storage` | `capabilities.personalStorage` | `personal-data` | The registry and manifest must contain matching valid `storage_namespace` and `storage_schema` metadata under the existing storage contract. |

Capability names are a closed, versioned vocabulary. Unknown names are invalid;
features cannot define private capability names. Adding or changing a capability
requires a human-reviewed revision of this contract and the protected provider
composition.

`personal-storage` is the namespace-bound `get`, `set`, `delete`, and `list`
interface defined by `docs/storage-contract.md`. It does not expose the
provider, database, namespace selector, filesystem, or registry.

This contract defines no protected course-data or alarm-scheduling capability.

## Registry Authority And Precedence

The protected registry is authoritative:

1. A feature receives no capability unless its registry descriptor authorizes
   that capability.
2. A feature receives no capability that its colocated manifest does not
   request.
3. Registry and manifest capability sets must match exactly. A mismatch is
   contract drift and the feature must not load.
4. The effective capability set is therefore the validated registry
   `authorized_capabilities` set, never a value supplied by feature code.
5. `enabled` exists only in the protected registry. A manifest field attempting
   to enable itself has no effect and is invalid.

Exact-set matching prevents both unauthorized expansion and dormant registry
authority that a later evolvable-only change could activate.

## Runtime Factory Interface

The approved runtime entry must export the named factory:

```text
createExtension(context) -> Extension
```

The host constructs `context`:

```text
{
  moduleId: string,
  capabilities: {
    personalStorage?: PersonalDataCapability
  }
}
```

Rules:

- `moduleId` is the canonical protected registry key.
- `capabilities` contains exactly the validated effective capability set,
  mapped through the vocabulary above.
- The host passes no registry object, protected module, database handle,
  filesystem path, server object, or unrestricted service locator.
- The feature must not mutate `context` or the capability container.
- The factory must return synchronously and must not perform host registration
  as a side effect.

The returned extension has this minimum interface:

```text
{
  getState() -> JSON-compatible value,
  execute(action: string, input: JSON-compatible value) ->
    JSON-compatible value | Promise<JSON-compatible value>
}
```

`getState` exposes feature-owned state only. `execute` is the generic action
boundary; the host owns transport, selects the registered feature by canonical
module ID, validates JSON-compatible input and output, and never exposes the
extension instance directly to browser code.

An extension may implement internal methods, but the generic host depends only
on `getState` and `execute`.

## Generic Application API

The human-reviewed application host exposes approved extensions without
hardcoding feature-specific routes:

```text
GET  /api/extensions/<module-id>
POST /api/extensions/<module-id>
```

The GET response is `{ "state": ... }`. The POST request body is:

```json
{
  "action": "add",
  "input": {}
}
```

The host validates the module ID, dispatches through `execute`, and returns
`{ "result": ... }`. Unknown, disabled, or failed extensions return a
controlled unavailable response. Input and output remain subject to the
generic JSON-compatibility checks.

Feature UI code may call this API, but it must not import the extension loader,
storage provider, registry, or protected runtime modules.

## UI Integration Validation

User-visible feature proposals include `ui_integration` metadata identifying
the UI entry file, feature ID, and rendered symbol. The evolution validator
requires the entry file to be an actual create/modify operation and checks that
the feature ID and rendered symbol occur in the proposed final content. This
prevents a proposal from claiming a UI integration merely by listing a file in
`files_touched`.

After application, the engine verifies that each live file exactly matches its
approved operation. Build, syntax, and test gates remain in force.

## Entry-Path Containment

Both registration validation and runtime loading must enforce all of these
rules:

- `runtime.entry` is non-empty, uses `/`, and is relative to the registered
  module `path`.
- Absolute paths, drive-qualified paths, URL forms, empty segments, `.`, `..`,
  backslashes, and NUL bytes are rejected.
- Resolving the entry against the module root, including symlink resolution,
  must remain inside the resolved registered module root.
- The resolved entry must be an existing regular `.js` file.
- The resolved entry must be owned by the same module according to its manifest.
- `runtime.factory_export` must exist and be a function.

No fallback path search, package-name resolution, or feature-supplied import
target is permitted.

## Enablement Semantics

- `enabled: true` means the protected host may validate, load, and compose the
  extension.
- `enabled: false` means the host must not import its runtime entry, construct
  capabilities, call its factory, expose its state, or dispatch actions to it.
- Missing `extension` metadata is equivalent to not being a runtime extension,
  not to `enabled: false`.
- A registry change is required to enable, disable, or change the authorized
  capability set.
- Runtime hot-loading is not part of Version 1. Registry changes take effect on
  the next application start.

## Registration And Human Review

An evolution request may propose a structured registration request, but it may
not include a patch to `registry/`. The request must contain the proposed module
ID, module path, contract path, complete protected extension descriptor, and
feature manifest.

Trusted governance performs deterministic validation first. A human then
approves or rejects the registration request. Only trusted governance acting
after explicit approval may write the protected registry entry and its
human-reviewed colocated `module.json`. The general proposal must not include
either file as an operation. The original feature proposal is revalidated
against that registered owner before feature files can be applied.

Approval is atomic from the governance perspective: a feature is not treated as
registered until the complete protected registry entry is valid and durable.
General evolution application remains unable to write `registry/`.

## Failure Behavior

- Invalid registration data or human rejection leaves `registry/` unchanged.
- Duplicate module IDs, path ownership collisions, unknown capabilities,
  descriptor/manifest mismatches, and invalid entry paths reject registration.
- A structurally invalid protected registry fails protected startup validation;
  the host must not guess or broaden authority.
- A disabled feature is absent from runtime state and action dispatch.
- Import errors, missing factory exports, factory failures, invalid factory
  results, or capability-construction failures isolate and disable that feature
  for the current process. They do not expose partial capabilities or weaken
  protected scheduling and course-data behavior.
- Calls to an unknown, disabled, or failed feature return a controlled
  unavailable error.
- Invalid feature action input or output is rejected at the host boundary
  without granting additional access.

## Step 7.0c Boundary

Step 7.0c implements protected registration approval, descriptor validation,
generic runtime discovery, and capability composition. Step 7.1 now implements
the generic HTTP transport and the first registered feature. Feature-specific
UI composition remains evolvable, while transport and host validation stay
human-reviewed and reusable.
