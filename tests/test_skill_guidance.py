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

    def test_skill_matches_user_language_for_report_prose(self) -> None:
        skill_text = read(SKILL_MD)
        playbook_text = read(PLAYBOOK)

        self.assertIn("Response Language", skill_text)
        self.assertIn("Match the user's language", skill_text)
        self.assertIn("For Chinese requests", skill_text)
        self.assertIn("下一步：我可以继续进入完整的爆炸半径 bug review", skill_text)
        self.assertIn("结论：", skill_text)
        self.assertIn("用户可见表现：", skill_text)

        self.assertIn("For Chinese reports", playbook_text)
        self.assertIn("在用户视角，这些 bug 的表现形式是怎样的？", playbook_text)
        self.assertIn("验证思路：", playbook_text)

    def test_skill_groups_findings_before_user_impact_summary(self) -> None:
        skill_text = read(SKILL_MD)
        playbook_text = read(PLAYBOOK)

        self.assertIn("Report Ordering", skill_text)
        self.assertIn("List all `[P1/P2/P3]` findings first", skill_text)
        self.assertIn("Do not interleave user-visible behavior inside each finding", skill_text)
        self.assertIn("在用户视角，这些 bug 的表现形式是怎样的？", skill_text)

        self.assertIn("User Impact Summary", playbook_text)
        self.assertIn("After listing all findings", playbook_text)
        self.assertIn("在用户视角，这些 bug 的表现形式是怎样的？", playbook_text)

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

        self.assertIn("user-visible behavior", text)
        self.assertIn("Verification idea", text)
