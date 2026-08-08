import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from server.main import (
    FileOperation,
    ProposalOutput,
    app,
    build_system_prompt,
    is_fast_path,
    load_all_contracts,
    validate_file_paths,
)


class TestEvolutionServer(unittest.TestCase):
    def test_loads_canonical_contracts_from_module_registry(self):
        contracts = load_all_contracts()
        self.assertEqual(
            set(contracts),
            {
                "alarm-engine", "app-runtime", "core-data", "evolution-server",
                "governance", "risk-flag", "ui", "web-shell",
            },
        )
        for module_id, contract in contracts.items():
            self.assertEqual(contract["module"], module_id)

    def test_system_prompt_preserves_locked_import_boundary(self):
        prompt = build_system_prompt(load_all_contracts())
        self.assertIn("Here are the canonical module contracts:", prompt)
        self.assertIn("never a direct schema or database import", prompt)
        self.assertNotIn("Use locked/core-data/access.js", prompt)

    def test_health_endpoint(self):
        with TestClient(app) as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "ok")
            self.assertIn("model", data)
            self.assertIn("api_key_configured", data)

    def test_fast_path_classification(self):
        fast_proposal = ProposalOutput(
            plan="Change header color",
            files_touched=["evolvable/ui/styles.css"],
            operations=[{"action": "modify", "path": "evolvable/ui/styles.css", "content": "body {}"}],
        )
        self.assertTrue(is_fast_path(fast_proposal))

        jsx_proposal = ProposalOutput(
            plan="Modify UI code",
            files_touched=["evolvable/ui/App.jsx"],
            operations=[FileOperation(action="modify", path="evolvable/ui/App.jsx", content="export default function App() {}")],
        )
        self.assertFalse(is_fast_path(jsx_proposal))

        locked_proposal = ProposalOutput(
            plan="Modify locked storage",
            files_touched=["locked/core-data/access.js"],
            operations=[FileOperation(action="modify", path="locked/core-data/access.js", content="export function hack() {}")],
        )
        self.assertFalse(is_fast_path(locked_proposal))

    def test_validate_file_paths(self):
        invalid_proposal = ProposalOutput(
            plan="Path traversal attempt",
            files_touched=["../etc/passwd"],
            operations=[{"action": "modify", "path": "../etc/passwd"}],
        )
        with self.assertRaises(ValueError):
            validate_file_paths(invalid_proposal)

    def test_missing_api_key_logs_failure(self):
        with TestClient(app) as client:
            with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}):
                response = client.post("/evolve", json={"text": "Add dark mode"})
                self.assertEqual(response.status_code, 500)
                self.assertIn("error", response.json())

    @patch("server.main.get_gemini_client")
    def test_successful_css_proposal_generation(self, mock_get_client):
        with TestClient(app) as client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_response = MagicMock()
            mock_response.text = json.dumps({
                "plan": "Change the topbar color.",
                "files_touched": ["evolvable/ui/styles.css"],
                "operations": [{"action": "modify", "path": "evolvable/ui/styles.css", "content": "body { color: #222; }"}],
                "contract_effects": {"new_contract_fields": [], "modified_contracts": []},
                "test_effects": {"new_tests": [], "modified_tests": []},
                "new_locked_imports": [],
            })
            mock_client.models.generate_content.return_value = mock_response
            response = client.post("/evolve", json={"text": "Change the topbar color"})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["path"], "fast")
            self.assertEqual(data["status"], "pending_review")

    def _write_pending(self, request_id, proposal, meta=None):
        pending_file = Path("server/pending") / f"{request_id}.json"
        pending_file.write_text(json.dumps({"meta": meta or {"id": request_id}, "proposal": proposal}), encoding="utf-8")
        return pending_file

    def test_validation_rejects_locked_modification(self):
        proposal = {
            "plan": "Modify locked file",
            "files_touched": ["locked/core-data/access.js"],
            "operations": [{"action": "modify", "path": "locked/core-data/access.js", "content": "export function hack() {}"}],
        }
        pending_file = self._write_pending("test-locked-mod", proposal)
        try:
            with TestClient(app) as client:
                report = client.post("/proposals/test-locked-mod/validate").json()
            self.assertFalse(report["valid"])
            self.assertEqual(report["steps"]["locked_protection"], "fail")
        finally:
            pending_file.unlink(missing_ok=True)

    def test_validation_rejects_forbidden_locked_import(self):
        proposal = {
            "plan": "Import locked schema",
            "files_touched": ["evolvable/ui/App.jsx"],
            "operations": [{"action": "modify", "path": "evolvable/ui/App.jsx", "content": "import { schema } from '../../locked/core-data/schema.js';"}],
        }
        pending_file = self._write_pending("test-locked-import", proposal)
        try:
            with TestClient(app) as client:
                report = client.post("/proposals/test-locked-import/validate").json()
            self.assertFalse(report["valid"])
            self.assertEqual(report["steps"]["dependency_analysis"], "fail")
        finally:
            pending_file.unlink(missing_ok=True)

    def test_apply_invalid_proposal_fails_validation(self):
        proposal = {
            "plan": "Modify locked file",
            "files_touched": ["locked/core-data/access.js"],
            "operations": [{"action": "modify", "path": "locked/core-data/access.js", "content": "export function hack() {}"}],
        }
        pending_file = self._write_pending("test-apply-invalid", proposal, {"id": "test-apply-invalid", "human_approved": True})
        try:
            with TestClient(app) as client:
                data = client.post("/proposals/test-apply-invalid/apply").json()
            self.assertFalse(data["success"])
            self.assertIn("validation", data)
        finally:
            pending_file.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
