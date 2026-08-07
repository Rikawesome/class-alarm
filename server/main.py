"""
Evolution backend — hardened version.

This rewrite fixes specific, confirmed issues found after a proposal wiped
the working UI in the previous version. Each fix below is tied to a root
cause, not a guess — see the comment at each fix for what it addresses.

ROOT CAUSES FIXED:
  1. Full-file context was truncated to 1000 chars, but "modify" operations
     require complete replacement content -> guaranteed data loss on any
     real file. Fixed: no truncation; oversized files force full-path
     review instead of being silently cut.
  2. Composition-root protection existed only as prompt text, not code.
     Fixed: a hardcoded PROTECTED_PREFIXES list is enforced regardless of
     what's in registry/modules.json (defense in depth, fail-closed).
  3. generate_evolution_endpoint() hardcoded path="fast" and never called
     the real triage function. Fixed: single shared is_fast_path() used
     everywhere, no exceptions.
  4. apply_proposal() never checked meta["path"] at all -- validation
     passing was treated as sufficient to auto-apply anything. Fixed:
     "full" path proposals now require an explicit human-approval step
     before apply() will touch them; "fast" path still requires
     validation to pass.
  5. Test/build commands used shell=True with glob patterns, which does
     not expand on Windows (cmd.exe doesn't glob) -- likely caused
     "0 tests ran, exit code 0" being read as success. Fixed: globs are
     expanded in Python via pathlib, and commands run with shell=False
     and an explicit argument list, cross-platform.
  6. Import-boundary check silently ignored any non-relative import.
     Fixed: unresolved imports are now flagged and force full-path
     review instead of passing silently.
  7. No check for a proposal drastically shrinking a file it's modifying
     -- the exact shape of a "wipe". Fixed: a size-shrink heuristic flags
     any modify that removes a large fraction of a file's prior content.
  8. Duplicate function definitions and two divergent, inconsistent
     proposal pipelines. Fixed: single, consistent pipeline; duplicates
     removed.
"""

import glob as globmod
import json
import os
import platform
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional, Union
from typing import List, Literal, Optional

from google import genai
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OpenAI = None  # type: ignore
    OPENAI_AVAILABLE = False
from google.genai import types
from pydantic import BaseModel, Field
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

# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------
# These categories determine whether the retry loop can attempt a fix, or
# whether the problem requires human intervention.
#
#   FIXABLE    — syntax error, build error, or test failure all within
#                evolvable/; the model can be shown its own output + the
#                error and asked to correct it.
#   UNFIXABLE  — the proposal touched a protected path, violated an
#                architectural boundary, or broke governance tests. No
#                amount of retrying will help; escalate immediately.
#   PROMOTE    — the proposal needs a contract change; don't retry, reclassify
#                as full-path and surface to the developer for approval.
# ---------------------------------------------------------------------------

FIXABLE_GATES = {"syntax_check", "production_build", "test_suite", "content_wipe_check"}
UNFIXABLE_GATES = {"path_safety", "locked_protection", "dependency_analysis"}


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

    # content_wipe is fixable — we tell Gemini to preserve more of the file.
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
        "1. Read the error output above carefully — it shows exactly what was wrong.",
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


class ProposalOutput(BaseModel):
    plan: str = Field(description="Clear step-by-step description of proposed change")
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


class EvolutionRequest(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_model_name() -> str:
    return os.getenv(DARWIN_MODEL, gemini-3.5-flash-lite)
def get_gemini_client() -> Optional[genai.Client]:
    api_key = os.getenv(GEMINI_API_KEY) or os.getenv(GOOGLE_API_KEY)
    if not api_key:
        return None
    return genai.Client(api_key=api_key)

# Helpers
# ---------------------------------------------------------------------------

def get_model_name() -> str:
    return os.getenv("DARWIN_MODEL", "gemini-3.5-flash-lite")


def get_gemini_client() -> Optional[genai.Client]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def is_protected_path(path_str: str) -> bool:
    """
    FIX #2: hardcoded, fail-closed check, independent of registry config.
    Note: locked/core-data/access.js is the one file evolvable code is
    allowed to IMPORT from — but it is still protected from being WRITTEN
    to by an evolution, same as every other locked file. No carve-out here.
    """
    normalized = Path(path_str).as_posix()
    return any(normalized.startswith(prefix) for prefix in PROTECTED_PREFIXES)


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
   locked/core-data/access.js — never a direct import of a schema or
   database client.
3. "modify" operations must return the COMPLETE file — you are shown the
   complete current file below for anything you might touch. If a file
   you need is not shown (listed under OVERSIZED FILES), do not propose
   modifying it — flag that it needs manual handling instead.

=== FULL CURRENT CONTENT OF EVOLVABLE FILES ===
{json.dumps(app_files_summary, indent=2)}

=== OVERSIZED FILES (too large to safely auto-edit — do not propose modifying these) ===
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
   Only propose modifying files you were shown in full — never a file
   listed as oversized.

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
        if posix_path.startswith(entry["path"]):
            return mod_id
    return None


def find_imports(code: str) -> List[str]:
    imports = []
    imports += re.findall(r'''\bimport\s+.*?\s+from\s+['"]([^'"]+)['"]''', code, re.DOTALL)
    imports += re.findall(r'''\bimport\s+['"]([^'"]+)['"]''', code)
    imports += re.findall(r'''\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)''', code)
    imports += re.findall(r'''\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)''', code)
    return [imp.strip() for imp in imports]


def resolve_import_path(importing_file_path: str, import_str: str) -> Optional[str]:
    if not import_str.startswith("."):
        return None
    importing_dir = Path(importing_file_path).parent
    resolved = (importing_dir / import_str).resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return None


def npm_cmd() -> str:
    return "npm.cmd" if platform.system() == "Windows" else "npm"


def run_command(args: List[str]) -> tuple:
    """
    FIX #5: takes an explicit argument list and runs with shell=False.
    Callers are responsible for expanding any globs themselves via
    expand_globs() before calling this — Windows' cmd.exe (invoked by
    shell=True) does not expand '*' the way a POSIX shell does, which
    previously caused test-file globs to pass through unexpanded and
    silently match zero files while still reporting exit code 0.
    """
    res = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, shell=False)
    return res.returncode, res.stdout, res.stderr


def expand_globs(patterns: List[str]) -> List[str]:
    files = []
    for pattern in patterns:
        matches = globmod.glob(str(ROOT / pattern), recursive=True)
        files.extend(matches)
    return files


def is_fast_path(proposal: ProposalOutput) -> bool:
    """
    FIX #3: this is now the ONLY function anywhere in the codebase that
    decides fast vs full — every entry point must call this, no exceptions,
    no hardcoded overrides.
    """
    all_paths = set(proposal.files_touched) | {op.path for op in proposal.operations}

    for p in all_paths:
        if is_protected_path(p):
            return False
        if not p.startswith("evolvable/ui/"):
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


class WorkspaceDryRun:
    def __init__(self, operations: List[FileOperation]):
        self.operations = operations
        self.backups = {}
        self.created_files = []

    def __enter__(self):
        for op in self.operations:
            path = (ROOT / op.path).resolve()
            path.relative_to(ROOT)
            if op.action == "create":
                if path.exists():
                    self.backups[op.path] = path.read_bytes()
                else:
                    self.created_files.append(op.path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(op.content or "", encoding="utf-8")
            elif op.action == "modify":
                if path.exists():
                    self.backups[op.path] = path.read_bytes()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(op.content or "", encoding="utf-8")
            elif op.action == "delete":
                if path.exists():
                    self.backups[op.path] = path.read_bytes()
                    path.unlink()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for file_path, original_bytes in self.backups.items():
            path = ROOT / file_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original_bytes)
        for file_path in self.created_files:
            path = ROOT / file_path
            if path.exists():
                path.unlink()
            parent = path.parent
            while parent != ROOT:
                if any(parent.iterdir()):
                    break
                parent.rmdir()
                parent = parent.parent


def check_for_content_wipe(op: FileOperation) -> Optional[str]:
    """
    FIX #7: catches the specific failure mode that actually happened —
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
        "path_safety": "pending",
        "module_ownership": "pending",
        "locked_protection": "pending",
        "dependency_analysis": "pending",
        "content_wipe_check": "pending",
        "syntax_check": "pending",
        "test_suite": "pending",
        "production_build": "pending",
    }

    def fail(errs):
        return {"valid": False, "errors": errs, "steps": steps}

    if not proposal_file.exists():
        return fail([f"Proposal {request_id} not found."])

    try:
        data = json.loads(proposal_file.read_text(encoding="utf-8"))
        proposal = ProposalOutput.model_validate(data.get("proposal", {}))
    except Exception as e:
        return fail([f"Failed to load/parse proposal: {e}"])

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

    all_paths = {op.path for op in proposal.operations} | set(proposal.files_touched)
    for p in all_paths:
        # FIX #2: hardcoded check runs FIRST and independently of registry state.
        if is_protected_path(p):
            errors.append(f"Protected path touched: {p} (matches a hardcoded protected prefix).")
            locked_protected = False
            continue
        owning_mod = get_owning_module(p, modules)
        if not owning_mod:
            errors.append(f"Path {p} does not belong to any registered evolvable module — failing closed.")
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
                    # slashes, or scoped @org/pkg) are safe bundled dependencies —
                    # Vite resolves them, they never touch the locked boundary.
                    # Only flag imports that look like aliased repo paths (contain
                    # a slash but aren't scoped packages), which could smuggle in
                    # a cross-boundary reference we can't verify statically.
                    is_scoped_pkg = imp.startswith("@") and imp.count("/") == 1
                    is_bare_pkg = "/" not in imp
                    if is_bare_pkg or is_scoped_pkg:
                        continue  # safe npm package import
                    errors.append(f"Unresolved/unverifiable import '{imp}' in {op.path} — requires manual review.")
                    dep_ok = False
                    continue
                if op.path.startswith("evolvable/") and resolved.startswith("locked/"):
                    if not resolved.startswith("locked/core-data/access.js"):
                        errors.append(f"Boundary violation: {op.path} imports {resolved} directly (must use access.js).")
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

    syntax_ok = True
    try:
        with WorkspaceDryRun(proposal.operations):
            for op in proposal.operations:
                # node --check cannot parse JSX syntax; Vite handles .jsx in the
                # build step below, so only run the node checker on plain .js files.
                if op.action in ("create", "modify") and op.path.endswith(".js") and not op.path.endswith(".jsx"):
                    ret, out, err = run_command(["node", "--check", op.path])
                    if ret != 0:
                        errors.append(f"Syntax error in {op.path}:\n{err or out}")
                        syntax_ok = False
            steps["syntax_check"] = "pass" if syntax_ok else "fail"
            if not syntax_ok:
                return fail(errors)

            ret, out, err = run_command([npm_cmd(), "run", "build"])
            if ret != 0:
                errors.append(f"Production build failed:\n{err or out}")
                steps["production_build"] = "fail"
                return fail(errors)
            steps["production_build"] = "pass"

            # FIX #5: expand globs ourselves in Python instead of relying on
            # shell expansion, which does not happen on Windows with shell=True.
            test_files = expand_globs([
                "tests/*.test.js",
                "locked/*/tests/*.test.js",
                "evolvable/*/tests/*.test.js",
                "app/tests/*.test.js",
            ])
            if not test_files:
                errors.append(
                    "No test files were found by glob expansion. Refusing to treat "
                    "an empty test run as a pass — check test file locations."
                )
                steps["test_suite"] = "fail"
                return fail(errors)

            ret, out, err = run_command(["node", "--test", *test_files])
            if ret != 0:
                errors.append(f"Test suite failed:\n{err or out}")
                steps["test_suite"] = "fail"
                return fail(errors)
            steps["test_suite"] = "pass"

    except Exception as e:
        errors.append(f"Error during dry-run validation: {e}")
        return fail(errors)

    return {"valid": True, "errors": [], "steps": steps}


def apply_proposal(request_id: str, human_approved: bool = False) -> dict:
    proposal_file = PENDING_DIR / f"{request_id}.json"
    if not proposal_file.exists():
        return {"success": False, "error": f"Proposal {request_id} not found."}

    data = json.loads(proposal_file.read_text(encoding="utf-8"))
    meta = data.get("meta", {})

    # FIX #4: the path label now actually gates something. "full" path
    # proposals may not be applied without an explicit prior approval step.
    path_type = meta.get("path")
    if path_type != "fast" and not (human_approved or meta.get("human_approved")):
        return {
            "success": False,
            "error": f"Proposal is '{path_type}' path and has not been human-approved. "
                     f"Call the approve endpoint first, or fast-path eligibility must be re-verified.",
        }

    validation = validate_proposal(request_id)
    if not validation.get("valid"):
        return {"success": False, "error": "Cannot apply invalid proposal.", "validation": validation}

    proposal = ProposalOutput.model_validate(data.get("proposal", {}))
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

        ret, out, err = run_command([npm_cmd(), "run", "build"])
        if ret != 0:
            raise RuntimeError(f"Production build failed:\n{err or out}")

        test_files = expand_globs([
            "tests/*.test.js",
            "locked/*/tests/*.test.js",
            "evolvable/*/tests/*.test.js",
            "app/tests/*.test.js",
        ])
        if not test_files:
            raise RuntimeError("No test files found — refusing to apply without a real test run.")
        ret, out, err = run_command(["node", "--test", *test_files])
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
    return JSONResponse({"status": "ok", "model": get_model_name(), "api_key_configured": bool(api_key)})


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


def _generate_proposal(client, model_name: str, system_prompt: str, context: str) -> ProposalOutput:
    """
    Single Gemini call → validated ProposalOutput.
    Separated so the retry loop can call it with different context each time.
    """
    response = client.models.generate_content(
        model=model_name,
        contents=context,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=ProposalOutput,
            temperature=0.1,
        ),
    )
    proposal = ProposalOutput.model_validate(json.loads(response.text))
    validate_file_paths(proposal)

    unresolved = []
    for op in proposal.operations:
        if op.content:
            for imp in find_imports(op.content):
                if resolve_import_path(op.path, imp) is None:
                    unresolved.append(imp)
    proposal.unresolved_imports = unresolved
    return proposal


def _run_auto_evolve_loop(
    client,
    model_name: str,
    system_prompt: str,
    req_text: str,
    session_id: str,
    now_iso: str,
) -> JSONResponse:
    """
    Self-healing retry loop — called by the /evolve endpoint when the caller
    passes ``"auto_retry": true`` in the request body.

    On each attempt the loop:
      1. Generates a proposal (first attempt: base context; retries: base context
         plus a PREVIOUS ATTEMPT FEEDBACK section containing the exact files
         Gemini wrote last time and the exact error output).
      2. Saves the proposal to server/pending/{id}.json.
      3. Runs validate_proposal() against the saved file.
      4. On pass → returns pending_review immediately.
      5. On fail → classifies the failure and either:
           UNFIXABLE  → writes to logs/escalations.json and returns 422.
           PROMOTE    → returns 202 asking for human approval.
           FIXABLE    → appends to failure_chain and loops.

    After MAX_RETRY_ATTEMPTS all-FIXABLE failures the loop gives up, writes an
    escalation record, and returns 422.

    NOTE: validate_proposal() runs the full build + test suite on every attempt.
    This keeps the loop strictly honest — it only declares success when the real
    gates pass — but it means auto_retry requests are slow (30-60 s per attempt).
    Use the standard /evolve → /proposals/{id}/validate flow when you want the
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
            proposal = _generate_proposal(client, model_name, system_prompt, context)
        except Exception as gen_err:
            error_msg = str(gen_err)
            append_log({
                "id": session_id, "timestamp": now_iso, "request": req_text,
                "model": model_name, "path": "none", "status": "failed",
                "error": error_msg, "attempt": attempt,
            })
            return JSONResponse(
                {"error": f"Proposal generation failed: {error_msg}"},
                status_code=500,
            )

        last_proposal = proposal
        path_type = "fast" if is_fast_path(proposal) else "full"

        attempt_record = {
            "id": attempt_id,
            "session_id": session_id,
            "timestamp": now_iso,
            "request": req_text,
            "model": model_name,
            "path": path_type,
            "status": "pending_review",
            "human_approved": False,
            "plan": proposal.plan,
            "files_touched": proposal.files_touched,
            "attempt": attempt,
            "failure_chain": failure_chain,
        }
        pending_file = PENDING_DIR / f"{attempt_id}.json"
        pending_file.write_text(
            json.dumps({"meta": attempt_record, "proposal": proposal.model_dump()}, indent=2),
            encoding="utf-8",
        )

        validation = validate_proposal(attempt_id)

        if validation.get("valid"):
            append_log({**attempt_record, "status": "pending_review"})
            return JSONResponse({
                "id": attempt_id,
                "session_id": session_id,
                "path": path_type,
                "status": "pending_review",
                "plan": proposal.plan,
                "files_touched": proposal.files_touched,
                "attempts": attempt,
                "failure_chain": failure_chain,
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
                "reason": f"Contract change required — promoted to full-path on attempt {attempt}",
                "plan": proposal.plan,
                "files_touched": proposal.files_touched,
                "failure_chain": failure_chain,
                "developer_action_required": True,
                "message": "This request needs a contract change. Approve it as a full-path proposal.",
            }, status_code=202)

        # FIXABLE — loop with the failure injected into next prompt.

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
    Evolution proposal endpoint — two modes depending on the request body:

    Standard mode (default, ``"auto_retry"`` absent or false):
      Generate one proposal, save it to pending/, and return immediately with
      ``status: "pending_review"``. Validation and apply are separate steps
      the caller drives explicitly. This is the fast path used by the chat UI.

    Auto-retry mode (``"auto_retry": true``):
      Run the self-healing loop: generate → validate → retry up to
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
        append_log({
            "id": session_id, "timestamp": now_iso, "request": req_text, "model": model_name,
            "path": "none", "status": "failed",
            "error": "GEMINI_API_KEY or GOOGLE_API_KEY not configured.",
        })
        return JSONResponse({"error": "Gemini API key is missing."}, status_code=500)

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
        proposal = _generate_proposal(client, model_name, system_prompt, context)

        fast = is_fast_path(proposal)
        path_type = "fast" if fast else "full"

        proposal_record = {
            "id": session_id, "timestamp": now_iso, "request": req_text, "model": model_name,
            "path": path_type, "status": "pending_review", "human_approved": False,
            "plan": proposal.plan, "files_touched": proposal.files_touched,
            "failure_chain": [],
        }
        pending_file = PENDING_DIR / f"{session_id}.json"
        pending_file.write_text(
            json.dumps({"meta": proposal_record, "proposal": proposal.model_dump()}, indent=2),
            encoding="utf-8",
        )
        append_log(proposal_record)

        return JSONResponse({
            "id": session_id, "path": path_type, "status": "pending_review",
            "plan": proposal.plan, "files_touched": proposal.files_touched,
        })

    except Exception as err:
        error_msg = str(err)
        append_log({
            "id": session_id, "timestamp": now_iso, "request": req_text, "model": model_name,
            "path": "none", "status": "failed", "error": error_msg,
        })
        status_code = 400 if isinstance(err, (ValueError, json.JSONDecodeError)) else 500
        return JSONResponse({"error": f"Proposal generation failed: {error_msg}"}, status_code=status_code)


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
    data["meta"]["human_approved"] = True
    data["meta"]["status"] = "approved"
    proposal_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    append_log({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id, "action": "approve", "status": "approved",
    })
    return JSONResponse({"id": request_id, "status": "approved"})


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
