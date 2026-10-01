"""
Smoke test scaffolding for FleetGuard Pulse foundation.
Validates repository structure and control file consistency without requiring external dependencies.
"""

import os
import unittest
from pathlib import Path


class TestRepositoryFoundation(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2]

    def test_core_directories_exist(self):
        expected_dirs = [
            "services/api",
            "services/ingestion",
            "services/stream_processor",
            "services/simulator",
            "services/ml",
            "services/analytics",
            "frontend",
            "infra/docker",
            "infra/terraform",
            "tests/unit",
            "tests/integration",
            "tests/contract",
            "tests/acceptance",
            "tests/performance",
            "tests/security",
            "tests/chaos",
            "docs",
            "scripts",
            "data/seed",
            "data/raw",
            "data/generated",
        ]
        for dir_path in expected_dirs:
            full_path = self.root / dir_path
            self.assertTrue(
                full_path.is_dir(),
                f"Expected directory {dir_path} does not exist",
            )

    def test_control_documents_exist(self):
        expected_files = [
            "docs/HACKATHON_SPEC.md",
            "docs/ACCEPTANCE_CHECKLIST.md",
            "docs/ARCHITECTURE_LOCK.md",
            "docs/ARCHITECTURE_PROPOSAL.md",
            "docs/BUILD_STATE.md",
            "docker-compose.yml",
            ".env.example",
            "Makefile",
            "pyproject.toml",
            "README.md",
        ]
        for file_path in expected_files:
            full_path = self.root / file_path
            self.assertTrue(
                full_path.is_file(),
                f"Expected file {file_path} does not exist",
            )

    def test_architecture_lock_status(self):
        lock_file = self.root / "docs/ARCHITECTURE_LOCK.md"
        content = lock_file.read_text(encoding="utf-8")
        self.assertIn("STATUS: ARCHITECTURE LOCKED", content)


if __name__ == "__main__":
    unittest.main()
