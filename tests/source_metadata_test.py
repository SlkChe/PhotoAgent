"""Регрессия QA-D01: неизвестное значение — null, а не пустой текст."""

import json
import unittest
from copy import deepcopy
from pathlib import Path

from pydantic import ValidationError

from shared.mvp_contracts.answer import AnswerSection
from shared.mvp_contracts.evidence import AnswerFragment, AnswerSource, Gap, Source
from shared.mvp_contracts.query import ContextUpdate, Entity


class SourceMetadataTest(unittest.TestCase):
    def test_nullable_text_rejects_blanks_preserves_partial_values(self) -> None:
        data = json.loads(Path("docs/mvp-1/contract-examples.json").read_text())
        cases = [
            (AnswerSource, data["answer"]["sources"][0], "author_or_organization", "Автор"),
            (AnswerSource, data["answer"]["sources"][0], "published_date", "1900"),
            (Source, data["evidence"]["sources"][0], "origin_group", "archive"),
            (AnswerFragment, data["answer"]["fragments"][0], "locator", "с. 10"),
            (Entity, data["query_analysis"]["entities"][0], "external_id", "catalog-1"),
            (ContextUpdate, data["query_analysis"]["context_update"], "pending_action", "clarify"),
            (
                AnswerSection,
                {"section_id": "s1", "heading": None, "text": "Текст", "claim_ids": []},
                "heading",
                "Дата",
            ),
            (
                Gap,
                {"subquestion_id": None, "description": "Нет источника", "reason": "no_results"},
                "subquestion_id",
                "q1",
            ),
        ]
        for model, original, field, valid in cases:
            for value in (None, valid, "", "   ", "\t\n", "\u00a0"):
                body = deepcopy(original)
                body[field] = value
                with self.subTest(model=model.__name__, field=field, value=repr(value)):
                    if value is None or value == valid:
                        self.assertEqual(getattr(model.model_validate(body), field), value)
                    else:
                        with self.assertRaises(ValidationError):
                            model.model_validate(body)
