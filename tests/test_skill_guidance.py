from __future__ import annotations

import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "detecting-circular-dependencies"
SKILL_MD = SKILL_DIR / "SKILL.md"
PLAYBOOK = SKILL_DIR / "references" / "bug-review-playbook.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class SkillGuidanceTests(unittest.TestCase):
    def test_skill_triggers_for_blast_radius_bug_review(self) -> None:
        text = read(SKILL_MD)

        self.assertIn("blast-radius", text)
        self.assertIn("bug risks", text)
        self.assertIn("user-visible bugs", text)

    def test_skill_defines_follow_up_bug_review_workflow(self) -> None:
        text = read(SKILL_MD)

        self.assertIn("Follow-up Bug Review Workflow", text)
        self.assertIn("Use circular dependency findings as entry points", text)
        self.assertIn("bug-review-playbook.md", text)
        self.assertIn("confirmed bugs from architectural risks", text)

    def test_skill_always_guides_detection_requests_toward_full_flow(self) -> None:
        text = read(SKILL_MD)

        self.assertIn("Continuation Guidance", text)
        self.assertIn("always offer the full follow-up flow", text)
        self.assertIn("even when no cycles are found", text)
        self.assertIn("non-cycle blast-radius scan", text)

    def test_bug_review_playbook_covers_blast_radius_patterns(self) -> None:
        text = read(PLAYBOOK)

        for pattern in [
            "Contract Drift",
            "Hidden Coupling",
            "Shared State Pollution",
            "Boundary Leak",
            "Temporal Coupling",
            "Semantic Duplication",
        ]:
            self.assertIn(pattern, text)

        self.assertIn("User-visible behavior", text)
        self.assertIn("Verification idea", text)
