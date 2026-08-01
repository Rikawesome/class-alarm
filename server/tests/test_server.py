import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from server.main import (
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
                "alarm-engine",
                "app-runtime",
                "core-data",
                "evolution-server",
                "governance",
                "risk-flag",
                "ui",
                "web-shell",
            },
        )
        for module_id, contract in contracts.items():
            self.assertEqual(contract["module"], module_id)

    def test_system_prompt_preserves_locked_import_boundary(self):
        prompt = build_system_prompt(load_all_contracts())

        self.assertIn("loaded through registry/modules.json", prompt)
        self.assertIn(
            "Evolvable modules must not import any module under locked/",
            prompt,
        )
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
            operations=[
                {"action": "modify", "path": "evolvable/ui/styles.css", "content": "/* css */"}
            ],
            contract_effects={"new_contract_fields": [], "modified_contracts": []},
            test_effects={"new_tests": [], "modified_tests": []},
            new_locked_imports=[],
        )
        self.assertTrue(is_fast_path(fast_proposal))

        full_proposal_locked = ProposalOutput(
            plan="Modify locked storage",
            files_touched=["locked/core-data/access.js"],
            operations=[{"action": "modify", "path": "locked/core-data/access.js"}],
            contract_effects={"new_contract_fields": [], "modified_contracts": []},
            test_effects={"new_tests": [], "modified_tests": []},
            new_locked_imports=[],
        )
        self.assertFalse(is_fast_path(full_proposal_locked))

    def test_validate_file_paths(self):
        invalid_proposal = ProposalOutput(
            plan="Path traversal attempt",
            files_touched=["../etc/passwd"],
            operations=[{"action": "modify", "path": "../etc/passwd"}],
            contract_effects={"new_contract_fields": [], "modified_contracts": []},
            test_effects={"new_tests": [], "modified_tests": []},
            new_locked_imports=[],
        )
        with self.assertRaises(ValueError):
            validate_file_paths(invalid_proposal)

    def test_missing_api_key_logs_failure(self):
        with TestClient(app) as client:
            with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}):
                response = client.post("/evolve", json={"text": "Add dark mode"})
                self.assertEqual(response.status_code, 500)
                self.assertIn("error", response.json())

                log_res = client.get("/proposals")
                self.assertEqual(log_res.status_code, 200)
                logs = log_res.json()
                self.assertGreater(len(logs), 0)
                last_entry = logs[-1]
                self.assertEqual(last_entry["status"], "failed")

    @patch("server.main.get_gemini_client")
    def test_successful_proposal_generation(self, mock_get_client):
        with TestClient(app) as client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_response = MagicMock()
            mock_response.text = json.dumps({
                "plan": "Add a dark mode toggle button to the schedule topbar.",
                "files_touched": ["evolvable/ui/App.jsx"],
                "operations": [
                    {
                        "action": "modify",
                        "path": "evolvable/ui/App.jsx",
                        "content": "// Updated App.jsx content"
                    }
                ],
                "contract_effects": {"new_contract_fields": [], "modified_contracts": []},
                "test_effects": {"new_tests": [], "modified_tests": []},
                "new_locked_imports": []
            })
            mock_client.models.generate_content.return_value = mock_response

            response = client.post("/evolve", json={"text": "Add a dark mode toggle to the schedule topbar"})
            self.assertEqual(response.status_code, 200)
            data = response.json()

            self.assertEqual(data["path"], "fast")
            self.assertEqual(data["status"], "pending_review")
            self.assertEqual(data["files_touched"], ["evolvable/ui/App.jsx"])

            req_id = data["id"]
            prop_res = client.get(f"/proposals/{req_id}")
            self.assertEqual(prop_res.status_code, 200)
            prop_data = prop_res.json()
            self.assertEqual(prop_data["proposal"]["plan"], "Add a dark mode toggle button to the schedule topbar.")



    def test_validation_rejects_locked_modification(self):
        with TestClient(app) as client:
            req_id = "test-locked-mod"
            pending_file = Path("server/pending") / f"{req_id}.json"
            proposal_data = {
                "meta": {"id": req_id, "request": "Modify locked core"},
                "proposal": {
                    "plan": "Modify locked file",
                    "files_touched": ["locked/core-data/access.js"],
                    "operations": [
                        {"action": "modify", "path": "locked/core-data/access.js", "content": "export function hack() {}"}
                    ]
                }
            }
            pending_file.write_text(json.dumps(proposal_data), encoding="utf-8")
            try:
                res = client.post(f"/proposals/{req_id}/validate")
                self.assertEqual(res.status_code, 200)
                report = res.json()
                self.assertFalse(report["valid"])
                self.assertEqual(report["steps"]["locked_protection"], "fail")
            finally:
                if pending_file.exists():
                    pending_file.unlink()

    def test_validation_rejects_locked_import(self):
        with TestClient(app) as client:
            req_id = "test-locked-import"
            pending_file = Path("server/pending") / f"{req_id}.json"
            proposal_data = {
                "meta": {"id": req_id, "request": "Import locked core from UI"},
                "proposal": {
                    "plan": "Import locked file",
                    "files_touched": ["evolvable/ui/App.jsx"],
                    "operations": [
                        {"action": "modify", "path": "evolvable/ui/App.jsx", "content": "import { db } from '../../locked/core-data/access.js';"}
                    ]
                }
            }
            pending_file.write_text(json.dumps(proposal_data), encoding="utf-8")
            try:
                res = client.post(f"/proposals/{req_id}/validate")
                self.assertEqual(res.status_code, 200)
                report = res.json()
                self.assertFalse(report["valid"])
                self.assertEqual(report["steps"]["dependency_analysis"], "fail")
            finally:
                if pending_file.exists():
                    pending_file.unlink()



    def test_apply_invalid_proposal_fails(self):
        with TestClient(app) as client:
            req_id = "test-apply-invalid"
            pending_file = Path("server/pending") / f"{req_id}.json"
            proposal_data = {
                "meta": {"id": req_id, "request": "Modify locked core"},
                "proposal": {
                    "plan": "Modify locked file",
                    "files_touched": ["locked/core-data/access.js"],
                    "operations": [
                        {"action": "modify", "path": "locked/core-data/access.js", "content": "export function hack() {}"}
                    ]
                }
            }
            pending_file.write_text(json.dumps(proposal_data), encoding="utf-8")
            try:
                res = client.post(f"/proposals/{req_id}/apply")
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertFalse(data["success"])
                self.assertIn("validation", data)
            finally:
                if pending_file.exists():
                    pending_file.unlink()



    @patch("server.main.get_gemini_client")
    def test_evolution_planner_endpoint(self, mock_get_client):
        with TestClient(app) as client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_response = MagicMock()
            mock_response.text = json.dumps({
                "intent": "Add export button",
                "affected_modules": ["ui"],
                "composition_changes": ["Import ExportButton in App.jsx and render it"],
                "files_to_modify": ["evolvable/ui/App.jsx"],
                "files_to_create": ["evolvable/ui/ExportButton.jsx"],
                "required_contracts": ["ui"],
                "validation_checks": ["component_mounted", "build_required"],
                "confidence": 0.95,
                "risk_level": "low"
            })
            mock_client.models.generate_content.return_value = mock_response

            response = client.post("/evolutions/plan", json={"intent": "Add export button"})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn("id", data)
            self.assertIn("plan", data)
            self.assertEqual(data["plan"]["intent"], "Add export button")
            self.assertEqual(data["plan"]["affected_modules"], ["ui"])
            self.assertIn("component_mounted", data["plan"]["validation_checks"])
            self.assertEqual(data["plan"]["confidence"], 0.95)



    @patch("server.main.get_gemini_client")
    def test_evolution_planner_rejects_orphans(self, mock_get_client):
        with TestClient(app) as client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_response = MagicMock()
            mock_response.text = json.dumps({
                "intent": "Create orphaned file",
                "affected_modules": ["ui"],
                "composition_changes": [],
                "files_to_modify": [],
                "files_to_create": ["evolvable/ui/Orphan.jsx"],
                "required_contracts": ["ui"],
                "validation_checks": ["build_required"],
                "confidence": 0.5,
                "risk_level": "medium"
            })
            mock_client.models.generate_content.return_value = mock_response

            response = client.post("/evolutions/plan", json={"intent": "Create orphaned file"})
            self.assertEqual(response.status_code, 400)
            self.assertIn("Violation of Policy 001", response.json()["error"])



    @patch("server.main.get_gemini_client")
    def test_evolution_planner_rejects_protected_core(self, mock_get_client):
        with TestClient(app) as client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_response = MagicMock()
            mock_response.text = json.dumps({
                "intent": "Mutate locked core",
                "affected_modules": ["core-data"],
                "composition_changes": ["Modify db.js"],
                "files_to_modify": ["locked/core-data/db.js"],
                "files_to_create": [],
                "required_contracts": ["core-data"],
                "validation_checks": ["build_required"],
                "confidence": 0.9,
                "risk_level": "high"
            })
            mock_client.models.generate_content.return_value = mock_response

            response = client.post("/evolutions/plan", json={"intent": "Mutate locked core"})
            self.assertEqual(response.status_code, 400)
            self.assertIn("Plan Validation Failed", response.json()["error"])

    @patch("server.main.get_gemini_client")
    def test_evolution_planner_saves_pending_plan(self, mock_get_client):
        with TestClient(app) as client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_response = MagicMock()
            mock_response.text = json.dumps({
                "intent": "Add feature",
                "affected_modules": ["ui"],
                "composition_changes": ["Update App.jsx"],
                "files_to_modify": ["evolvable/ui/App.jsx"],
                "files_to_create": ["evolvable/ui/NewWidget.jsx"],
                "required_contracts": ["ui"],
                "validation_checks": ["build_required"],
                "confidence": 0.95,
                "risk_level": "low"
            })
            mock_client.models.generate_content.return_value = mock_response

            response = client.post("/evolutions/plan", json={"intent": "Add feature"})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn("id", data)
            self.assertIn("plan", data)

            plan_id = data["id"]
            pending_file = Path("server/pending") / f"plan_{plan_id}.json"
            try:
                self.assertTrue(pending_file.exists())
                saved_data = json.loads(pending_file.read_text(encoding="utf-8"))
                self.assertEqual(saved_data["id"], plan_id)
                self.assertEqual(saved_data["intent"], "Add feature")
            finally:
                if pending_file.exists():
                    pending_file.unlink()



    def test_generate_evolution_plan_not_found(self):
        with TestClient(app) as client:
            response = client.post("/evolutions/generate", json={"plan_id": "nonexistent-id"})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["error"], "Plan not found.")

    @patch("server.main.get_gemini_client")
    def test_generate_evolution_unplanned_guard(self, mock_get_client):
        with TestClient(app) as client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            plan_id = "test-plan-guard"
            plan_file = Path("server/pending") / f"plan_{plan_id}.json"
            plan_record = {
                "id": plan_id,
                "plan": {
                    "intent": "Add feature",
                    "affected_modules": ["ui"],
                    "composition_changes": ["Update App.jsx"],
                    "files_to_modify": ["evolvable/ui/App.jsx"],
                    "files_to_create": [],
                    "required_contracts": ["ui"],
                    "validation_checks": ["build_required"],
                    "confidence": 0.9,
                    "risk_level": "low"
                }
            }
            plan_file.parent.mkdir(parents=True, exist_ok=True)
            plan_file.write_text(json.dumps(plan_record), encoding="utf-8")

            mock_response = MagicMock()
            mock_response.text = json.dumps({
                "plan_id": plan_id,
                "description": "Unauthorized change",
                "operations": [
                    {"action": "modify", "path": "locked/core-data/access.js", "content": "hack"}
                ]
            })
            mock_client.models.generate_content.return_value = mock_response

            try:
                response = client.post("/evolutions/generate", json={"plan_id": plan_id})
                self.assertEqual(response.status_code, 400)
                self.assertIn("Unplanned file modification detected", response.json()["error"])
            finally:
                if plan_file.exists():
                    plan_file.unlink()


if __name__ == "__main__":
    unittest.main()
