"""Целостность независимого корпуса T-02; не оценка качества анализатора."""

import json
import unittest
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[1] / "tests/fixtures/qa/query-corpus.json"


class QaCorpusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = json.loads(CORPUS.read_text())
        cls.cases = cls.corpus["cases"]

    def test_stable_ids_and_review_provenance(self) -> None:
        self.assertEqual(self.corpus["corpus_version"], "0.3.0")
        self.assertEqual(self.corpus["expert_review_status"], "approved_base_pending_A13")
        self.assertEqual(len({case["case_id"] for case in self.cases}), len(self.cases))
        for case in self.cases:
            with self.subTest(case=case["case_id"]):
                self.assertRegex(case["case_id"], r"^T02-\d{3}$")
                self.assertTrue(case["input"].strip())
                self.assertEqual(case["annotation"]["status"], "expert_approved_base")
                self.assertTrue(case["annotation"]["rationale"])
                self.assertTrue(Path(case["annotation"]["requirement"]).is_file())

    def test_scope_and_intent_coverage(self) -> None:
        self.assertEqual(
            {topic for case in self.cases for topic in case["expected"]["topics"]},
            {"technology", "art", "actors", "genres", "works"},
        )
        self.assertEqual(
            {case["expected"]["intent"] for case in self.cases} - {None},
            {
                "reference",
                "explain",
                "historical_overview",
                "timeline",
                "compare",
                "fact_check",
                "artistic_significance",
                "source_selection",
            },
        )
        self.assertEqual(
            {case["expected"]["scope_status"] for case in self.cases},
            {"in_scope", "mixed", "out_of_scope", "undetermined"},
        )

    def test_context_and_pending_role_boundaries(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["case_id"]):
                context, expected = case["context"], case["expected"]
                self.assertEqual(context["locale"], "ru")
                known = {entity["id"] for entity in context["entities"]}
                for entity in expected["entities"]:
                    if entity["context_id"] is not None:
                        self.assertIn(entity["context_id"], known)
                if expected["role"]["status"] == "pending_A13":
                    self.assertNotIn("role", case["annotation"]["scored_fields"])
                    self.assertIsNone(expected["role"]["value"])
                if context["clarification_rounds_used"] >= 1:
                    self.assertFalse(expected["needs_clarification"])
                if expected["needs_clarification"]:
                    self.assertEqual(expected["search"], "forbidden")

    def test_splits_do_not_share_inputs_or_groups(self) -> None:
        splits: dict[str, set[str]] = {}
        groups: dict[str, set[str]] = {}
        for case in self.cases:
            split = case["split"]
            self.assertIn(split, {"development", "evaluation"})
            text = " ".join(case["input"].casefold().split())
            self.assertNotIn(text, splits.setdefault(split, set()))
            splits[split].add(text)
            groups.setdefault(split, set()).add(case["group_id"])
        self.assertFalse(splits["development"] & splits["evaluation"])
        self.assertFalse(groups["development"] & groups["evaluation"])
        for split in splits:
            selected = [case for case in self.cases if case["split"] == split]
            self.assertEqual(len({c["expected"]["intent"] for c in selected} - {None}), 8)
            self.assertEqual(len({t for c in selected for t in c["expected"]["topics"]}), 5)


if __name__ == "__main__":
    unittest.main()
