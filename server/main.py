"""
Evolution backend - MVP version (Gemini Integration & Proposal Generation).

Converts natural language evolution requests into structured, reviewable proposals
without modifying working application files. Evaluates fast-path vs full-path
eligibility based on registry contracts and module boundaries.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "registry" / "modules.json"
LOG_PATH = ROOT / "logs" / "evolution-log.json"
PENDING_DIR = ROOT / "server" / "pending"
PENDING_DIR.mkdir(exist_ok=True)


def load_env_file():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

load_env_file()


class FileOperation(BaseModel):
    action: Literal["create", "modify", "delete"]
    path: str
    content: Optional[str] = Field(
        default=None,
        description="Complete updated or created file content if action is modify or create",
    )


class ContractEffects(BaseModel):
    new_contract_fields: List[str] = Field(
        default_factory=list, description="Any new fields added to contracts"
    )
    modified_contracts: List[str] = Field(
        default_factory=list, description="Contract file paths modified"
    )


class TestEffects(BaseModel):
    new_tests: List[str] = Field(
        default_factory=list, description="New test file paths created"
    )
    modified_tests: List[str] = Field(
        default_factory=list, description="Existing test file paths modified"
    )




class EvolutionProposal(BaseModel):
    plan_id: str = Field(description="The plan ID this proposal implements")
    description: str = Field(description="Description of the implemented changes")
    operations: List[FileOperation] = Field(description="Explicit file operations generated from the plan")


class EvolutionPlan(BaseModel):
    intent: str = Field(description="The original user intent or natural language evolution request")
    affected_modules: List[str] = Field(description="List of module IDs affected by this change (e.g. ['ui', 'core-data'])")
    composition_changes: List[str] = Field(description="Explicit description of changes needed in the composition root (e.g. importing and rendering components in App.jsx)")
    files_to_modify: List[str] = Field(description="List of existing files to be modified")
    files_to_create: List[str] = Field(description="List of new files to be created")
    required_contracts: List[str] = Field(description="Module contracts that must be respected during implementation")
    validation_checks: List[str] = Field(description="Specific validation checks the runtime should run (e.g. ['component_mounted', 'build_required', 'routing_updated'])")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0 in this plan's feasibility and safety")
    risk_level: str = Field(description="Risk classification: 'low', 'medium', or 'high'")


class ProposalOutput(BaseModel):
    plan: str = Field(
        description="Clear step-by-step description of proposed change"
    )
    files_touched: List[str] = Field(
        description="All file paths relative to repository root that will be created, modified, or deleted"
    )
    operations: List[FileOperation] = Field(
        description="Explicit operations to execute on touched files"
    )
    contract_effects: ContractEffects = Field(default_factory=ContractEffects)
    test_effects: TestEffects = Field(default_factory=TestEffects)
    new_locked_imports: List[str] = Field(
        default_factory=list,
        description="Any new imports from locked/ core modules introduced by this change",
    )


class EvolutionRequest(BaseModel):
    text: str


def get_model_name() -> str:
    return os.getenv("DARWIN_MODEL", "gemini-3.5-flash-lite")


def get_gemini_client() -> Optional[genai.Client]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def load_all_contracts() -> dict:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    contracts = {}

    for module_id, entry in registry.get("modules", {}).items():
        contract_path = (ROOT / entry["contract"]).resolve()

        try:
            contract_path.relative_to(ROOT)
        except ValueError as err:
            raise ValueError(
                f"Contract path for {module_id} is outside the workspace: "
                f"{entry['contract']}"
            ) from err

        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if contract.get("module") != module_id:
            raise ValueError(
                f"Contract identity mismatch for {module_id}: "
                f"{contract.get('module')!r}"
            )

        contracts[module_id] = contract

    return contracts


def build_system_prompt(contracts: dict) -> str:
    return f"""You are an evolution proposal generator for a modular application called Class Alarm.

Here are the canonical module contracts loaded through registry/modules.json:

{json.dumps(contracts, indent=2)}

Architectural invariants to observe:
1. Never propose changes under locked/.
2. Presentation changes should touch evolvable/ui/ only.
3. Feature additions should reside in evolvable/features/.
4. Evolvable modules must not import any module under locked/. They use declared application HTTP APIs instead.
5. Files owned by app-runtime, web-shell, evolution-server, or governance require human review and are outside the autonomous fast path.

Given a user's plain-language evolution request, create a concrete change proposal matching the exact JSON schema requested.
Do not modify files directly; produce the structured proposal object."""


def append_log(entry: dict):
    log = []
    if LOG_PATH.exists():
        try:
            log = json.loads(LOG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log = []
    log.append(entry)
    LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")


def is_fast_path(proposal: ProposalOutput) -> bool:
    for file_path in proposal.files_touched:
        if not file_path.startswith("evolvable/ui/"):
            return False

    for op in proposal.operations:
        if not op.path.startswith("evolvable/ui/"):
            return False

    if proposal.contract_effects.new_contract_fields or proposal.contract_effects.modified_contracts:
        return False

    if proposal.new_locked_imports:
        return False

    return True


def validate_file_paths(proposal: ProposalOutput):
    for file_path in proposal.files_touched:
        normalized = Path(file_path)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError(f"Path traversal or absolute path detected: {file_path}")

    for op in proposal.operations:
        normalized = Path(op.path)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError(f"Path traversal or absolute path detected: {op.path}")


async def health(request: Request):
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    return JSONResponse({
        "status": "ok",
        "model": get_model_name(),
        "api_key_configured": bool(api_key),
    })


async def list_proposals(request: Request):
    if not LOG_PATH.exists():
        return JSONResponse([])
    try:
        log = json.loads(LOG_PATH.read_text(encoding="utf-8"))
        return JSONResponse(log)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_proposal(request: Request):
    request_id = request.path_params["request_id"]
    proposal_file = PENDING_DIR / f"{request_id}.json"
    if not proposal_file.exists():
        return JSONResponse({"error": "Proposal not found"}, status_code=404)
    try:
        data = json.loads(proposal_file.read_text(encoding="utf-8"))
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def evolve(request: Request):
    request_id = str(uuid.uuid4())
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
        entry = {
            "id": request_id,
            "timestamp": now_iso,
            "request": req_text,
            "model": model_name,
            "path": "none",
            "status": "failed",
            "error": "GEMINI_API_KEY or GOOGLE_API_KEY environment variable is not configured.",
        }
        append_log(entry)
        return JSONResponse(
            {"error": "Gemini API key is missing. Set GEMINI_API_KEY environment variable."},
            status_code=500,
        )

    contracts = load_all_contracts()

    system_prompt = build_system_prompt(contracts)

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=req_text,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=ProposalOutput,
            ),
        )

        raw_json = response.text
        proposal_dict = json.loads(raw_json)
        proposal = ProposalOutput.model_validate(proposal_dict)

        validate_file_paths(proposal)

        fast = is_fast_path(proposal)
        path_type = "fast" if fast else "full"

        proposal_record = {
            "id": request_id,
            "timestamp": now_iso,
            "request": req_text,
            "model": model_name,
            "path": path_type,
            "status": "pending_review",
            "plan": proposal.plan,
            "files_touched": proposal.files_touched,
            "operations_count": len(proposal.operations),
            "contract_effects": proposal.contract_effects.model_dump(),
            "test_effects": proposal.test_effects.model_dump(),
        }

        pending_file = PENDING_DIR / f"{request_id}.json"
        pending_data = {
            "meta": proposal_record,
            "proposal": proposal.model_dump(),
        }
        pending_file.write_text(json.dumps(pending_data, indent=2), encoding="utf-8")

        append_log(proposal_record)

        return JSONResponse({
            "id": request_id,
            "path": path_type,
            "status": "pending_review",
            "plan": proposal.plan,
            "files_touched": proposal.files_touched,
        })

    except Exception as err:
        error_msg = str(err)
        failure_entry = {
            "id": request_id,
            "timestamp": now_iso,
            "request": req_text,
            "model": model_name,
            "path": "none",
            "status": "failed",
            "error": error_msg,
        }
        append_log(failure_entry)
        status_code = 400 if isinstance(err, (ValueError, json.JSONDecodeError)) else 500
        return JSONResponse(
            {"error": f"Proposal generation failed: {error_msg}"},
            status_code=status_code,
        )



import subprocess
import re

def get_owning_module(file_path: str, modules: dict) -> Optional[str]:
    posix_path = Path(file_path).as_posix()
    sorted_modules = sorted(modules.items(), key=lambda x: len(x[1]["path"]), reverse=True)
    for mod_id, entry in sorted_modules:
        mod_prefix = entry["path"]
        if posix_path.startswith(mod_prefix):
            return mod_id
    return None

def find_imports(code: str) -> List[str]:
    imports = []
    static_matches = re.findall(r'''\bimport\s+.*?\s+from\s+['\"]([^\'\"]+)['\"]''', code, re.DOTALL)
    imports.extend(static_matches)
    simple_static_matches = re.findall(r'''\bimport\s+['\"]([^\'\"]+)['\"]''', code)
    imports.extend(simple_static_matches)
    dynamic_matches = re.findall(r'''\bimport\s*\(\s*['\"]([^\'\"]+)['\"]\s*\)''', code)
    imports.extend(dynamic_matches)
    require_matches = re.findall(r'''\brequire\s*\(\s*['\"]([^\'\"]+)['\"]\s*\)''', code)
    imports.extend(require_matches)
    return [imp.strip() for imp in imports]

def resolve_import_path(importing_file_path: str, import_str: str) -> Optional[str]:
    if not import_str.startswith("."):
        return None
    importing_dir = Path(importing_file_path).parent
    resolved = (importing_dir / import_str).resolve()
    try:
        relative = resolved.relative_to(ROOT)
        return relative.as_posix()
    except ValueError:
        return None

def run_command(cmd: str) -> tuple:
    res = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        shell=True
    )
    return res.returncode, res.stdout, res.stderr

class WorkspaceDryRun:
    def __init__(self, operations):
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

def validate_proposal(request_id: str) -> dict:
    proposal_file = PENDING_DIR / f"{request_id}.json"
    if not proposal_file.exists():
        return {
            "valid": False,
            "errors": [f"Proposal {request_id} not found."],
            "steps": {
                "module_ownership": "fail",
                "locked_protection": "fail",
                "dependency_analysis": "fail",
                "syntax_check": "fail",
                "test_suite": "fail",
                "production_build": "fail"
            }
        }
        
    try:
        data = json.loads(proposal_file.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "valid": False,
            "errors": [f"Failed to parse proposal file: {str(e)}"],
            "steps": {
                "module_ownership": "fail",
                "locked_protection": "fail",
                "dependency_analysis": "fail",
                "syntax_check": "fail",
                "test_suite": "fail",
                "production_build": "fail"
            }
        }
        
    proposal_dict = data.get("proposal", {})
    try:
        proposal = ProposalOutput.model_validate(proposal_dict)
    except Exception as e:
        return {
            "valid": False,
            "errors": [f"Proposal does not match schema: {str(e)}"],
            "steps": {
                "module_ownership": "fail",
                "locked_protection": "fail",
                "dependency_analysis": "fail",
                "syntax_check": "fail",
                "test_suite": "fail",
                "production_build": "fail"
            }
        }

    errors = []
    steps = {
        "module_ownership": "pending",
        "locked_protection": "pending",
        "dependency_analysis": "pending",
        "syntax_check": "pending",
        "test_suite": "pending",
        "production_build": "pending"
    }

    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        modules = registry.get("modules", {})
    except Exception as e:
        errors.append(f"Failed to load registry: {str(e)}")
        return {"valid": False, "errors": errors, "steps": steps}

    try:
        validate_file_paths(proposal)
    except ValueError as e:
        errors.append(str(e))
        steps["locked_protection"] = "fail"
        return {"valid": False, "errors": errors, "steps": steps}

    ownership_ok = True
    locked_protected = True
    
    for op in proposal.operations:
        owning_mod = get_owning_module(op.path, modules)
        if not owning_mod:
            errors.append(f"File path {op.path} does not belong to any registered module.")
            ownership_ok = False
        else:
            policy = modules[owning_mod].get("evolution_policy", "locked")
            if policy == "locked":
                errors.append(f"Modification of locked module file {op.path} (owned by {owning_mod}) is forbidden.")
                locked_protected = False

    for path in proposal.files_touched:
        owning_mod = get_owning_module(path, modules)
        if not owning_mod:
            errors.append(f"Touched path {path} does not belong to any registered module.")
            ownership_ok = False
        else:
            policy = modules[owning_mod].get("evolution_policy", "locked")
            if policy == "locked":
                errors.append(f"Touching locked module file {path} (owned by {owning_mod}) is forbidden.")
                locked_protected = False

    steps["module_ownership"] = "pass" if ownership_ok else "fail"
    steps["locked_protection"] = "pass" if locked_protected else "fail"

    dep_analysis_ok = True
    for op in proposal.operations:
        if op.action in ("create", "modify") and op.content:
            imports = find_imports(op.content)
            for imp in imports:
                resolved_target = resolve_import_path(op.path, imp)
                if resolved_target:
                    if op.path.startswith("evolvable/") and resolved_target.startswith("locked/"):
                        errors.append(f"Boundary Violation: Evolvable file {op.path} imports from locked module path: {resolved_target}")
                        dep_analysis_ok = False
                    if op.path.startswith("locked/") and resolved_target.startswith("evolvable/"):
                        errors.append(f"Boundary Violation: Locked file {op.path} imports from evolvable module path: {resolved_target}")
                        dep_analysis_ok = False

    steps["dependency_analysis"] = "pass" if dep_analysis_ok else "fail"

    if errors:
        return {"valid": False, "errors": errors, "steps": steps}

    syntax_ok = True
    tests_ok = True
    build_ok = True

    try:
        with WorkspaceDryRun(proposal.operations):
            for op in proposal.operations:
                if op.action in ("create", "modify") and op.path.endswith(".js"):
                    ret, out, err = run_command(f"node --check {op.path}")
                    if ret != 0:
                        errors.append(f"Syntax Error in {op.path}:\n{err or out}")
                        syntax_ok = False
            
            steps["syntax_check"] = "pass" if syntax_ok else "fail"
            if not syntax_ok:
                return {"valid": False, "errors": errors, "steps": steps}

            ret, out, err = run_command("npm run build")
            if ret != 0:
                errors.append(f"Production Build Failed:\n{err or out}")
                build_ok = False
            
            steps["production_build"] = "pass" if build_ok else "fail"
            if not build_ok:
                return {"valid": False, "errors": errors, "steps": steps}

            ret, out, err = run_command("node --test tests/*.test.js locked/*/tests/*.test.js app/tests/*.test.js")
            if ret != 0:
                errors.append(f"Test Suite Failed:\n{err or out}")
                tests_ok = False
            
            steps["test_suite"] = "pass" if tests_ok else "fail"
            if not tests_ok:
                return {"valid": False, "errors": errors, "steps": steps}

    except Exception as e:
        errors.append(f"Error during dry-run validation: {str(e)}")
        steps["syntax_check"] = "fail" if steps["syntax_check"] == "pending" else steps["syntax_check"]
        steps["production_build"] = "fail" if steps["production_build"] == "pending" else steps["production_build"]
        steps["test_suite"] = "fail" if steps["test_suite"] == "pending" else steps["test_suite"]
        return {"valid": False, "errors": errors, "steps": steps}

    return {
        "valid": True,
        "errors": [],
        "steps": {
            "module_ownership": "pass",
            "locked_protection": "pass",
            "dependency_analysis": "pass",
            "syntax_check": "pass",
            "test_suite": "pass",
            "production_build": "pass"
        }
    }

async def validate_proposal_endpoint(request: Request):
    request_id = request.path_params["request_id"]
    report = validate_proposal(request_id)
    return JSONResponse(report)



def apply_proposal(request_id: str) -> dict:
    proposal_file = PENDING_DIR / f"{request_id}.json"
    if not proposal_file.exists():
        return {"success": False, "error": f"Proposal {request_id} not found."}

    validation = validate_proposal(request_id)
    if not validation.get("valid"):
        return {
            "success": False,
            "error": "Cannot apply invalid or unverified proposal.",
            "validation": validation
        }

    data = json.loads(proposal_file.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    proposal_dict = data.get("proposal", {})
    proposal = ProposalOutput.model_validate(proposal_dict)

    backups = {}
    created_files = []

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
            if op.action in ("create", "modify") and op.path.endswith(".js"):
                ret, out, err = run_command(f"node --check {op.path}")
                if ret != 0:
                    raise RuntimeError(f"Syntax Error in {op.path}:\n{err or out}")

        ret, out, err = run_command("npm run build")
        if ret != 0:
            raise RuntimeError(f"Production Build Failed:\n{err or out}")

        ret, out, err = run_command("node --test tests/*.test.js locked/*/tests/*.test.js app/tests/*.test.js")
        if ret != 0:
            raise RuntimeError(f"Test Suite Failed:\n{err or out}")

        meta["status"] = "applied"
        data["meta"] = meta
        proposal_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "action": "apply",
            "status": "success",
            "files_touched": proposal.files_touched
        })

        return {
            "success": True,
            "request_id": request_id,
            "status": "applied",
            "files_touched": proposal.files_touched
        }

    except Exception as e:
        for file_path, original_bytes in backups.items():
            path = ROOT / file_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original_bytes)
        for file_path in created_files:
            path = ROOT / file_path
            if path.exists():
                path.unlink()
                parent = path.parent
                while parent != ROOT:
                    if any(parent.iterdir()):
                        break
                    parent.rmdir()
                    parent = parent.parent

        meta["status"] = "rolled_back"
        data["meta"] = meta
        proposal_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "action": "apply",
            "status": "rolled_back",
            "error": str(e)
        })

        return {
            "success": False,
            "error": f"Application failed and was rolled back: {str(e)}",
            "status": "rolled_back"
        }

async def apply_proposal_endpoint(request: Request):
    request_id = request.path_params["request_id"]
    result = apply_proposal(request_id)
    return JSONResponse(result)


async def validate_proposal_endpoint(request: Request):
    request_id = request.path_params["request_id"]
    report = validate_proposal(request_id)
    return JSONResponse(report)

def apply_proposal(request_id: str) -> dict:
    proposal_file = PENDING_DIR / f"{request_id}.json"
    if not proposal_file.exists():
        return {"success": False, "error": f"Proposal {request_id} not found."}

    validation = validate_proposal(request_id)
    if not validation.get("valid"):
        return {
            "success": False,
            "error": "Cannot apply invalid or unverified proposal.",
            "validation": validation
        }

    data = json.loads(proposal_file.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    proposal_dict = data.get("proposal", {})
    proposal = ProposalOutput.model_validate(proposal_dict)

    backups = {}
    created_files = []

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
            if op.action in ("create", "modify") and op.path.endswith(".js"):
                ret, out, err = run_command(f"node --check {op.path}")
                if ret != 0:
                    raise RuntimeError(f"Syntax Error in {op.path}:\n{err or out}")

        ret, out, err = run_command("npm run build")
        if ret != 0:
            raise RuntimeError(f"Production Build Failed:\n{err or out}")

        ret, out, err = run_command("node --test tests/*.test.js locked/*/tests/*.test.js app/tests/*.test.js")
        if ret != 0:
            raise RuntimeError(f"Test Suite Failed:\n{err or out}")

        meta["status"] = "applied"
        data["meta"] = meta
        proposal_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "action": "apply",
            "status": "success",
            "files_touched": proposal.files_touched
        })

        return {
            "success": True,
            "request_id": request_id,
            "status": "applied",
            "files_touched": proposal.files_touched
        }

    except Exception as e:
        for file_path, original_bytes in backups.items():
            path = ROOT / file_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original_bytes)
        for file_path in created_files:
            path = ROOT / file_path
            if path.exists():
                path.unlink()
                parent = path.parent
                while parent != ROOT:
                    if any(parent.iterdir()):
                        break
                    parent.rmdir()
                    parent = parent.parent

        meta["status"] = "rolled_back"
        data["meta"] = meta
        proposal_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "action": "apply",
            "status": "rolled_back",
            "error": str(e)
        })

        return {
            "success": False,
            "error": f"Application failed and was rolled back: {str(e)}",
            "status": "rolled_back"
        }

async def apply_proposal_endpoint(request: Request):
    request_id = request.path_params["request_id"]
    result = apply_proposal(request_id)
    return JSONResponse(result)



def build_evolution_context(intent: str) -> str:
    try:
        contracts = load_all_contracts()
    except Exception:
        contracts = {}
    
    app_dir = ROOT / "app"
    app_files_summary = {}
    if app_dir.exists():
        for p in app_dir.glob("**/*"):
            if p.is_file():
                rel = str(p.relative_to(ROOT))
                try:
                    app_files_summary[rel] = p.read_text(encoding="utf-8")[:1000]
                except Exception:
                    pass

    context = f"""=== HOST APPLICATION CONTEXT ===
Application Name: Class Alarm
Architecture: Modular Evolvable Architecture (Locked Core vs Evolvable Periphery)
Composition Layer: app/ directory (composition roots and host wiring)

=== ACTIVE POLICIES ===
1. Policy 001: Any newly created file must be explicitly imported, mounted, or registered in an existing module or composition root. Orphaned files of any type are strictly forbidden.
2. Evolvable modules never import modules under locked/. They use declared host APIs.
3. Locked modules never import evolvable modules.

=== AVAILABLE COMPOSITION LAYER (app/) ===
{json.dumps(app_files_summary, indent=2)}

=== CANONICAL MODULE CONTRACTS ===
{json.dumps(contracts, indent=2)}

=== USER INTENT ===
{intent}
"""
    return context



async def generate_evolution_endpoint(request: Request):
    try:
        body = await request.json()
        plan_id = body.get("plan_id")
        if not plan_id:
            return JSONResponse({"error": "plan_id is required."}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"Invalid request body: {str(e)}"}, status_code=400)

    plan_file = PENDING_DIR / f"plan_{plan_id}.json"
    if not plan_file.exists():
        return JSONResponse({"error": "Plan not found."}, status_code=404)

    try:
        plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
        plan_dict = plan_data.get("plan", {})
        plan = EvolutionPlan.model_validate(plan_dict)
    except Exception as e:
        return JSONResponse({"error": f"Failed to load or parse plan: {str(e)}"}, status_code=400)

    client = get_gemini_client()
    if not client:
        return JSONResponse({"error": "Gemini API key is not configured (GEMINI_API_KEY or GOOGLE_API_KEY missing)."}, status_code=500)

    model_name = get_model_name()
    
    prompt = f"""=== EVOLUTION PLAN TO EXECUTE ===
Intent: {plan.intent}
Affected Modules: {plan.affected_modules}
Composition Changes: {plan.composition_changes}
Files to Modify: {plan.files_to_modify}
Files to Create: {plan.files_to_create}
Required Contracts: {plan.required_contracts}
Validation Checks: {plan.validation_checks}

Generate the exact file operations (create, modify, delete) required to fulfill this plan. You must strictly adhere to the files listed in files_to_modify and files_to_create."""

    system_instruction = """You are an expert Code Generator for Project Darwin.
Your task is to act ONLY as a Code Generator executing the provided EvolutionPlan.
You must generate precise file operations (create, modify, delete) with complete content for every file specified in the plan.
Adhere strictly to the requested JSON schema (EvolutionProposal). Do not touch any files outside the plan."""

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={
                "system_instruction": system_instruction,
                "response_mime_type": "application/json",
                "response_schema": EvolutionProposal,
                "temperature": 0.1,
            }
        )
        proposal_dict = json.loads(response.text)
        proposal = EvolutionProposal.model_validate(proposal_dict)

        # Unplanned Modification Guard (Python Validation)
        allowed_modify = set(plan.files_to_modify)
        allowed_create = set(plan.files_to_create)

        for op in proposal.operations:
            if op.action == "modify" and op.path not in allowed_modify:
                return JSONResponse({
                    "error": f"Generation Failed: Unplanned file modification detected for '{op.path}'."
                }, status_code=400)
            if op.action == "create" and op.path not in allowed_create:
                return JSONResponse({
                    "error": f"Generation Failed: Unplanned file creation detected for '{op.path}'."
                }, status_code=400)
            if op.action == "delete" and op.path not in allowed_modify:
                return JSONResponse({
                    "error": f"Generation Failed: Unplanned file deletion detected for '{op.path}'."
                }, status_code=400)

        # Persistence (Bridged to ProposalOutput for Step 4/5 validation and apply)
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        files_touched = [op.path for op in proposal.operations]
        proposal_record = {
            "meta": {
                "id": plan_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "request": plan.intent,
                "model": model_name,
                "path": "fast",
                "status": "pending_review",
                "plan": proposal.description,
                "files_touched": files_touched
            },
            "proposal": {
                "plan": proposal.description,
                "files_touched": files_touched,
                "operations": [op.model_dump() for op in proposal.operations],
                "contract_effects": {"new_contract_fields": [], "modified_contracts": []},
                "test_effects": {"new_tests": [], "modified_tests": []},
                "new_locked_imports": []
            }
        }
        proposal_file = PENDING_DIR / f"proposal_{plan_id}.json"
        proposal_file.write_text(json.dumps(proposal_record, indent=2), encoding="utf-8")

        request_file = PENDING_DIR / f"{plan_id}.json"
        request_file.write_text(json.dumps(proposal_record, indent=2), encoding="utf-8")

        return JSONResponse({
            "plan_id": plan_id,
            "summary": {
                "description": proposal.description,
                "operations_count": len(proposal.operations),
                "files_touched": [op.path for op in proposal.operations]
            }
        })
    except Exception as e:
        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "plan_id": plan_id,
            "action": "generate",
            "status": "failed",
            "error": str(e)
        })
        return JSONResponse({"error": f"Code generation failed: {str(e)}"}, status_code=500)


async def plan_evolution_endpoint(request: Request):
    try:
        body = await request.json()
        intent = body.get("text") or body.get("intent")
        if not intent:
            return JSONResponse({"error": "Evolution intent ('text' or 'intent') is required."}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"Invalid request body: {str(e)}"}, status_code=400)

    client = get_gemini_client()
    if not client:
        return JSONResponse({"error": "Gemini API key is not configured (GEMINI_API_KEY or GOOGLE_API_KEY missing)."}, status_code=500)

    model_name = get_model_name()
    context_str = build_evolution_context(intent)

    system_instruction = """You are an expert Evolution Planner for Project Darwin.
Your task is to analyze the user intent and active architecture context, then formulate a precise, structured EvolutionPlan.
Do NOT write code or generate file operations. Focus entirely on architectural planning, affected modules, composition changes (ensuring Policy 001 is satisfied so no components are orphaned), required contracts, files to create/modify, validation checks, confidence, and risk level.
Adhere strictly to the requested JSON schema (EvolutionPlan)."""

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=context_str,
            config={
                "system_instruction": system_instruction,
                "response_mime_type": "application/json",
                "response_schema": EvolutionPlan,
                "temperature": 0.1,
            }
        )
        plan_dict = json.loads(response.text)
        plan = EvolutionPlan.model_validate(plan_dict)

        if plan.files_to_create and not plan.files_to_modify:
            return JSONResponse({
                "error": "Violation of Policy 001: files_to_create is not empty, but files_to_modify is empty. Orphaned files are strictly forbidden; new files must be explicitly registered or imported in existing files."
            }, status_code=400)

        for path in plan.files_to_modify + plan.files_to_create:
            if path.startswith("locked/") or path.startswith("registry/"):
                return JSONResponse({
                    "error": "Plan Validation Failed: Cannot mutate protected core or registry boundaries."
                }, status_code=400)

        plan_id = str(uuid.uuid4())
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        plan_record = {
            "id": plan_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "intent": intent,
            "plan": plan.model_dump()
        }
        plan_file = PENDING_DIR / f"plan_{plan_id}.json"
        plan_file.write_text(json.dumps(plan_record, indent=2), encoding="utf-8")

        return JSONResponse({
            "id": plan_id,
            "plan": plan.model_dump()
        })
    except Exception as e:
        append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "intent": intent,
            "action": "plan",
            "status": "failed",
            "error": str(e)
        })
        return JSONResponse({"error": f"Evolution planning failed: {str(e)}"}, status_code=500)


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/proposals", list_proposals, methods=["GET"]),
        Route("/proposals/{request_id}", get_proposal, methods=["GET"]),
        Route("/evolve", evolve, methods=["POST"]),
        Route("/proposals/{request_id}/validate", validate_proposal_endpoint, methods=["POST"]),
        Route("/evolutions/plan", plan_evolution_endpoint, methods=["POST"]),
        Route("/evolutions/generate", generate_evolution_endpoint, methods=["POST"]),
        Route("/proposals/{request_id}/apply", apply_proposal_endpoint, methods=["POST"]),
    ]
)
