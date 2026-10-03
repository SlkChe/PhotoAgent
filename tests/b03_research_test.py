"""Проверки измерительного инструмента; не приёмка качества анализатора."""

import unittest
from unittest.mock import patch

from scripts.b03.run import run_case
from scripts.b03.schema import AnalysisInput, Projection
from scripts.b03.scoring import score_case, summarize


def case_fixture() -> dict:
    """Независимый технический пример, не метка evaluation."""
    return {
        "case_id": "unit-1",
        "split": "evaluation",
        "input": "Объясни диафрагму",
        "context": {"locale": "ru", "entities": []},
        "expected": {
            "topics": ["technology"],
            "intent": "explain",
            "needs_clarification": False,
            "role": {"status": "pending_A13", "value": None},
        },
        "annotation": {"scored_fields": ["topics", "intent", "needs_clarification", "role"]},
    }


def projection_fixture() -> Projection:
    """Полная валидная исследовательская проекция."""
    return Projection(
        topics=["technology"],
        intent="explain",
        dialogue_act="ask",
        scope_status="in_scope",
        needs_clarification=False,
        response_mode="focused",
        role=None,
        entities=[],
        excluded_parts=[],
        subquestion_intents=[],
        search="required_for_new_facts",
        cloud_generation="allowed_after_evidence",
    )


class B03ResearchTest(unittest.TestCase):
    def test_analyzer_gets_no_labels_and_no_case_id(self) -> None:
        seen = []

        def analyzer(data: AnalysisInput) -> Projection:
            seen.append(data.model_dump())
            return projection_fixture()

        with patch("scripts.b03.run.baseline.analyze", side_effect=analyzer):
            row = run_case("rules", case_fixture(), "serial", 0)
        self.assertIsNone(row["error"])
        self.assertEqual(set(seen[0]), {"input", "context"})
        self.assertNotIn("expected", seen[0])

    def test_failed_case_stays_in_denominator(self) -> None:
        case = case_fixture()
        with patch("scripts.b03.run.baseline.analyze", side_effect=ValueError("invalid")):
            row = run_case("rules", case, "serial", 0)
        result = summarize([case], [row])["serial/evaluation"]
        self.assertEqual(result["invalid"], 1)
        self.assertEqual(result["fields"]["intent"]["correct"], 0)
        self.assertEqual(result["fields"]["intent"]["total"], 1)
        self.assertNotIn("role", result["fields"])

    def test_topics_are_sets_and_null_is_not_missing(self) -> None:
        case = case_fixture()
        case["expected"]["topics"] = ["art", "technology"]
        case["expected"]["intent"] = None
        output = {"topics": ["technology", "art"], "intent": None, "needs_clarification": False}
        self.assertTrue(all(score_case(case, output).values()))
        del output["intent"]
        self.assertFalse(score_case(case, output)["intent"])

    def test_accepted_role_and_optional_clarification(self) -> None:
        case = case_fixture()
        case["expected"]["role"] = {"status": "accepted", "value": "Друг"}
        case["expected"]["clarification_options"] = [False, True]
        output = projection_fixture().model_dump()
        output.update(role="Друг", needs_clarification=True)
        self.assertTrue(all(score_case(case, output).values()))

    def test_input_context_is_not_shared_between_calls(self) -> None:
        case = case_fixture()
        observations = []

        def analyzer(data: AnalysisInput) -> Projection:
            observations.append(len(data.context["entities"]))
            data.context["entities"].append({"label": "test"})
            return projection_fixture()

        with patch("scripts.b03.run.baseline.analyze", side_effect=analyzer):
            run_case("rules", case, "serial", 0)
            run_case("rules", case, "serial", 1)
        self.assertEqual(observations, [0, 0])
        self.assertEqual(case["context"]["entities"], [])

    def test_truncated_model_response_is_not_validated_as_success(self) -> None:
        response = {
            "choices": [
                {
                    "message": {"content": projection_fixture().model_dump_json()},
                    "finish_reason": "length",
                }
            ]
        }
        with patch("scripts.b03.runtime.request", return_value=response):
            row = run_case("model", case_fixture(), "serial", 0)
        self.assertIsNone(row["output"])
        self.assertEqual(row["metadata"]["finish_reason"], "length")


if __name__ == "__main__":
    unittest.main()
