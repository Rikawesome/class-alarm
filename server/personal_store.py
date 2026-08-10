"""Per-user personal evolution artifact storage.

This store is deliberately separate from repository proposals and the
application's course/personal-feature databases. It provides versioned,
branch-scoped artifacts for the future personal evolution lane; activation is
not exposed to the current global UI yet.
"""

import json
import hashlib
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "personal-evolution.db"
MAX_ARTIFACT_BYTES = 64 * 1024
SUPPORTED_ARTIFACT_KINDS = {"ui-preferences", "ui-widget"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_personal_artifact(manifest: dict, content: dict, content_hash: str) -> dict:
    """Validate a safe, declarative personal artifact before persistence."""
    if not isinstance(manifest, dict) or manifest.get("kind") not in SUPPORTED_ARTIFACT_KINDS:
        raise ValueError("Personal artifact manifest has an unsupported kind.")
    if manifest.get("version") != 1:
        raise ValueError("Personal artifact manifest version must be 1.")
    if not isinstance(content, dict):
        raise ValueError("Personal artifact content must be a JSON object.")
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_ARTIFACT_BYTES:
        raise ValueError("Personal artifact exceeds the 64 KiB size limit.")
    expected_hash = hashlib.sha256(encoded).hexdigest()
    if content_hash != expected_hash:
        raise ValueError("Personal artifact content hash does not match content.")
    return {"valid": True, "kind": manifest["kind"], "version": 1, "bytes": len(encoded), "content_hash": expected_hash}


class PersonalArtifactStore:
    def __init__(self, database_path: Optional[str] = None):
        self.database_path = database_path or os.getenv(
            "DARWIN_PERSONAL_ARTIFACT_DB_PATH", str(DEFAULT_PATH)
        )
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.database_path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS personal_branches (
              branch_id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('active', 'archived')),
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_personal_branches_user
              ON personal_branches(user_id, updated_at);
            CREATE TABLE IF NOT EXISTS personal_artifacts (
              artifact_id TEXT PRIMARY KEY,
              branch_id TEXT NOT NULL REFERENCES personal_branches(branch_id),
              version INTEGER NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('draft', 'validated', 'approved', 'active', 'rolled_back')),
              manifest_json TEXT NOT NULL,
              content_json TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              parent_artifact_id TEXT,
              validation_json TEXT,
              created_at TEXT NOT NULL,
              activated_at TEXT,
              UNIQUE(branch_id, version)
            );
            CREATE INDEX IF NOT EXISTS idx_personal_artifacts_branch
              ON personal_artifacts(branch_id, version);
            """
        )
        self.db.commit()

    def close(self):
        self.db.close()

    def create_branch(self, user_id: str) -> dict:
        if not user_id or len(user_id) > 128:
            raise ValueError("user_id must be a non-empty identifier.")
        now = _now()
        branch = {"branch_id": str(uuid.uuid4()), "user_id": user_id, "status": "active", "created_at": now, "updated_at": now}
        self.db.execute(
            "INSERT INTO personal_branches(branch_id,user_id,status,created_at,updated_at) VALUES(?,?,?,?,?)",
            tuple(branch.values()),
        )
        self.db.commit()
        return branch

    def get_branch_for_user(self, branch_id: str, user_id: str) -> Optional[dict]:
        row = self.db.execute(
            "SELECT * FROM personal_branches WHERE branch_id = ? AND user_id = ? AND status = 'active'",
            (branch_id, user_id),
        ).fetchone()
        return dict(row) if row else None

    def get_or_create_branch(self, user_id: str) -> dict:
        row = self.db.execute(
            "SELECT * FROM personal_branches WHERE user_id = ? AND status = 'active' ORDER BY updated_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return dict(row) if row else self.create_branch(user_id)

    def create_artifact(self, branch_id: str, manifest: dict, content: dict, content_hash: str, validation: Optional[dict] = None) -> dict:
        validation_result = validate_personal_artifact(manifest, content, content_hash)
        branch = self.db.execute("SELECT 1 FROM personal_branches WHERE branch_id = ? AND status = 'active'", (branch_id,)).fetchone()
        if not branch:
            raise ValueError("Active personal branch not found.")
        previous = self.db.execute("SELECT MAX(version) AS version FROM personal_artifacts WHERE branch_id = ?", (branch_id,)).fetchone()
        version = int(previous["version"] or 0) + 1
        artifact = {
            "artifact_id": str(uuid.uuid4()), "branch_id": branch_id, "version": version,
            "status": "draft", "manifest_json": json.dumps(manifest, sort_keys=True),
            "content_json": json.dumps(content, sort_keys=True), "content_hash": content_hash,
            "parent_artifact_id": None, "validation_json": json.dumps(validation or validation_result),
            "created_at": _now(), "activated_at": None,
        }
        self.db.execute(
            "INSERT INTO personal_artifacts(artifact_id,branch_id,version,status,manifest_json,content_json,content_hash,parent_artifact_id,validation_json,created_at,activated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            tuple(artifact.values()),
        )
        self.db.commit()
        return artifact

    def list_artifacts(self, branch_id: str) -> list[dict]:
        rows = self.db.execute("SELECT * FROM personal_artifacts WHERE branch_id = ? ORDER BY version DESC", (branch_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_artifact_for_user(self, artifact_id: str, user_id: str) -> Optional[dict]:
        row = self.db.execute(
            """SELECT a.* FROM personal_artifacts a
               JOIN personal_branches b ON b.branch_id = a.branch_id
               WHERE a.artifact_id = ? AND b.user_id = ? AND b.status = 'active'""",
            (artifact_id, user_id),
        ).fetchone()
        return dict(row) if row else None

    def approve(self, artifact_id: str, user_id: str) -> dict:
        artifact = self.get_artifact_for_user(artifact_id, user_id)
        if not artifact:
            raise ValueError("Personal artifact not found for this user.")
        if artifact["status"] not in {"draft", "validated"}:
            raise ValueError("Only draft or validated personal artifacts can be approved.")
        self.db.execute("UPDATE personal_artifacts SET status = 'approved' WHERE artifact_id = ?", (artifact_id,))
        self.db.commit()
        return self.get_artifact_for_user(artifact_id, user_id)

    def activate(self, artifact_id: str) -> dict:
        artifact = self.db.execute("SELECT * FROM personal_artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        if not artifact:
            raise ValueError("Personal artifact not found.")
        if artifact["status"] != "approved":
            raise ValueError("Personal artifact must be approved before activation.")
        self.db.execute("UPDATE personal_artifacts SET status = 'rolled_back' WHERE branch_id = ? AND status = 'active'", (artifact["branch_id"],))
        self.db.execute("UPDATE personal_artifacts SET status = 'active', activated_at = ? WHERE artifact_id = ?", (_now(), artifact_id))
        self.db.commit()
        return dict(self.db.execute("SELECT * FROM personal_artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone())

    def activate_for_user(self, artifact_id: str, user_id: str) -> dict:
        artifact = self.get_artifact_for_user(artifact_id, user_id)
        if not artifact:
            raise ValueError("Personal artifact not found for this user.")
        return self.activate(artifact_id)

    def rollback(self, artifact_id: str, user_id: str) -> dict:
        current = self.get_artifact_for_user(artifact_id, user_id)
        if not current or current["status"] != "active":
            raise ValueError("Only the active personal artifact can be rolled back.")
        previous = self.db.execute(
            "SELECT * FROM personal_artifacts WHERE branch_id = ? AND status = 'rolled_back' ORDER BY version DESC LIMIT 1",
            (current["branch_id"],),
        ).fetchone()
        if not previous:
            raise ValueError("No previous personal artifact is available for rollback.")
        self.db.execute("UPDATE personal_artifacts SET status = 'rolled_back' WHERE artifact_id = ?", (artifact_id,))
        self.db.execute("UPDATE personal_artifacts SET status = 'active', activated_at = ? WHERE artifact_id = ?", (_now(), previous["artifact_id"]))
        self.db.commit()
        return dict(self.db.execute("SELECT * FROM personal_artifacts WHERE artifact_id = ?", (previous["artifact_id"],)).fetchone())
