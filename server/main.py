import atexit
import glob as globmod
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import List, Literal, Optional, Union

from google import genai
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OpenAI = None  # type: ignore
    OPENAI_AVAILABLE = False
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "registry" / "modules.json"
LOG_PATH = ROOT / "logs" / "evolution-log.json"
PENDING_DIR = ROOT / "server" / "pending"
PENDING_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# FIX #2: hardcoded, always-enforced protection, independent of whatever is
# (or isn't) correctly configured in registry/modules.json. A misconfigured
# or missing registry entry must never be able to unlock these paths.
# ---------------------------------------------------------------------------
PROTECTED_PREFIXES = ("locked/", "app/", "server/", "governance/", "registry/", ".env")

# FIX #1: files larger than this are never auto-truncated into a partial
# view. If a target file is bigger than this, the request is forced to
# full-path / manual review instead of letting the model "complete-replace"
# something it only partially saw.
MAX_SAFE_CONTEXT_CHARS = 20_000

# FIX #7: if a "modify" operation's new content is less than this fraction
# of the original file's length, treat it as a suspected wipe and force
# manual review rather than silently allowing it.
MIN_RETAINED_CONTENT_RATIO = 0.6

# Maximum number of times the pipeline will automatically retry a proposal
# after a fixable validation failure before escalating to the developer.
MAX_RETRY_ATTEMPTS = 3
PROVIDER_RETRY_ATTEMPTS = 2

# The control plane must never judge a proposal against an already-broken
# application. Cache a successful/failed baseline report until source changes;
# this avoids paying for the build and test suite on every endpoint call.
_BASELINE_HEALTH_CACHE: Optional[dict] = None

# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------
# These categories determine whether the retry loop can attempt a fix, or
# whether the problem requires human intervention.
#
#   FIXABLE    â€” syntax error, build error, or test failure all within
#                evolvable/; the model can be shown its own output + the
#                error and asked to correct it.
#   UNFIXABLE  â€” the proposal touched a protected path, violated an
#                architectural boundary, or broke governance tests. No
#                amount of retrying will help; escalate immediately.
#   PROMOTE    â€” the proposal needs a contract change; don't retry, reclassify
#                as full-path and surface to the developer for approval.
# ---------------------------------------------------------------------------

FIXABLE_GATES = {
    "registration",
    "syntax_check",
    "extension_contract",
    "production_build",
    "test_suite",
    "content_wipe_check",
}
UNFIXABLE_GATES = {
    "path_safety",
    "locked_protection",
    "dependency_analysis",
    "scope_authorization",
}


def classify_failure(steps: dict, errors: list) -> str:
    """
    Return 'FIXABLE', 'UNFIXABLE', or 'PROMOTE' for a validation result.
    The classification drives whether evolve() retries or escalates.
    """
    for gate in UNFIXABLE_GATES:
        if steps.get(gate) == "fail":
            return "UNFIXABLE"

    # A module_ownership failure usually means a contract change is needed.
    if steps.get("module_ownership") == "fail":
        return "PROMOTE"

    # content_wipe is fixable â€” we tell Gemini to preserve more of the file.
    # build / syntax / test failures are fixable if they're in evolvable/.
    for gate in FIXABLE_GATES:
        if steps.get(gate) == "fail":
            return "FIXABLE"

    # Fallback: if we can't categorise it, don't retry blindly.
    return "UNFIXABLE"


def build_retry_context(
    intent: str,
    failure_chain: list,
    previous_operations: list,
) -> str:
    """
    Build the evolution context for a retry attempt.

    The critical addition over build_evolution_context() is a PREVIOUS ATTEMPT
    FEEDBACK section that gives Gemini back exactly what it generated last time,
    annotated with what went wrong. Without this the model has no memory of its
    prior output and is likely to repeat the same mistake.
    """
    base_context = build_evolution_context(intent)

    feedback_lines = [
        "\n=== PREVIOUS ATTEMPT FEEDBACK (read this carefully before responding) ===",
        f"Your proposal failed validation. This is attempt {len(failure_chain) + 1} of {MAX_RETRY_ATTEMPTS}.",
        "",
    ]

    for i, record in enumerate(failure_chain, start=1):
        feedback_lines.append(f"--- Attempt {i} failure ---")
        feedback_lines.append(f"Gate that failed : {record['gate']}")
        feedback_lines.append(f"Classification   : {record['classification']}")
        feedback_lines.append(f"Error output     :\n{record['error']}")
        if record.get("generated_files"):
            feedback_lines.append("Files you generated in that attempt:")
            for path, content in record["generated_files"].items():
                feedback_lines.append(f"\n  [{path}]\n{content}")
        feedback_lines.append("")

    feedback_lines += [
        "INSTRUCTIONS FOR THIS RETRY:",
        "1. Read the error output above carefully â€” it shows exactly what was wrong.",
        "2. The generated file content shown above is what you produced last time.",
        "   Fix only the specific problem identified; do not rewrite unrelated parts.",
        "3. The HARD RULES in the HOST APPLICATION CONTEXT section above still apply.",
        "   Do not try to fix a problem by touching a protected path.",
    ]

    return base_context + "\n".join(feedback_lines)


def write_escalation(request_id: str, intent: str, failure_chain: list, reason: str):
    """
    Append a structured escalation record to logs/escalations.json so the
    developer has a single place to look when the retry loop gives up.
    """
    escalation_path = ROOT / "logs" / "escalations.json"
    records = []
    if escalation_path.exists():
        try:
            records = json.loads(escalation_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            records = []
    records.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "original_request": intent,
        "reason": reason,
        "attempts": len(failure_chain),
        "failure_chain": failure_chain,
    })
    escalation_path.write_text(json.dumps(records, indent=2), encoding="utf-8")


def load_env_file():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


load_env_file()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class FileOperation(BaseModel):
    action: Literal["create", "modify", "delete"]
    path: str
    content: Optional[str] = Field(
        default=None,
        description="Complete updated or created file content if action is modify or create",
    )


class ContractEffects(BaseModel):
    new_contract_fields: List[str] = Field(default_factory=list)
    modified_contracts: List[str] = Field(default_factory=list)


class TestEffects(BaseModel):
    new_tests: List[str] = Field(default_factory=list)
    modified_tests: List[str] = Field(default_factory=list)


class UIIntegration(BaseModel):
    entry_file: str = Field(description="UI entry file that renders the feature")
    feature_id: str = Field(description="Feature identifier, such as weekly-goals")
    rendered_symbol: str = Field(
        description="Component or visible marker that must occur in entry_file content"
    )


class ExtensionRuntimeDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: str
    factory_export: str


class ProtectedExtensionDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1.0"]
    enabled: bool
    runtime: ExtensionRuntimeDescriptor
    authorized_capabilities: List[str]


class FeatureExtensionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1.0"]
    runtime: ExtensionRuntimeDescriptor
    requested_capabilities: List[str]


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str
    path: str
    contract: str
    extension: ProtectedExtensionDescriptor
    manifest: dict


class GenerationRegistrationRequest(BaseModel):
    module_id: str = Field(
        description="Lowercase kebab-case feature ID, for example weekly-goals."
    )
    authorized_capabilities: List[Literal["personal-storage"]] = Field(
        default_factory=list,
        description=(
            "Protected capabilities requested by the feature. Include personal-storage "
            "whenever the feature persists feature-owned data."
        ),
    )
    manifest_json: str = Field(
        description=(
            "Complete feature module.json object serialized as a valid JSON string. "
            "The manifest MUST contain an \"extension\" key with exactly this shape: "
            "{\"contract_version\": \"1.0\", \"runtime\": {\"entry\": \"index.js\", "
            "\"factory_export\": \"createExtension\"}, \"requested_capabilities\": [...]}. "
            "requested_capabilities must exactly match authorized_capabilities. "
            "Example for a feature with personal-storage: "
            "{\"module\": \"weekly-goals\", \"role\": \"feature\", "
            "\"evolution_policy\": \"evolvable\", "
            "\"owns\": [\"evolvable/features/weekly-goals/**\"], "
            "\"file_policies\": {\"module.json\": \"human-review\", \"index.js\": \"evolvable\"}, "
            "\"storage_namespace\": \"weekly-goals\", "
            "\"storage_schema\": {\"version\": 1, \"record\": {\"title\": \"string\", \"completed\": \"boolean\"}}, "
            "\"extension\": {\"contract_version\": \"1.0\", "
            "\"runtime\": {\"entry\": \"index.js\", \"factory_export\": \"createExtension\"}, "
            "\"requested_capabilities\": [\"personal-storage\"]}}"
        )
    )


class ProposalOutput(BaseModel):
    plan: str = Field(description="Clear step-by-step description of proposed change")
    scope: Literal["global", "personal"] = Field(
        default="global",
        description="Evolution authority scope. Personal scope is reserved for the user-artifact lane.",
    )
    target: Optional[str] = Field(
        default=None,
        description="Optional user or artifact target. Required when scope is personal.",
    )
    artifact_manifest: List[str] = Field(
        default_factory=list,
        description="User-owned artifacts produced by personal evolution; empty for repository changes.",
    )
    files_touched: List[str] = Field(description="All file paths relative to repository root")
    operations: List[FileOperation] = Field(description="Explicit operations to execute")
    contract_effects: ContractEffects = Field(default_factory=ContractEffects)
    test_effects: TestEffects = Field(default_factory=TestEffects)
    new_locked_imports: List[str] = Field(default_factory=list)
    unresolved_imports: List[str] = Field(
        default_factory=list,
        description="Imports the model could not confirm as safe (non-relative/aliased). "
                    "Populated by validation, not the model.",
    )
    ui_integration: Optional[UIIntegration] = None
    registration_request: Optional[RegistrationRequest] = None


class GenerationProposalOutput(BaseModel):
    plan: str = Field(description="Clear step-by-step description of proposed change")
    scope: Literal["global", "personal"] = "global"
    target: Optional[str] = None
    artifact_manifest: List[str] = Field(default_factory=list)
    files_touched: List[str] = Field(description="All file paths relative to repository root")
    operations: List[FileOperation] = Field(description="Explicit operations to execute")
    contract_effects: ContractEffects = Field(default_factory=ContractEffects)
    test_effects: TestEffects = Field(default_factory=TestEffects)
    new_locked_imports: List[str] = Field(default_factory=list)
    unresolved_imports: List[str] = Field(default_factory=list)
    ui_integration: Optional[UIIntegration] = None
    registration_request: Optional[GenerationRegistrationRequest] = None


class EvolutionRequest(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_model_name() -> str:
    # Default deliberately NOT flash-lite: that tier scored far lower on
    # agentic coding benchmarks and is the likely reason a proposal wiped
    # the UI in the first place. Override with DARWIN_MODEL if needed, but
    # the safe default here is a full-tier model, not the cheapest one.
    return os.getenv("DARWIN_MODEL", "gemini-2.5-flash")


def get_gemini_client() -> Optional[genai.Client]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def classify_provider_error(error: Exception) -> dict:
    """Normalize provider failures into stable API-facing categories."""
    message = str(error)
    upper = message.upper()
    if "API KEY" in upper or "GOOGLE_API_KEY" in upper or "GEMINI_API_KEY" in upper:
        category, retryable, status = "configuration", False, 503
    elif any(token in upper for token in ("401", "UNAUTHENTICATED", "403", "PERMISSION_DENIED", "404", "NOT_FOUND")):
        category, retryable, status = "configuration", False, 503
    elif any(token in upper for token in ("429", "RESOURCE_EXHAUSTED", "QUOTA", "503", "UNAVAILABLE", "TIMEOUT", "CONNECTION")):
        category, retryable, status = "transient_provider", True, 503
    else:
        category, retryable, status = "generation", False, 500
    return {"category": category, "retryable": retryable, "status_code": status, "detail": message}


def is_protected_path(path_str: str) -> bool:
    """
    FIX #2: hardcoded, fail-closed check, independent of registry config.
    Note: locked/core-data/access.js is the one file evolvable code is
    allowed to IMPORT from â€” but it is still protected from being WRITTEN
    to by an evolution, same as every other locked file. No carve-out here.
    """
    normalized = Path(path_str).as_posix()
    return any(normalized.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def load_all_contracts() -> dict:
    """
    Reads registry/modules.json, then reads each module's own contract
    file it points to, keyed by module id. Missing until now -- this is
    what build_evolution_context() and evolve() were calling, and its
    absence is the real cause behind the Pylance 'not defined' errors
    (Pylance was right: the name genuinely didn't exist anywhere).
    """
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    contracts = {}
    for module_id, entry in registry.get("modules", {}).items():
        contract_path = (ROOT / entry["contract"]).resolve()
        contract_path.relative_to(ROOT)  # guard against a contract path escaping the repo
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if contract.get("module") != module_id:
            raise ValueError(
                f"Contract identity mismatch for {module_id}: file declares "
                f"module={contract.get('module')!r}"
            )
        contracts[module_id] = contract
    return contracts


def load_registry_modules() -> dict:
    """
    Returns just the {module_id: {...}} mapping from registry/modules.json
    -- used by validate_proposal()/get_owning_module() for ownership and
    locked/evolvable policy checks. Same missing-function issue as above.
    """
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return registry.get("modules", {})


KNOWN_EXTENSION_CAPABILITIES = {"personal-storage"}
MODULE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
JAVASCRIPT_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
STORAGE_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def validate_extension_entry_path(entry_path: str) -> PurePosixPath:
    if (
        not entry_path
        or "\\" in entry_path
        or "\x00" in entry_path
        or re.match(r"^[A-Za-z]:", entry_path)
        or "://" in entry_path
    ):
        raise ValueError("Extension runtime entry must be a non-empty relative POSIX path.")
    relative = PurePosixPath(entry_path)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in entry_path.split("/"))
    ):
        raise ValueError("Extension runtime entry contains a forbidden path segment.")
    if relative.suffix != ".js":
        raise ValueError("Extension runtime entry must resolve to a .js file.")
    return relative


def _validate_capability_list(capabilities: List[str], field_name: str):
    if capabilities != sorted(capabilities) or len(capabilities) != len(set(capabilities)):
        raise ValueError(f"{field_name} must contain unique capability names in lexical order.")
    unknown = set(capabilities) - KNOWN_EXTENSION_CAPABILITIES
    if unknown:
        raise ValueError(f"{field_name} contains unknown capabilities: {sorted(unknown)}.")


def _manifest_policy_covers_entry(manifest: dict, entry_path: str) -> bool:
    for pattern in manifest.get("file_policies", {}):
        if PurePosixPath(entry_path).match(pattern):
            return True
    return False


def validate_registration_request(
    registration: RegistrationRequest,
    modules: dict,
) -> tuple[dict, bool]:
    module_id = registration.module_id
    if not MODULE_ID_PATTERN.fullmatch(module_id):
        raise ValueError("Registration module_id must use lowercase letters, numbers, and hyphens.")

    expected_path = f"evolvable/features/{module_id}"
    expected_contract = f"{expected_path}/module.json"
    if registration.path != expected_path or registration.contract != expected_contract:
        raise ValueError(
            f"Registration paths must be '{expected_path}' and '{expected_contract}'."
        )

    descriptor = registration.extension
    entry_path = validate_extension_entry_path(descriptor.runtime.entry)
    if not JAVASCRIPT_IDENTIFIER_PATTERN.fullmatch(descriptor.runtime.factory_export):
        raise ValueError("Extension factory_export must be a valid JavaScript identifier.")
    _validate_capability_list(
        descriptor.authorized_capabilities,
        "authorized_capabilities",
    )

    manifest = registration.manifest
    if manifest.get("module") != module_id:
        raise ValueError("Feature manifest module must match the registration module_id.")
    if manifest.get("role") != "feature" or manifest.get("evolution_policy") != "evolvable":
        raise ValueError("Registered extensions must be evolvable feature modules.")
    if manifest.get("file_policies", {}).get("module.json") != "human-review":
        raise ValueError("Feature manifests must keep module.json human-reviewed.")
    if f"{expected_path}/**" not in manifest.get("owns", []):
        raise ValueError("Feature manifest owns must include its complete registered module path.")
    if not _manifest_policy_covers_entry(manifest, entry_path.as_posix()):
        raise ValueError("Feature manifest file_policies must cover the runtime entry.")

    try:
        feature_request = FeatureExtensionRequest.model_validate(manifest.get("extension"))
    except Exception as error:
        raise ValueError(f"Feature manifest extension request is invalid: {error}") from error
    if feature_request.contract_version != descriptor.contract_version:
        raise ValueError("Registry and manifest extension contract versions must match.")
    if feature_request.runtime != descriptor.runtime:
        raise ValueError("Registry and manifest runtime descriptors must match.")
    _validate_capability_list(
        feature_request.requested_capabilities,
        "requested_capabilities",
    )
    if feature_request.requested_capabilities != descriptor.authorized_capabilities:
        raise ValueError("Requested and authorized capability sets must match exactly.")

    storage_namespace = manifest.get("storage_namespace")
    storage_schema = manifest.get("storage_schema")
    if "personal-storage" in descriptor.authorized_capabilities:
        if not isinstance(storage_namespace, str) or not STORAGE_NAMESPACE_PATTERN.fullmatch(storage_namespace):
            raise ValueError("personal-storage requires a valid storage_namespace.")
        if not isinstance(storage_schema, dict) or not isinstance(storage_schema.get("version"), int):
            raise ValueError("personal-storage requires a versioned storage_schema.")
        if not isinstance(storage_schema.get("record"), dict):
            raise ValueError("personal-storage requires a storage_schema record definition.")

    candidate_entry = {
        "path": registration.path,
        "contract": registration.contract,
        "role": "feature",
        "evolution_policy": "evolvable",
        "extension": descriptor.model_dump(),
    }
    if storage_namespace is not None or storage_schema is not None:
        if storage_namespace is None or storage_schema is None:
            raise ValueError("storage_namespace and storage_schema must be declared together.")
        candidate_entry["storage_namespace"] = storage_namespace
        candidate_entry["storage_schema"] = storage_schema

    existing = modules.get(module_id)
    if existing is not None:
        if existing != candidate_entry:
            raise ValueError(f"Module '{module_id}' is already registered differently.")
        contract_path = ROOT / registration.contract
        if not contract_path.exists():
            raise ValueError(f"Registered contract is missing: {registration.contract}.")
        existing_manifest = json.loads(contract_path.read_text(encoding="utf-8"))
        if existing_manifest != manifest:
            raise ValueError(f"Registered contract differs from the requested manifest for '{module_id}'.")
        return candidate_entry, True

    for existing_id, existing_entry in modules.items():
        existing_path = PurePosixPath(existing_entry["path"]).as_posix().rstrip("/")
        candidate_path = PurePosixPath(registration.path).as_posix().rstrip("/")
        if (
            candidate_path == existing_path
            or candidate_path.startswith(f"{existing_path}/")
            or existing_path.startswith(f"{candidate_path}/")
        ):
            raise ValueError(
                f"Registration path collides with module '{existing_id}'."
            )
        if existing_entry.get("storage_namespace") == storage_namespace and storage_namespace is not None:
            raise ValueError(
                f"Storage namespace '{storage_namespace}' is already registered."
            )

    return candidate_entry, False


def write_registration(root: Path, registration: RegistrationRequest, candidate_entry: dict):
    registry_path = root / "registry" / "modules.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["modules"][registration.module_id] = candidate_entry
    contract_path = root / registration.contract
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(
        json.dumps(registration.manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")


def install_approved_registration(registration: RegistrationRequest) -> bool:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    candidate_entry, already_registered = validate_registration_request(
        registration,
        registry.get("modules", {}),
    )
    if already_registered:
        return False

    contract_path = (ROOT / registration.contract).resolve()
    contract_path.relative_to(ROOT)
    if contract_path.exists():
        raise ValueError(f"Registration contract already exists: {registration.contract}.")

    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_temp = contract_path.with_name(f".{contract_path.name}.{uuid.uuid4().hex}.tmp")
    registry_temp = REGISTRY_PATH.with_name(f".{REGISTRY_PATH.name}.{uuid.uuid4().hex}.tmp")
    contract_temp.write_text(
        json.dumps(registration.manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    registry["modules"][registration.module_id] = candidate_entry
    registry_temp.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    try:
        os.replace(contract_temp, contract_path)
        os.replace(registry_temp, REGISTRY_PATH)
    except Exception:
        contract_temp.unlink(missing_ok=True)
        registry_temp.unlink(missing_ok=True)
        contract_path.unlink(missing_ok=True)
        raise
    return True


def build_evolution_context(intent: str) -> str:
    try:
        contracts = load_all_contracts()
    except Exception:
        contracts = {}

    app_dir = ROOT / "evolvable"
    app_files_summary = {}
    oversized_files = []
    if app_dir.exists():
        for p in app_dir.glob("**/*"):
            if p.is_file():
                rel = str(p.relative_to(ROOT))
                try:
                    text = p.read_text(encoding="utf-8")
                except Exception:
                    continue
                # FIX #1: no truncation. If it's too big to safely include in
                # full, flag it instead of silently cutting it.
                if len(text) > MAX_SAFE_CONTEXT_CHARS:
                    oversized_files.append(rel)
                else:
                    app_files_summary[rel] = text

    context = f"""=== HOST APPLICATION CONTEXT ===
Application Name: Class Alarm
Architecture: Modular Evolvable Architecture (Locked Core vs Evolvable Periphery)

=== HARD RULES (enforced in code, not just here) ===
1. These path prefixes are NEVER eligible for automatic modification,
   regardless of what you propose: {", ".join(PROTECTED_PREFIXES)}
2. Evolvable modules must only reach core data through
   locked/core-data/access.js â€” never a direct import of a schema or
   database client.
3. "modify" operations must return the COMPLETE file â€” you are shown the
   complete current file below for anything you might touch. If a file
   you need is not shown (listed under OVERSIZED FILES), do not propose
   modifying it â€” flag that it needs manual handling instead.

4. A new feature module must use registration_request. Do not include
   registry/modules.json or the new module.json in file operations; trusted
   governance writes those only after explicit human approval.
5. For a new feature, module_id is lowercase kebab-case. The host derives
   evolvable/features/<module-id>, module.json, runtime entry index.js, and
   factory export createExtension. Persistent features request personal-storage.

=== FULL CURRENT CONTENT OF EVOLVABLE FILES ===
{json.dumps(app_files_summary, indent=2)}

=== OVERSIZED FILES (too large to safely auto-edit â€” do not propose modifying these) ===
{json.dumps(oversized_files, indent=2)}

=== CANONICAL MODULE CONTRACTS ===
{json.dumps(contracts, indent=2)}

=== USER INTENT ===
{intent}
"""
    return context


def build_system_prompt(contracts: dict) -> str:
    return f"""You are an evolution proposal generator for a modular application called Class Alarm.

Here are the canonical module contracts:
{json.dumps(contracts, indent=2)}

Architectural invariants (also enforced mechanically after you respond,
so do not attempt to work around them):
1. Never propose changes under: {", ".join(PROTECTED_PREFIXES)}
2. Presentation changes touch evolvable/ui/ only.
3. Feature additions reside in evolvable/features/.
4. Evolvable modules only reach core data via locked/core-data/access.js,
   never a direct schema or database import.
5. "modify" operations must return the complete file content, not a diff.
   Only propose modifying files you were shown in full â€” never a file
   listed as oversized.

6. A new feature module must include registration_request. Never propose a
   registry/ operation or a module.json operation for that new module; trusted
   governance creates both only after explicit human approval.
7. registration_request.manifest_json must contain the complete feature
   module.json object serialized as a valid JSON string. The manifest MUST
   contain an "extension" key. The "extension" value must be an object
   with exactly these fields:
     {{"contract_version": "1.0", "runtime": {{"entry": "index.js",
       "factory_export": "createExtension"}},
       "requested_capabilities": [... same as authorized_capabilities ...]}}
   A complete valid manifest_json for a personal-storage feature looks like:
   {{"module": "weekly-goals", "role": "feature",
     "evolution_policy": "evolvable",
     "owns": ["evolvable/features/weekly-goals/**"],
     "file_policies": {{"module.json": "human-review", "index.js": "evolvable"}},
     "storage_namespace": "weekly-goals",
     "storage_schema": {{"version": 1, "record": {{"title": "string", "completed": "boolean"}}}},
     "extension": {{"contract_version": "1.0",
       "runtime": {{"entry": "index.js", "factory_export": "createExtension"}},
       "requested_capabilities": ["personal-storage"]}}}}
8. If the feature persists feature-owned data, authorized_capabilities must be
   ["personal-storage"] and the manifest must declare matching storage metadata.

9. A registered extension factory is called as:
   createExtension({{ moduleId, capabilities: {{ personalStorage }} }}).
   It MUST return exactly the generic runtime interface expected by the host:
   {{ getState() -> JSON-compatible state, execute(action, input) -> JSON-compatible output }}.
   Do not return feature-specific methods as the host interface. Dispatch feature
   actions inside execute(), and use capabilities.personalStorage for persistence.

10. If the request adds a user-visible feature, include ui_integration with the
    exact UI entry_file, feature_id, and rendered_symbol. The UI operation must
    import/render that symbol in the entry_file; do not claim UI integration in
    files_touched without changing the actual entry file content.

    11. Scope rules are strict: use scope "global" for every ordinary request,
    including UI and stylesheet changes. Only use scope "personal" when the
    user explicitly asks for a change private to a named user or personal
    artifact. Personal scope is not enabled in this repository yet; never
    infer it from a file path, target, or artifact_manifest. For global
    requests, target must be null and artifact_manifest must be [].

    Respond only with the requested JSON schema."""


def append_log(entry: dict):
    log = []
    if LOG_PATH.exists():
        try:
            log = json.loads(LOG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log = []
    log.append(entry)
    LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")


def validate_file_paths(proposal: ProposalOutput):
    for file_path in list(proposal.files_touched) + [op.path for op in proposal.operations]:
        normalized = Path(file_path)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError(f"Path traversal or absolute path detected: {file_path}")


def get_owning_module(file_path: str, modules: dict) -> Optional[str]:
    posix_path = Path(file_path).as_posix()
    sorted_modules = sorted(modules.items(), key=lambda x: len(x[1]["path"]), reverse=True)
    for mod_id, entry in sorted_modules:
        module_path = Path(entry["path"]).as_posix().rstrip("/")
        if posix_path == module_path or posix_path.startswith(f"{module_path}/"):
            return mod_id
    return None


def find_imports(code: str) -> List[str]:
    imports = []
    imports += re.findall(r'''\bimport\s+.*?\s+from\s+['"]([^'"]+)['"]''', code, re.DOTALL)
    imports += re.findall(r'''\bimport\s+['"]([^'"]+)['"]''', code)
    imports += re.findall(r'''\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)''', code)
    imports += re.findall(r'''\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)''', code)
    return [imp.strip() for imp in imports]


def ui_component_is_imported_and_rendered(source: str, symbol: str) -> bool:
    """Return whether a JSX component is both imported and rendered in source."""
    if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", symbol):
        return False

    escaped_symbol = re.escape(symbol)
    imported_as_default = re.search(
        rf"\bimport\s+{escaped_symbol}\s*(?:,|from\s*['\"])", source
    )
    imported_as_named = re.search(
        rf"\bimport\s+(?:[A-Za-z_$][A-Za-z0-9_$]*\s*,\s*)?"
        rf"\{{[^}}]*\b(?:{escaped_symbol}|[A-Za-z_$][A-Za-z0-9_$]*\s+as\s+{escaped_symbol})\b[^}}]*\}}\s*from\s*['\"]",
        source,
        flags=re.DOTALL,
    )
    if not (imported_as_default or imported_as_named):
        return False

    # Ignore ordinary JavaScript comments so a commented-out component cannot
    # satisfy the render proof. The JSX expression itself is then required.
    without_comments = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)
    return re.search(rf"<\s*{escaped_symbol}(?=\s|/|>)", without_comments) is not None


def resolve_import_path(importing_file_path: str, import_str: str) -> Optional[str]:
    if not import_str.startswith("."):
        return None
    importing_dir = Path(importing_file_path).parent
    resolved = (ROOT / importing_dir / import_str).resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return None


def npm_cmd() -> str:
    return "npm.cmd" if platform.system() == "Windows" else "npm"


def run_command(args: List[str], cwd: Optional[Path] = None, timeout: int = 120, env_overrides: Optional[dict] = None) -> tuple:
    """
    FIX #5: takes an explicit argument list and runs with shell=False.
    FIX #14: every command now has a hard timeout -- nothing in this
    pipeline should be able to hang silently and indefinitely.
    FIX #15: accepts env_overrides so callers (namely the build step) can
    inject DARWIN_VITE_CACHE_DIR without the caller having to manage the
    full environment dict itself.
    """
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    try:
        res = subprocess.run(
            args, cwd=str(cwd or ROOT), capture_output=True, text=True,
            shell=False, timeout=timeout, env=env,
        )
        return res.returncode, res.stdout, res.stderr
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return (
            -1,
            stdout,
            f"Command timed out after {timeout}s: {' '.join(args)}\n{stderr}",
        )


def baseline_source_fingerprint() -> tuple:
    """Return a cheap fingerprint of files that can affect app health."""
    tracked_roots = ("app", "evolvable", "governance", "locked", "registry", "web")
    files = [ROOT / "package.json", ROOT / "package-lock.json", ROOT / "vite.config.js"]
    for relative_root in tracked_roots:
        root = ROOT / relative_root
        if root.exists():
            files.extend(path for path in root.rglob("*") if path.is_file())
    return tuple(
        (path.relative_to(ROOT).as_posix(), path.stat().st_mtime_ns, path.stat().st_size)
        for path in sorted(files)
    )


def get_baseline_health() -> dict:
    """Build and test the unmodified application before accepting proposals."""
    global _BASELINE_HEALTH_CACHE
    fingerprint = baseline_source_fingerprint()
    if _BASELINE_HEALTH_CACHE and _BASELINE_HEALTH_CACHE["fingerprint"] == fingerprint:
        return _BASELINE_HEALTH_CACHE["report"]

    build_code, build_out, build_err = run_command([npm_cmd(), "run", "build"])
    if build_code != 0:
        report = {
            "healthy": False,
            "stage": "production_build",
            "error": (build_err or build_out).strip(),
        }
    else:
        test_code, test_out, test_err = run_command(
            ["node", "--test", "--test-concurrency=1"], timeout=180
        )
        report = {
            "healthy": test_code == 0,
            "stage": "test_suite" if test_code != 0 else None,
            "error": (test_err or test_out).strip() if test_code != 0 else None,
        }

    _BASELINE_HEALTH_CACHE = {"fingerprint": fingerprint, "report": report}
    return report


# FIX #15: a fixed, real, persistent location for Vite's dependency
# pre-bundle cache -- deliberately OUTSIDE any temp validation workspace,
# so it survives being created and deleted on every single attempt.
VITE_CACHE_DIR = ROOT / ".darwin-vite-cache"


def expand_globs(patterns: List[str], base: Optional[Path] = None) -> List[str]:
    root = base or ROOT
    files = []
    for pattern in patterns:
        matches = globmod.glob(str(root / pattern), recursive=True)
        files.extend(matches)
    return files


# ---------------------------------------------------------------------------
# FIX #13: isolated validation workspace.
#
# ROOT CAUSE OF THE "VANISHING EVOLUTION": the old WorkspaceDryRun wrote
# proposed changes directly into the LIVE evolvable/ files -- the exact
# files your Vite dev server is watching -- ran validation (which can take
# 10-30+ seconds, longer with multiple auto_retry attempts), then restored
# the originals. Vite hot-reloaded on the write AND again on the restore,
# which is why a change flashed briefly in the browser and then reverted,
# and why the approval modal never got a stable proposal to render.
#
# Fixed: validation runs against a persistent, process-local temp workspace,
# never the live files. It is initialized once, then only changed source files
# are synchronized before each run. The live files are only ever touched once,
# deliberately, inside apply_proposal() -- after validation has passed and
# (for full-path) a human has approved it.
# ---------------------------------------------------------------------------

IGNORE_DIRS_FOR_COPY = {
    "node_modules",
    ".git",
    "dist",
    "build",
    ".vite",
    "venv",
    "__pycache__",
    "pending",
}


def link_or_fail_node_modules(tmp_root: Path):
    """
    FIX #14 (continued): the previous version silently fell back to a full
    recursive copy of node_modules when a symlink couldn't be created --
    on Windows without Developer Mode/admin, that's the default, and a
    real node_modules folder can take 10-20+ minutes to copy this way,
    especially under antivirus real-time scanning. That silent multi-
    minute hang, potentially repeated across auto_retry attempts, is the
    most likely cause of a request that never seems to finish.

    Fixed: try a real symlink first (fast, works on Mac/Linux and Windows
    with dev mode). On Windows, fall back to a directory JUNCTION via
    `mklink /J`, which -- unlike a symlink -- does NOT require admin or
    Developer Mode. Only if both of those fail do we raise immediately,
    with a clear message, instead of quietly starting a slow full copy.
    """
    node_modules_src = ROOT / "node_modules"
    node_modules_dest = tmp_root / "node_modules"
    if not node_modules_src.exists():
        return  # nothing to link; build/test will fail with a clear npm error anyway

    try:
        node_modules_dest.symlink_to(node_modules_src, target_is_directory=True)
        return
    except OSError:
        pass

    if platform.system() == "Windows":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(node_modules_dest), str(node_modules_src)],
            capture_output=True, text=True, shell=False,
        )
        if result.returncode == 0:
            return

    raise RuntimeError(
        "Could not link node_modules into the isolated validation workspace "
        "(symlink and junction both failed). Refusing to silently fall back "
        "to a full copy, which can hang for many minutes on a real "
        "node_modules folder. On Windows, enable Developer Mode "
        "(Settings > Privacy & Security > For developers) to allow "
        "symlinks/junctions without admin rights, then retry."
    )


_VALIDATION_WORKSPACE: Optional[Path] = None
_VALIDATION_SOURCE_STATE: dict = {}
_VALIDATION_LOCK = threading.Lock()


def _source_files() -> dict:
    files = {}
    for item in ROOT.iterdir():
        if item.name in IGNORE_DIRS_FOR_COPY or item.name.startswith("."):
            continue
        candidates = [item] if item.is_file() else [p for p in item.rglob("*") if p.is_file()]
        for source in candidates:
            relative = source.relative_to(ROOT)
            if any(part in IGNORE_DIRS_FOR_COPY or part.startswith(".") for part in relative.parts):
                continue
            stat = source.stat()
            files[relative.as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return files


def _copy_source_file(tmp_root: Path, relative: str):
    source = ROOT / relative
    destination = tmp_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def create_validation_workspace() -> Path:
    """Create the isolated workspace once and reuse it across validations."""
    global _VALIDATION_WORKSPACE, _VALIDATION_SOURCE_STATE
    if _VALIDATION_WORKSPACE is not None and _VALIDATION_WORKSPACE.exists():
        return _VALIDATION_WORKSPACE

    tmp_root = Path(tempfile.mkdtemp(prefix="darwin_validate_"))
    for relative in _source_files():
        _copy_source_file(tmp_root, relative)
    link_or_fail_node_modules(tmp_root)
    _VALIDATION_SOURCE_STATE = _source_files()
    _VALIDATION_WORKSPACE = tmp_root
    return tmp_root


def cleanup_validation_workspace(tmp_root: Path):
    """Restore only proposal files; the reusable workspace remains intact."""
    return None


def sync_validation_workspace(tmp_root: Path):
    """Synchronize live source changes without recopying the repository."""
    global _VALIDATION_SOURCE_STATE
    current = _source_files()
    for relative, state in current.items():
        if _VALIDATION_SOURCE_STATE.get(relative) != state:
            _copy_source_file(tmp_root, relative)
    for relative in set(_VALIDATION_SOURCE_STATE) - set(current):
        stale = tmp_root / relative
        if stale.exists():
            stale.unlink()
    _VALIDATION_SOURCE_STATE = current


def _remove_validation_workspace():
    if _VALIDATION_WORKSPACE is not None:
        shutil.rmtree(_VALIDATION_WORKSPACE, ignore_errors=True)


atexit.register(_remove_validation_workspace)


def is_fast_path(proposal: ProposalOutput) -> bool:
    """
    FIX #3: this is now the ONLY function anywhere in the codebase that
    decides fast vs full â€” every entry point must call this, no exceptions,
    no hardcoded overrides.
    """
    if proposal.scope != "global" or proposal.registration_request is not None:
        return False

    all_paths = set(proposal.files_touched) | {op.path for op in proposal.operations}

    for p in all_paths:
        if is_protected_path(p):
            return False
        if not p.startswith("evolvable/ui/"):
            return False
        # Stylesheet-only changes can use lightweight validation. UI
        # JavaScript, JSX, and markup still require a production build.
        if Path(p).suffix.lower() not in {".css", ".scss", ".sass", ".less"}:
            return False

    if proposal.contract_effects.new_contract_fields or proposal.contract_effects.modified_contracts:
        return False
    if proposal.new_locked_imports:
        return False
    if proposal.unresolved_imports:
        # FIX #6: an import we couldn't confirm as safe is treated as a
        # reason to require full review, not silently ignored.
        return False

    return True


def check_for_content_wipe(op: FileOperation) -> Optional[str]:
    """
    FIX #7: catches the specific failure mode that actually happened â€”
    a 'modify' whose new content is drastically shorter than the file it
    replaces, which is exactly the signature of a truncated-context wipe.
    """
    if op.action != "modify":
        return None
    path = ROOT / op.path
    if not path.exists():
        return None
    try:
        original = path.read_text(encoding="utf-8")
    except Exception:
        return None
    new = op.content or ""
    if len(original) == 0:
        return None
    ratio = len(new) / len(original)
    if ratio < MIN_RETAINED_CONTENT_RATIO:
        return (
            f"Suspected content wipe in {op.path}: new content is {ratio:.0%} "
            f"the length of the original ({len(new)} vs {len(original)} chars). "
            f"Flagged for manual review instead of auto-applying."
        )
    return None


def validate_proposal(request_id: str) -> dict:
    proposal_file = PENDING_DIR / f"{request_id}.json"
    steps = {
        "proposal_integrity": "pending",
        "scope_authorization": "pending",
        "path_safety": "pending",
        "registration": "pending",
        "module_ownership": "pending",
        "locked_protection": "pending",
        "dependency_analysis": "pending",
        "content_wipe_check": "pending",
        "syntax_check": "pending",
        "extension_contract": "pending",
        "ui_integration": "pending",
        "baseline_health": "pending",
        "test_suite": "pending",
        "production_build": "pending",
    }
    # FIX #16: real timing per stage, in milliseconds, so latency can be
    # diagnosed from data instead of guessed at. Returned alongside the
    # normal validation result and also written into the pending file.
    timings_ms: dict = {}

    def fail(errs):
        return {"valid": False, "errors": errs, "steps": steps, "timings_ms": timings_ms}

    if not proposal_file.exists():
        return fail([f"Proposal {request_id} not found."])

    try:
        data = json.loads(proposal_file.read_text(encoding="utf-8"))
        proposal = ProposalOutput.model_validate(data.get("proposal", {}))
    except Exception as e:
        return fail([f"Failed to load/parse proposal: {e}"])

    if (
        not proposal.files_touched
        and not proposal.operations
        and proposal.registration_request is None
    ):
        steps["proposal_integrity"] = "fail"
        return fail([
            "Proposal contains no file operations; empty proposals cannot be approved or applied."
        ])
    steps["proposal_integrity"] = "pass"

    if proposal.scope == "personal":
        steps["scope_authorization"] = "fail"
        return fail([
            "Personal evolution is not enabled yet. Personal-scoped proposals are "
            "schema-compatible but cannot write or activate artifacts in the global lane."
        ])
    if proposal.target is not None or proposal.artifact_manifest:
        steps["scope_authorization"] = "fail"
        return fail([
            "Global proposals cannot declare a personal target or artifact_manifest. "
            "Use scope 'personal' only for an explicitly private request."
        ])
    steps["scope_authorization"] = "pass"

    try:
        validate_file_paths(proposal)
    except ValueError as e:
        steps["path_safety"] = "fail"
        return fail([str(e)])
    steps["path_safety"] = "pass"

    try:
        modules = load_registry_modules()
    except Exception as e:
        return fail([f"Failed to load registry: {e}"])

    errors = []
    ownership_ok = True
    locked_protected = True
    registration_entry = None

    if proposal.registration_request is not None:
        try:
            registration_entry, _ = validate_registration_request(
                proposal.registration_request,
                modules,
            )
            runtime_path = (
                f"{proposal.registration_request.path}/"
                f"{proposal.registration_request.extension.runtime.entry}"
            )
            runtime_operations = [
                operation
                for operation in proposal.operations
                if operation.path == runtime_path
                and operation.action in {"create", "modify"}
            ]
            if len(runtime_operations) != 1:
                raise ValueError(
                    f"Registration proposal must create exactly one runtime entry: {runtime_path}."
                )
            modules = {
                **modules,
                proposal.registration_request.module_id: registration_entry,
            }
            steps["registration"] = "pass"
        except ValueError as error:
            steps["registration"] = "fail"
            return fail([str(error)])
    else:
        steps["registration"] = "skipped"
        steps["extension_contract"] = "skipped"

    if proposal.registration_request is not None:
        integration = proposal.ui_integration
        if integration is None:
            steps["ui_integration"] = "fail"
            return fail([
                "Feature proposals must declare ui_integration with entry_file, "
                "feature_id, and rendered_symbol."
            ])
        ui_operations = [
            operation for operation in proposal.operations
            if operation.path == integration.entry_file
            and operation.action in {"create", "modify"}
        ]
        if len(ui_operations) != 1:
            steps["ui_integration"] = "fail"
            return fail([
                f"UI integration must modify exactly one entry file: {integration.entry_file}."
            ])
        ui_content = ui_operations[0].content or ""
        if not ui_component_is_imported_and_rendered(
            ui_content,
            integration.rendered_symbol,
        ):
            steps["ui_integration"] = "fail"
            return fail([
                f"UI entry file {integration.entry_file} must import and render "
                f"feature '{integration.feature_id}' via '{integration.rendered_symbol}'."
            ])
        steps["ui_integration"] = "pass"
    else:
        steps["ui_integration"] = "skipped"

    all_paths = {op.path for op in proposal.operations} | set(proposal.files_touched)
    for p in all_paths:
        if (
            proposal.registration_request is not None
            and p == proposal.registration_request.contract
        ):
            errors.append(
                "The trusted registration transaction owns the new module.json; "
                "proposal operations must not create or modify it."
            )
            locked_protected = False
            continue
        # FIX #2: hardcoded check runs FIRST and independently of registry state.
        if is_protected_path(p):
            errors.append(f"Protected path touched: {p} (matches a hardcoded protected prefix).")
            locked_protected = False
            continue
        owning_mod = get_owning_module(p, modules)
        if not owning_mod:
            errors.append(f"Path {p} does not belong to any registered evolvable module â€” failing closed.")
            ownership_ok = False
            continue
        policy = modules[owning_mod].get("evolution_policy", "locked")
        if policy == "locked":
            errors.append(f"Modification of locked module file {p} (owned by {owning_mod}) is forbidden.")
            locked_protected = False

    steps["module_ownership"] = "pass" if ownership_ok else "fail"
    steps["locked_protection"] = "pass" if locked_protected else "fail"

    dep_ok = True
    for op in proposal.operations:
        if op.action in ("create", "modify") and op.content:
            for imp in find_imports(op.content):
                resolved = resolve_import_path(op.path, imp)
                if resolved is None:
                    # Non-relative imports that are plain npm package names (no
                    # slashes, or scoped @org/pkg) are safe bundled dependencies â€”
                    # Vite resolves them, they never touch the locked boundary.
                    # Only flag imports that look like aliased repo paths (contain
                    # a slash but aren't scoped packages), which could smuggle in
                    # a cross-boundary reference we can't verify statically.
                    is_scoped_pkg = imp.startswith("@") and imp.count("/") == 1
                    is_bare_pkg = "/" not in imp
                    if is_bare_pkg or is_scoped_pkg:
                        continue  # safe npm package import
                    errors.append(f"Unresolved/unverifiable import '{imp}' in {op.path} â€” requires manual review.")
                    dep_ok = False
                    continue
                if op.path.startswith("evolvable/") and resolved.startswith("locked/"):
                    if not resolved.startswith("locked/core-data/access.js"):
                        errors.append(f"Boundary violation: {op.path} imports {resolved} directly (must use access.js).")
                        dep_ok = False
                if (
                    op.path.startswith("evolvable/")
                    and resolved.startswith(("app/", "server/", "governance/", "registry/"))
                ):
                    errors.append(
                        f"Boundary violation: {op.path} imports protected host path {resolved}."
                    )
                    dep_ok = False
                if op.path.startswith("locked/") and resolved.startswith("evolvable/"):
                    errors.append(f"Boundary violation: locked file {op.path} imports evolvable path {resolved}.")
                    dep_ok = False
    steps["dependency_analysis"] = "pass" if dep_ok else "fail"

    wipe_ok = True
    for op in proposal.operations:
        wipe_msg = check_for_content_wipe(op)
        if wipe_msg:
            errors.append(wipe_msg)
            wipe_ok = False
    steps["content_wipe_check"] = "pass" if wipe_ok else "fail"

    if errors:
        return fail(errors)

    baseline_health = get_baseline_health()
    if not baseline_health["healthy"]:
        steps["baseline_health"] = "fail"
        return fail([f"Baseline health check failed at {baseline_health['stage']}: {baseline_health['error']}"])
    steps["baseline_health"] = "pass"

    syntax_ok = True
    _t0 = time.monotonic()
    _VALIDATION_LOCK.acquire()
    workspace = None
    workspace_backups = {}
    try:
        workspace = create_validation_workspace()
        sync_validation_workspace(workspace)
    except Exception as e:
        _VALIDATION_LOCK.release()
        return fail([f"Failed to create isolated validation workspace: {e}"])
    timings_ms["workspace_copy"] = round((time.monotonic() - _t0) * 1000)

    try:
        if proposal.registration_request is not None:
            registration_paths = [
                "registry/modules.json",
                proposal.registration_request.contract,
            ]
            for relative in registration_paths:
                path = workspace / relative
                if relative not in workspace_backups:
                    workspace_backups[relative] = path.read_bytes() if path.exists() else None
            write_registration(
                workspace,
                proposal.registration_request,
                registration_entry,
            )

        for op in proposal.operations:
            path = (workspace / op.path).resolve()
            path.relative_to(workspace)  # guard against a path escaping the sandbox
            if op.path not in workspace_backups:
                workspace_backups[op.path] = path.read_bytes() if path.exists() else None
            if op.action in ("create", "modify"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(op.content or "", encoding="utf-8")
            elif op.action == "delete":
                if path.exists():
                    path.unlink()

        _t0 = time.monotonic()
        for op in proposal.operations:
            # node --check cannot parse JSX syntax; Vite handles .jsx in the
            # build step below, so only run the node checker on plain .js files.
            if op.action in ("create", "modify") and op.path.endswith(".js") and not op.path.endswith(".jsx"):
                ret, out, err = run_command(["node", "--check", op.path], cwd=workspace)
                if ret != 0:
                    errors.append(f"Syntax error in {op.path}:\n{err or out}")
                    syntax_ok = False
        timings_ms["syntax_check"] = round((time.monotonic() - _t0) * 1000)
        steps["syntax_check"] = "pass" if syntax_ok else "fail"
        if not syntax_ok:
            return fail(errors)

        if proposal.registration_request is not None:
            _t0 = time.monotonic()
            validation_script = (
                "import { loadApprovedExtensions } from './app/extensions.js';"
                "const host = await loadApprovedExtensions();"
                f"const failure = host.getFailures()[{json.dumps(proposal.registration_request.module_id)}];"
                "if (failure) throw new Error(failure);"
                "host.getState();"
                f"const stateFailure = host.getFailures()[{json.dumps(proposal.registration_request.module_id)}];"
                "if (stateFailure) throw new Error(stateFailure);"
            )
            ret, out, err = run_command(
                ["node", "--input-type=module", "--eval", validation_script],
                cwd=workspace,
            )
            timings_ms["extension_contract"] = round((time.monotonic() - _t0) * 1000)
            if ret != 0:
                errors.append(f"Extension contract validation failed:\n{err or out}")
                steps["extension_contract"] = "fail"
                return fail(errors)
            steps["extension_contract"] = "pass"

        _t0 = time.monotonic()
        ret, out, err = run_command(
            [npm_cmd(), "run", "build"], cwd=workspace,
            env_overrides={"DARWIN_VITE_CACHE_DIR": str(VITE_CACHE_DIR)},
        )
        timings_ms["production_build"] = round((time.monotonic() - _t0) * 1000)
        if ret != 0:
            errors.append(f"Production build failed:\n{err or out}")
            steps["production_build"] = "fail"
            return fail(errors)
        steps["production_build"] = "pass"

        # Stylesheet-only proposals still need a real production build, but
        # do not need to rerun the complete JavaScript suite after the clean
        # baseline preflight has passed.
        if is_fast_path(proposal):
            steps["test_suite"] = "skipped"
            return {"valid": True, "errors": [], "steps": steps, "timings_ms": timings_ms, "path": "fast"}

        # FIX #5: expand globs ourselves in Python instead of relying on
        # shell expansion, which does not happen on Windows with shell=True.
        test_files = expand_globs([
            "tests/*.test.js",
            "locked/*/tests/*.test.js",
            "evolvable/*/tests/*.test.js",
            "evolvable/features/*/tests/*.test.js",
            "app/tests/*.test.js",
            "governance/tests/*.test.js",
        ], base=workspace)
        if not test_files:
            errors.append(
                "No test files were found by glob expansion. Refusing to treat "
                "an empty test run as a pass â€” check test file locations."
            )
            steps["test_suite"] = "fail"
            return fail(errors)

        _t0 = time.monotonic()
        # SQLite-backed test files share one isolated database. Run test files
        # serially so parallel module initialization cannot race on WAL setup.
        ret, out, err = run_command(
            ["node", "--test", "--test-concurrency=1", *test_files], cwd=workspace
        )
        timings_ms["test_suite"] = round((time.monotonic() - _t0) * 1000)
        if ret != 0:
            errors.append(f"Test suite failed:\n{err or out}")
            steps["test_suite"] = "fail"
            return fail(errors)
        steps["test_suite"] = "pass"

    except Exception as e:
        errors.append(f"Error during isolated validation: {e}")
        return fail(errors)
    finally:
        # Proposal files are restored whether validation passes or fails; the
        # reusable workspace and the live repo remain separate.
        for relative, original_bytes in workspace_backups.items():
            path = workspace / relative
            if original_bytes is None:
                if path.exists():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original_bytes)
        cleanup_validation_workspace(workspace)
        _VALIDATION_LOCK.release()

    return {"valid": True, "errors": [], "steps": steps, "timings_ms": timings_ms}


def verify_applied_operations(proposal: ProposalOutput) -> None:
    """Confirm the live files exactly match the approved operations."""
    for operation in proposal.operations:
        path = (ROOT / operation.path).resolve()
        path.relative_to(ROOT)
        if operation.action in {"create", "modify"}:
            if not path.exists() or path.read_text(encoding="utf-8") != (operation.content or ""):
                raise RuntimeError(
                    f"Applied content differs from the approved operation for {operation.path}."
                )
        elif operation.action == "delete" and path.exists():
            raise RuntimeError(f"Approved deletion did not complete for {operation.path}.")


def apply_proposal(request_id: str, human_approved: bool = False) -> dict:
    proposal_file = PENDING_DIR / f"{request_id}.json"
    if not proposal_file.exists():
        return {"success": False, "error": f"Proposal {request_id} not found."}

    data = json.loads(proposal_file.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    proposal = ProposalOutput.model_validate(data.get("proposal", {}))
    actual_path_type = "fast" if is_fast_path(proposal) else "full"

    # FIX #4: the path label now actually gates something. "full" path
    # proposals may not be applied without an explicit prior approval step.
    if actual_path_type != "fast" and not (human_approved or meta.get("human_approved")):
        return {
            "success": False,
            "error": f"Proposal is '{actual_path_type}' path and has not been human-approved. "
                     f"Call the approve endpoint first, or fast-path eligibility must be re-verified.",
        }

    validation = validate_proposal(request_id)
    if not validation.get("valid"):
        return {"success": False, "error": "Cannot apply invalid proposal.", "validation": validation}

    backups, created_files = {}, []

    try:
        for op in proposal.operations:
            path = (ROOT / op.path).resolve()
            path.relative_to(ROOT)
            if op.action == "create":
                if path.exists():
                    backups[op.path] = path.read_bytes()
                else:
                    created_files.append(op.path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(op.content or "", encoding="utf-8")
            elif op.action == "modify":
                if path.exists():
                    backups[op.path] = path.read_bytes()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(op.content or "", encoding="utf-8")
            elif op.action == "delete":
                if path.exists():
                    backups[op.path] = path.read_bytes()
                    path.unlink()

        for op in proposal.operations:
            if op.action in ("create", "modify") and op.path.endswith(".js") and not op.path.endswith(".jsx"):
                ret, out, err = run_command(["node", "--check", op.path])
                if ret != 0:
                    raise RuntimeError(f"Syntax error in {op.path}:\n{err or out}")

        verify_applied_operations(proposal)

        ret, out, err = run_command(
            [npm_cmd(), "run", "build"],
            env_overrides={"DARWIN_VITE_CACHE_DIR": str(VITE_CACHE_DIR)},
        )
        if ret != 0:
            raise RuntimeError(f"Production build failed:\n{err or out}")

        test_files = expand_globs([
            "tests/*.test.js",
            "locked/*/tests/*.test.js",
            "evolvable/*/tests/*.test.js",
            "evolvable/features/*/tests/*.test.js",
            "app/tests/*.test.js",
            "governance/tests/*.test.js",
        ])
        if actual_path_type != "fast" and not test_files:
            raise RuntimeError("No test files found â€” refusing to apply without a real test run.")
        if actual_path_type != "fast":
            ret, out, err = run_command(
                ["node", "--test", "--test-concurrency=1", *test_files]
            )
            if ret != 0:
                raise RuntimeError(f"Test suite failed:\n{err or out}")

        meta["status"] = "applied"
        meta["applied_at"] = datetime.now(timezone.utc).isoformat()
        data["meta"] = meta
        proposal_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "action": "apply",
            "status": "success",
            "files_touched": proposal.files_touched,
        })
        return {"success": True, "request_id": request_id, "status": "applied", "files_touched": proposal.files_touched}

    except Exception as e:
        for file_path, original_bytes in backups.items():
            path = ROOT / file_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original_bytes)
        for file_path in created_files:
            path = ROOT / file_path
            if path.exists():
                path.unlink()

        meta["status"] = "rolled_back"
        data["meta"] = meta
        proposal_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "action": "apply",
            "status": "rolled_back",
            "error": str(e),
        })
        return {"success": False, "error": f"Application failed and was rolled back: {e}", "status": "rolled_back"}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

async def health(request: Request):
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    baseline = get_baseline_health()
    provider = {
        "configured": bool(api_key),
        "model": get_model_name(),
        "status": "configured" if api_key else "missing_credentials",
    }
    return JSONResponse({
        "status": "ok" if baseline["healthy"] and api_key else "degraded",
        "model": get_model_name(),
        "api_key_configured": bool(api_key),
        "provider": provider,
        "baseline": baseline,
    }, status_code=200 if baseline["healthy"] and api_key else 503)


async def list_proposals(request: Request):
    if not LOG_PATH.exists():
        return JSONResponse([])
    try:
        return JSONResponse(json.loads(LOG_PATH.read_text(encoding="utf-8")))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_proposal(request: Request):
    request_id = request.path_params["request_id"]
    proposal_file = PENDING_DIR / f"{request_id}.json"
    if not proposal_file.exists():
        return JSONResponse({"error": "Proposal not found"}, status_code=404)
    try:
        return JSONResponse(json.loads(proposal_file.read_text(encoding="utf-8")))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def parse_generated_proposal(payload: dict) -> ProposalOutput:
    generated = GenerationProposalOutput.model_validate(payload)
    proposal_data = generated.model_dump()
    registration = proposal_data.get("registration_request")
    if registration is not None:
        manifest_json = registration.pop("manifest_json")
        try:
            registration["manifest"] = json.loads(manifest_json)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Generated registration manifest_json is invalid JSON: {error}"
            ) from error
        module_id = registration["module_id"]
        module_path = f"evolvable/features/{module_id}"
        contract_path = f"{module_path}/module.json"
        runtime = {
            "entry": "index.js",
            "factory_export": "createExtension",
        }
        registration["path"] = module_path
        registration["contract"] = contract_path
        registration["extension"] = {
            "contract_version": "1.0",
            "enabled": True,
            "runtime": runtime,
            "authorized_capabilities": registration.pop("authorized_capabilities"),
        }

        # GenerationRegistrationRequest carries the manifest as an opaque JSON
        # string.  Some model outputs serialize the required manifest extension
        # as null, even though the registration contract supplies the canonical
        # runtime and capability values.  Normalize only that absent value; a
        # non-null manifest extension remains subject to strict validation below.
        if registration["manifest"].get("extension") is None:
            descriptor = registration["extension"]
            registration["manifest"]["extension"] = {
                "contract_version": descriptor["contract_version"],
                "runtime": descriptor["runtime"],
                "requested_capabilities": descriptor["authorized_capabilities"],
            }

        retained_operations = []
        for operation in proposal_data["operations"]:
            if operation["path"] != contract_path:
                retained_operations.append(operation)
                continue
            if operation["action"] not in {"create", "modify"}:
                raise ValueError(
                    "Generated registration module.json operation must create or modify "
                    "the same manifest supplied in manifest_json."
                )
            try:
                operation_manifest = json.loads(operation.get("content") or "")
            except json.JSONDecodeError as error:
                raise ValueError(
                    "Generated registration module.json operation contains invalid JSON."
                ) from error
            if operation_manifest != registration["manifest"]:
                raise ValueError(
                    "Generated registration module.json operation differs from manifest_json."
                )
        proposal_data["operations"] = retained_operations
        proposal_data["files_touched"] = [
            path for path in proposal_data["files_touched"] if path != contract_path
        ]
    return ProposalOutput.model_validate(proposal_data)


def _generate_proposal(client, model_name: str, system_prompt: str, context: str) -> tuple:
    """
    Single Gemini call â†’ validated ProposalOutput.
    Separated so the retry loop can call it with different context each time.
    FIX #16: now also returns elapsed generation time in ms, since this is
    one of the real candidate causes of overall latency (worth measuring
    directly rather than assuming it's fast).
    """
    _t0 = time.monotonic()
    response = None
    for provider_attempt in range(1, PROVIDER_RETRY_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=context,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=GenerationProposalOutput,
                    temperature=0.1,
                ),
            )
            break
        except Exception as error:
            provider = classify_provider_error(error)
            if not provider["retryable"] or provider_attempt >= PROVIDER_RETRY_ATTEMPTS:
                raise
            time.sleep(min(2 ** (provider_attempt - 1), 4))
    if response is None:
        raise RuntimeError("Model provider returned no response.")
    generation_ms = round((time.monotonic() - _t0) * 1000)
    proposal = parse_generated_proposal(json.loads(response.text))
    validate_file_paths(proposal)

    unresolved = []
    for op in proposal.operations:
        if op.content:
            for imp in find_imports(op.content):
                if resolve_import_path(op.path, imp) is None:
                    unresolved.append(imp)
    proposal.unresolved_imports = unresolved
    return proposal, generation_ms


def _run_auto_evolve_loop(
    client,
    model_name: str,
    system_prompt: str,
    req_text: str,
    session_id: str,
    now_iso: str,
) -> JSONResponse:
    """
    Self-healing retry loop â€” called by the /evolve endpoint when the caller
    passes ``"auto_retry": true`` in the request body.

    On each attempt the loop:
      1. Generates a proposal (first attempt: base context; retries: base context
         plus a PREVIOUS ATTEMPT FEEDBACK section containing the exact files
         Gemini wrote last time and the exact error output).
      2. Saves the proposal to server/pending/{id}.json.
      3. Runs validate_proposal() against the saved file.
      4. On pass â†’ returns pending_review immediately.
      5. On fail â†’ classifies the failure and either:
           UNFIXABLE  â†’ writes to logs/escalations.json and returns 422.
           PROMOTE    â†’ returns 202 asking for human approval.
           FIXABLE    â†’ appends to failure_chain and loops.

    After MAX_RETRY_ATTEMPTS all-FIXABLE failures the loop gives up, writes an
    escalation record, and returns 422.

    NOTE: validate_proposal() runs the full build + test suite on every attempt.
    This keeps the loop strictly honest â€” it only declares success when the real
    gates pass â€” but it means auto_retry requests are slow (30-60 s per attempt).
    Use the standard /evolve â†’ /proposals/{id}/validate flow when you want the
    fast non-blocking experience.
    """
    failure_chain: list = []
    last_proposal: Optional[ProposalOutput] = None

    for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
        attempt_id = str(uuid.uuid4())

        if attempt == 1:
            context = build_evolution_context(req_text)
        else:
            # Attach what Gemini generated last time to the last failure record
            # so build_retry_context() can embed it in the new prompt.
            if failure_chain and last_proposal:
                failure_chain[-1]["generated_files"] = {
                    op.path: op.content or ""
                    for op in last_proposal.operations
                    if op.action in ("create", "modify")
                }
            context = build_retry_context(req_text, failure_chain, [])

        try:
            proposal, generation_ms = _generate_proposal(client, model_name, system_prompt, context)
        except Exception as gen_err:
            error_msg = str(gen_err)
            provider = classify_provider_error(gen_err)
            append_log({
                "id": session_id, "timestamp": now_iso, "request": req_text,
                "model": model_name, "path": "none", "status": "failed",
                "error": error_msg, "provider": provider, "attempt": attempt,
            })
            return JSONResponse(
                {
                    "error": "Proposal generation failed.",
                    "provider": provider,
                    "message": (
                        "The model provider is temporarily unavailable. Please retry shortly."
                        if provider["retryable"]
                        else "The evolution provider configuration is invalid or unsupported."
                    ),
                },
                status_code=provider["status_code"],
            )

        last_proposal = proposal
        path_type = "fast" if is_fast_path(proposal) else "full"

        attempt_record = {
            "id": attempt_id,
            "session_id": session_id,
            "timestamp": now_iso,
            "request": req_text,
            "model": model_name,
            "scope": proposal.scope,
            "target": proposal.target,
            "artifact_manifest": proposal.artifact_manifest,
            "path": path_type,
            "status": "pending_review",
            "human_approved": False,
            "plan": proposal.plan,
            "files_touched": proposal.files_touched,
            "attempt": attempt,
            "generation_ms": generation_ms,
            "failure_chain": failure_chain,
        }
        pending_file = PENDING_DIR / f"{attempt_id}.json"
        pending_file.write_text(
            json.dumps({"meta": attempt_record, "proposal": proposal.model_dump()}, indent=2),
            encoding="utf-8",
        )

        validation = validate_proposal(attempt_id)

        if validation.get("valid"):
            append_log({
                **attempt_record, "status": "pending_review",
                "validation_timings_ms": validation.get("timings_ms", {}),
            })
            return JSONResponse({
                "id": attempt_id,
                "session_id": session_id,
                "scope": proposal.scope,
                "target": proposal.target,
                "artifact_manifest": proposal.artifact_manifest,
                "path": path_type,
                "status": "pending_review",
                "plan": proposal.plan,
                "files_touched": proposal.files_touched,
                "attempts": attempt,
                "failure_chain": failure_chain,
                "generation_ms": generation_ms,
                "validation_timings_ms": validation.get("timings_ms", {}),
            })

        steps = validation.get("steps", {})
        errors = validation.get("errors", [])
        classification = classify_failure(steps, errors)

        failing_gate = next(
            (g for g in list(UNFIXABLE_GATES) + ["module_ownership"] + list(FIXABLE_GATES)
             if steps.get(g) == "fail"),
            "unknown",
        )
        failure_chain.append({
            "attempt": attempt,
            "attempt_id": attempt_id,
            "gate": failing_gate,
            "classification": classification,
            "error": "\n".join(errors),
            "steps": steps,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        attempt_record["status"] = "failed_validation"
        attempt_record["failure_chain"] = failure_chain
        pending_file.write_text(
            json.dumps({"meta": attempt_record, "proposal": proposal.model_dump()}, indent=2),
            encoding="utf-8",
        )
        append_log({**attempt_record, "status": "failed_validation", "classification": classification})

        if classification == "UNFIXABLE":
            reason = (
                f"Unfixable failure at gate '{failing_gate}' on attempt {attempt}: "
                f"{errors[0] if errors else 'unknown'}"
            )
            write_escalation(session_id, req_text, failure_chain, reason)
            return JSONResponse({
                "id": attempt_id,
                "session_id": session_id,
                "status": "escalated",
                "classification": "UNFIXABLE",
                "reason": reason,
                "failure_chain": failure_chain,
                "developer_action_required": True,
                "message": (
                    "This proposal touched something beyond what the evolution engine "
                    "can fix automatically. Details have been written to logs/escalations.json."
                ),
            }, status_code=422)

        if classification == "PROMOTE":
            return JSONResponse({
                "id": attempt_id,
                "session_id": session_id,
                "status": "promoted",
                "path": "full",
                "classification": "PROMOTE",
                "reason": f"Contract change required â€” promoted to full-path on attempt {attempt}",
                "plan": proposal.plan,
                "files_touched": proposal.files_touched,
                "failure_chain": failure_chain,
                "developer_action_required": True,
                "message": "This request needs a contract change. Approve it as a full-path proposal.",
            }, status_code=202)

        # FIXABLE â€” loop with the failure injected into next prompt.

    # Retry budget exhausted.
    reason = (
        f"Retry limit ({MAX_RETRY_ATTEMPTS}) exhausted. "
        "All attempts had FIXABLE failures that could not be resolved."
    )
    write_escalation(session_id, req_text, failure_chain, reason)
    append_log({
        "id": session_id, "timestamp": now_iso, "request": req_text,
        "model": model_name, "path": "none", "status": "escalated",
        "attempts": MAX_RETRY_ATTEMPTS, "failure_chain": failure_chain,
    })
    return JSONResponse({
        "session_id": session_id,
        "status": "escalated",
        "classification": "RETRY_EXHAUSTED",
        "attempts": MAX_RETRY_ATTEMPTS,
        "failure_chain": failure_chain,
        "developer_action_required": True,
        "message": (
            f"The engine tried {MAX_RETRY_ATTEMPTS} times but could not produce a "
            "passing proposal. See logs/escalations.json for the full failure chain."
        ),
    }, status_code=422)


async def evolve(request: Request):
    """
    Evolution proposal endpoint â€” two modes depending on the request body:

    Standard mode (default, ``"auto_retry"`` absent or false):
      Generate one proposal, save it to pending/, and return immediately with
      ``status: "pending_review"``. Validation and apply are separate steps
      the caller drives explicitly. This is the fast path used by the chat UI.

    Auto-retry mode (``"auto_retry": true``):
      Run the self-healing loop: generate â†’ validate â†’ retry up to
      MAX_RETRY_ATTEMPTS times, feeding each failure back as context for the
      next attempt. Returns only when the proposal passes all gates, an
      UNFIXABLE failure is hit, or retries are exhausted. Slower (one full
      build+test run per attempt) but hands back a validated proposal or a
      structured escalation without any further calls needed.
    """
    session_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    model_name = get_model_name()
    client = get_gemini_client()

    try:
        body = await request.json()
    except Exception:
        body = {}
    req_text = body.get("text", "")
    if not req_text or not str(req_text).strip():
        return JSONResponse({"error": "Evolution request text cannot be empty."}, status_code=400)

    if not client:
        provider = {"category": "configuration", "retryable": False, "status_code": 503, "detail": "GEMINI_API_KEY or GOOGLE_API_KEY not configured."}
        append_log({
            "id": session_id, "timestamp": now_iso, "request": req_text, "model": model_name,
            "path": "none", "status": "failed",
            "error": provider["detail"], "provider": provider,
        })
        return JSONResponse({
            "error": "Gemini API key is missing.",
            "provider": provider,
        }, status_code=503)

    auto_retry = bool(body.get("auto_retry", False))

    try:
        contracts = load_all_contracts()
        system_prompt = build_system_prompt(contracts)
    except Exception as err:
        return JSONResponse({"error": f"Failed to load contracts: {err}"}, status_code=500)

    if auto_retry:
        return _run_auto_evolve_loop(
            client, model_name, system_prompt, req_text, session_id, now_iso
        )

    # --- Standard single-shot path (original behaviour) ---
    try:
        context = build_evolution_context(req_text)
        proposal, generation_ms = _generate_proposal(client, model_name, system_prompt, context)

        fast = is_fast_path(proposal)
        path_type = "fast" if fast else "full"

        proposal_record = {
            "id": session_id, "timestamp": now_iso, "request": req_text, "model": model_name,
            "scope": proposal.scope, "target": proposal.target,
            "artifact_manifest": proposal.artifact_manifest,
            "path": path_type, "status": "pending_review", "human_approved": False,
            "plan": proposal.plan, "files_touched": proposal.files_touched,
            "generation_ms": generation_ms,
            "failure_chain": [],
        }
        pending_file = PENDING_DIR / f"{session_id}.json"
        pending_file.write_text(
            json.dumps({"meta": proposal_record, "proposal": proposal.model_dump()}, indent=2),
            encoding="utf-8",
        )
        append_log(proposal_record)

        return JSONResponse({
            "id": session_id, "scope": proposal.scope, "target": proposal.target,
            "artifact_manifest": proposal.artifact_manifest,
            "path": path_type, "status": "pending_review",
            "plan": proposal.plan, "files_touched": proposal.files_touched,
        })

    except Exception as err:
        error_msg = str(err)
        provider = classify_provider_error(err)
        append_log({
            "id": session_id, "timestamp": now_iso, "request": req_text, "model": model_name,
            "path": "none", "status": "failed", "error": error_msg, "provider": provider,
        })
        status_code = 400 if isinstance(err, (ValueError, json.JSONDecodeError)) else 500
        if status_code == 500:
            status_code = provider["status_code"]
        return JSONResponse({
            "error": f"Proposal generation failed: {error_msg}",
            "provider": provider,
        }, status_code=status_code)


async def validate_proposal_endpoint(request: Request):
    return JSONResponse(validate_proposal(request.path_params["request_id"]))


async def approve_proposal_endpoint(request: Request):
    """
    New: the explicit human-approval step 'full' path proposals now require
    before apply_proposal() will touch them (see FIX #4).
    """
    request_id = request.path_params["request_id"]
    proposal_file = PENDING_DIR / f"{request_id}.json"
    if not proposal_file.exists():
        return JSONResponse({"error": "Proposal not found"}, status_code=404)
    data = json.loads(proposal_file.read_text(encoding="utf-8"))
    proposal = ProposalOutput.model_validate(data.get("proposal", {}))
    registration_created = False
    if proposal.registration_request is not None:
        validation = validate_proposal(request_id)
        if not validation.get("valid"):
            return JSONResponse(
                {
                    "error": "Registration proposals must pass validation before approval.",
                    "validation": validation,
                },
                status_code=422,
            )
        try:
            registration_created = install_approved_registration(
                proposal.registration_request
            )
        except (ValueError, json.JSONDecodeError) as error:
            return JSONResponse({"error": str(error)}, status_code=400)
    data["meta"]["human_approved"] = True
    data["meta"]["status"] = "approved"
    if proposal.registration_request is not None:
        data["meta"]["registration_approved"] = True
    proposal_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    append_log({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "action": "approve",
        "status": "approved",
        "registration_created": registration_created,
    })
    return JSONResponse({
        "id": request_id,
        "status": "approved",
        "registration_created": registration_created,
    })


async def apply_proposal_endpoint(request: Request):
    return JSONResponse(apply_proposal(request.path_params["request_id"]))


app = Starlette(
    routes=[
        Route("/health", health),
        Route("/proposals", list_proposals),
        Route("/proposals/{request_id}", get_proposal),
        Route("/evolve", evolve, methods=["POST"]),
        Route("/proposals/{request_id}/validate", validate_proposal_endpoint, methods=["POST"]),
        Route("/proposals/{request_id}/approve", approve_proposal_endpoint, methods=["POST"]),
        Route("/proposals/{request_id}/apply", apply_proposal_endpoint, methods=["POST"]),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:4173", "http://127.0.0.1:4173"],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type"],
        )
    ],
)
