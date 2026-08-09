import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from server.main import (
    FileOperation,
    GenerationProposalOutput,
    ProposalOutput,
    RegistrationRequest,
    _source_files,
    app,
    build_system_prompt,
    install_approved_registration,
    is_fast_path,
    load_all_contracts,
    parse_generated_proposal,
    validate_registration_request,
    validate_file_paths,
)


class TestEvolutionServer(unittest.TestCase):
    def _registration_request(self):
        module_id = "sample-feature"
        module_path = f"evolvable/features/{module_id}"
        storage_schema = {
            "version": 1,
            "record": {
                "type": "object",
                "required": [],
                "additionalProperties": True,
                "properties": {},
            },
        }
        runtime = {
            "entry": "index.js",
            "factory_export": "createExtension",
        }
        return RegistrationRequest(
            module_id=module_id,
            path=module_path,
            contract=f"{module_path}/module.json",
            extension={
                "contract_version": "1.0",
                "enabled": True,
                "runtime": runtime,
                "authorized_capabilities": ["personal-storage"],
            },
            manifest={
                "module": module_id,
                "role": "feature",
                "evolution_policy": "evolvable",
                "storage_namespace": module_id,
                "storage_schema": storage_schema,
                "owns": [f"{module_path}/**"],
                "extension": {
                    "contract_version": "1.0",
                    "runtime": runtime,
                    "requested_capabilities": ["personal-storage"],
                },
                "depends_on": [],
                "file_policies": {
                    "module.json": "human-review",
                    "index.js": "evolvable",
                },
            },
        )

    def test_loads_canonical_contracts_from_module_registry(self):
        contracts = load_all_contracts()
        self.assertEqual(
            set(contracts),
            {
                "alarm-engine", "app-runtime", "core-data", "evolution-server",
                "personal-data",
                "governance", "risk-flag", "ui", "web-shell", "weekly-goals",
            },
        )
        for module_id, contract in contracts.items():
            self.assertEqual(contract["module"], module_id)

    def test_gemini_generation_schema_avoids_additional_properties(self):
        schema_text = json.dumps(GenerationProposalOutput.model_json_schema())
        self.assertNotIn("additionalProperties", schema_text)

    def test_generated_registration_manifest_json_is_parsed_strictly(self):
        registration = self._registration_request()
        manifest_content = json.dumps(registration.manifest)
        generated = {
            "plan": "Register a feature",
            "files_touched": [
                "evolvable/features/sample-feature/index.js",
                "evolvable/features/sample-feature/module.json",
            ],
            "operations": [
                {
                    "action": "create",
                    "path": "evolvable/features/sample-feature/index.js",
                    "content": "export function createExtension() {}",
                },
                {
                    "action": "create",
                    "path": "evolvable/features/sample-feature/module.json",
                    "content": manifest_content,
                },
            ],
            "registration_request": {
                "module_id": registration.module_id,
                "path": "evolvable/features/sample-feature/",
                "contract": registration.contract,
                "extension": {
                    "contract_version": "1.0",
                    "enabled": True,
                    "runtime": {
                        "entry": "evolvable/features/sample-feature/index.js",
                        "factory_export": "createSampleFeature",
                    },
                    "authorized_capabilities": [],
                },
                "authorized_capabilities": ["personal-storage"],
                "manifest_json": manifest_content,
            },
        }

        proposal = parse_generated_proposal(generated)
        self.assertEqual(
            proposal.registration_request.manifest,
            registration.manifest,
        )
        self.assertEqual(
            proposal.registration_request.path,
            "evolvable/features/sample-feature",
        )
        self.assertEqual(
            proposal.registration_request.contract,
            "evolvable/features/sample-feature/module.json",
        )
        self.assertEqual(
            proposal.registration_request.extension.runtime.entry,
            "index.js",
        )
        self.assertEqual(
            proposal.registration_request.extension.runtime.factory_export,
            "createExtension",
        )
        self.assertEqual(
            proposal.registration_request.extension.authorized_capabilities,
            ["personal-storage"],
        )
        self.assertNotIn(
            "evolvable/features/sample-feature/module.json",
            proposal.files_touched,
        )
        self.assertEqual(len(proposal.operations), 1)
        candidate, already_registered = validate_registration_request(
            proposal.registration_request,
            {},
        )
        self.assertFalse(already_registered)
        self.assertEqual(candidate["path"], "evolvable/features/sample-feature")

        generated["registration_request"]["manifest_json"] = "{"
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            parse_generated_proposal(generated)

    def test_generated_registration_normalizes_null_manifest_extension(self):
        registration = self._registration_request()
        manifest = dict(registration.manifest)
        manifest["extension"] = None
        generated = {
            "plan": "Register a feature",
            "files_touched": ["evolvable/features/sample-feature/index.js"],
            "operations": [{
                "action": "create",
                "path": "evolvable/features/sample-feature/index.js",
                "content": "export function createExtension() {}",
            }],
            "registration_request": {
                "module_id": registration.module_id,
                "authorized_capabilities": ["personal-storage"],
                "manifest_json": json.dumps(manifest),
            },
        }

        proposal = parse_generated_proposal(generated)
        candidate, already_registered = validate_registration_request(
            proposal.registration_request,
            {},
        )
        self.assertFalse(already_registered)
        self.assertEqual(
            candidate["extension"]["authorized_capabilities"],
            ["personal-storage"],
        )

    def test_generated_duplicate_manifest_must_match_manifest_json(self):
        registration = self._registration_request()
        generated = {
            "plan": "Register a feature",
            "files_touched": [
                "evolvable/features/sample-feature/index.js",
                "evolvable/features/sample-feature/module.json",
            ],
            "operations": [
                {
                    "action": "create",
                    "path": "evolvable/features/sample-feature/index.js",
                    "content": "export function createExtension() {}",
                },
                {
                    "action": "create",
                    "path": "evolvable/features/sample-feature/module.json",
                    "content": "{}",
                },
            ],
            "registration_request": {
                "module_id": registration.module_id,
                "authorized_capabilities": ["personal-storage"],
                "manifest_json": json.dumps(registration.manifest),
            },
        }

        with self.assertRaisesRegex(ValueError, "differs from manifest_json"):
            parse_generated_proposal(generated)

    def test_system_prompt_preserves_locked_import_boundary(self):
        prompt = build_system_prompt(load_all_contracts())
        self.assertIn("Here are the canonical module contracts:", prompt)
        self.assertIn("capabilities: { personalStorage }", prompt)
        self.assertIn("execute(action, input)", prompt)
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

        registration_proposal = ProposalOutput(
            plan="Register a new feature",
            files_touched=["evolvable/features/sample-feature/index.js"],
            operations=[{
                "action": "create",
                "path": "evolvable/features/sample-feature/index.js",
                "content": "export function createExtension() {}",
            }],
            registration_request=self._registration_request(),
        )
        self.assertFalse(is_fast_path(registration_proposal))

    def test_validate_file_paths(self):
        invalid_proposal = ProposalOutput(
            plan="Path traversal attempt",
            files_touched=["../etc/passwd"],
            operations=[{"action": "modify", "path": "../etc/passwd"}],
        )
        with self.assertRaises(ValueError):
            validate_file_paths(invalid_proposal)

    def test_validation_workspace_includes_contracts_but_excludes_runtime_caches(self):
        source_files = _source_files()
        self.assertIn("server/module.json", source_files)
        self.assertFalse(any(path.startswith("server/pending/") for path in source_files))
        self.assertFalse(any("venv/" in path for path in source_files))
        self.assertFalse(any("__pycache__/" in path for path in source_files))

    def test_registration_request_validates_registry_authority(self):
        registration = self._registration_request()
        candidate, already_registered = validate_registration_request(
            registration,
            {},
        )

        self.assertFalse(already_registered)
        self.assertEqual(candidate["extension"]["enabled"], True)
        self.assertEqual(
            candidate["extension"]["authorized_capabilities"],
            ["personal-storage"],
        )
        self.assertEqual(candidate["storage_namespace"], "sample-feature")

        registration.manifest["extension"]["requested_capabilities"] = []
        with self.assertRaisesRegex(ValueError, "match exactly"):
            validate_registration_request(registration, {})

    def test_trusted_registration_writes_registry_and_manifest_together(self):
        registration = self._registration_request()
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            registry_path = temporary_root / "registry" / "modules.json"
            registry_path.parent.mkdir(parents=True)
            registry_path.write_text(
                json.dumps({
                    "schema_version": "1.0.0",
                    "modules": {},
                    "artifacts": {},
                }),
                encoding="utf-8",
            )

            with (
                patch("server.main.ROOT", temporary_root),
                patch("server.main.REGISTRY_PATH", registry_path),
            ):
                self.assertTrue(install_approved_registration(registration))
                self.assertFalse(install_approved_registration(registration))

            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            manifest_path = temporary_root / registration.contract
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                registry["modules"]["sample-feature"]["extension"],
                registration.extension.model_dump(),
            )
            self.assertEqual(manifest, registration.manifest)

    def test_registration_validation_requires_the_declared_runtime_entry(self):
        registration = self._registration_request()
        proposal = {
            "plan": "Register without implementation",
            "files_touched": [],
            "operations": [],
            "registration_request": registration.model_dump(),
        }
        pending_file = self._write_pending("test-registration-entry", proposal)
        try:
            with TestClient(app) as client:
                report = client.post("/proposals/test-registration-entry/validate").json()
            self.assertFalse(report["valid"])
            self.assertEqual(report["steps"]["registration"], "fail")
            self.assertIn("runtime entry", report["errors"][0])
        finally:
            pending_file.unlink(missing_ok=True)

    def test_registration_validation_rejects_unrendered_ui_integration(self):
        registration = self._registration_request()
        proposal = {
            "plan": "Register a feature and add its UI",
            "files_touched": [
                "evolvable/features/sample-feature/index.js",
                "evolvable/ui/App.jsx",
            ],
            "operations": [
                {
                    "action": "create",
                    "path": "evolvable/features/sample-feature/index.js",
                    "content": "export function createExtension() { return { getState() { return {}; }, execute() { return null; } }; }",
                },
                {
                    "action": "modify",
                    "path": "evolvable/ui/App.jsx",
                    "content": "export default function App() { return <div>Schedule</div>; }",
                },
            ],
            "ui_integration": {
                "entry_file": "evolvable/ui/App.jsx",
                "feature_id": "sample-feature",
                "rendered_symbol": "SampleFeature",
            },
            "registration_request": registration.model_dump(),
        }
        pending_file = self._write_pending("test-ui-integration", proposal)
        try:
            with TestClient(app) as client:
                report = client.post("/proposals/test-ui-integration/validate").json()
            self.assertFalse(report["valid"])
            self.assertEqual(report["steps"]["ui_integration"], "fail")
            self.assertIn("does not render", report["errors"][0])
        finally:
            pending_file.unlink(missing_ok=True)

    @patch("server.main.append_log")
    @patch("server.main.install_approved_registration")
    @patch("server.main.validate_proposal")
    def test_human_approval_invokes_trusted_registration(
        self,
        mock_validate_proposal,
        mock_install_registration,
        mock_append_log,
    ):
        registration = self._registration_request()
        proposal = {
            "plan": "Register a feature",
            "files_touched": ["evolvable/features/sample-feature/index.js"],
            "operations": [{
                "action": "create",
                "path": "evolvable/features/sample-feature/index.js",
                "content": "export function createExtension() {}",
            }],
            "registration_request": registration.model_dump(),
        }
        pending_file = self._write_pending(
            "test-registration-approval",
            proposal,
            {"id": "test-registration-approval", "human_approved": False},
        )
        mock_validate_proposal.return_value = {"valid": True}
        mock_install_registration.return_value = True
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/proposals/test-registration-approval/approve"
                )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["registration_created"])
            mock_install_registration.assert_called_once()
            mock_append_log.assert_called_once()
        finally:
            pending_file.unlink(missing_ok=True)

    def test_missing_api_key_logs_failure(self):
        with TestClient(app) as client:
            with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}):
                response = client.post("/evolve", json={"text": "Add dark mode"})
                self.assertEqual(response.status_code, 500)
                self.assertIn("error", response.json())

    def test_validation_rejects_empty_noop_proposal(self):
        proposal = {
            "plan": "Protected change is not permitted",
            "files_touched": [],
            "operations": [],
        }
        pending_file = self._write_pending("test-empty-noop", proposal)
        try:
            with TestClient(app) as client:
                report = client.post("/proposals/test-empty-noop/validate").json()
            self.assertFalse(report["valid"])
            self.assertEqual(report["steps"]["proposal_integrity"], "fail")
            self.assertIn("no file operations", report["errors"][0])
        finally:
            pending_file.unlink(missing_ok=True)

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

    def test_validation_rejects_protected_extension_loader_import(self):
        proposal = {
            "plan": "Import the protected extension loader",
            "files_touched": ["evolvable/ui/loader.js"],
            "operations": [{
                "action": "create",
                "path": "evolvable/ui/loader.js",
                "content": "import { loadApprovedExtensions } from '../../app/extensions.js';",
            }],
        }
        pending_file = self._write_pending("test-protected-loader-import", proposal)
        try:
            with TestClient(app) as client:
                report = client.post(
                    "/proposals/test-protected-loader-import/validate"
                ).json()
            self.assertFalse(report["valid"])
            self.assertEqual(report["steps"]["dependency_analysis"], "fail")
            self.assertIn("protected host path", report["errors"][0])
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
