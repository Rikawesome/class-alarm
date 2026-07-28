"""
Evolution backend — MVP version.

One Claude call plays "central agent + module agent" for now. Triage is a
static rule, not a judgment call, checked against the contract files. No
resolver, no misuse-check pipeline yet — deliberately deferred.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
client = Anthropic()  # reads ANTHROPIC_API_KEY from env

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = ROOT / "registry" / "contracts"
LOG_PATH = ROOT / "logs" / "evolution-log.json"
PENDING_DIR = ROOT / "server" / "pending"
PENDING_DIR.mkdir(exist_ok=True)


class EvolutionRequest(BaseModel):
    text: str


def load_all_contracts() -> dict:
    contracts = {}
    for f in REGISTRY_DIR.glob("*.json"):
        contracts[f.stem] = json.loads(f.read_text())
    return contracts


def append_log(entry: dict):
    log = json.loads(LOG_PATH.read_text()) if LOG_PATH.exists() else []
    log.append(entry)
    LOG_PATH.write_text(json.dumps(log, indent=2))


def is_fast_path(diff_summary: dict) -> bool:
    """
    Static rule, not discretion:
    fast path only if the diff touches evolvable/ui/ files only,
    adds no new contract fields, and adds no new locked/core-data imports.
    """
    touches_only_ui = all(
        p.startswith("evolvable/ui/") for p in diff_summary.get("files_touched", [])
    )
    no_new_contract_fields = not diff_summary.get("new_contract_fields")
    no_new_locked_imports = not diff_summary.get("new_locked_imports")
    return touches_only_ui and no_new_contract_fields and no_new_locked_imports


@app.post("/evolve")
def evolve(req: EvolutionRequest):
    contracts = load_all_contracts()

    system_prompt = f"""You are a module agent for a small evolvable app.
Here are the current module contracts (source of truth for what each module
owns, exposes, and depends on):

{json.dumps(contracts, indent=2)}

Given a user's plain-language request, propose a code change that stays
within an evolvable module's declared surface. Never touch a locked module.
Respond with JSON: {{
  "plan": "...",
  "files_touched": ["evolvable/..."],
  "new_contract_fields": [...],
  "new_locked_imports": [...],
  "diff": "..."
}}"""

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": req.text}],
    )

    result = json.loads(response.content[0].text)
    request_id = str(uuid.uuid4())
    fast = is_fast_path(result)

    entry = {
        "id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request": req.text,
        "plan": result.get("plan"),
        "files_touched": result.get("files_touched"),
        "path": "fast" if fast else "full",
        "status": "applied" if fast else "pending_review",
    }
    append_log(entry)

    if fast:
        # MVP: write the diff straight to the file; a real version would
        # apply it via a proper patch mechanism.
        pass  # apply_diff(result["diff"])  -- left for you to wire up
    else:
        (PENDING_DIR / f"{request_id}.json").write_text(json.dumps(result, indent=2))

    return {"path": entry["path"], "id": request_id, "plan": result.get("plan")}
