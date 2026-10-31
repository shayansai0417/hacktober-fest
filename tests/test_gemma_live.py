from __future__ import annotations

import os
from io import BytesIO

import pytest
from PIL import Image

from schemas import MarkingQuestion, MarkingScheme
from services.gemma_service import grade_pages


pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE_GEMMA_TEST") != "1" or not os.getenv("GEMMA_API_KEY"), reason="Set RUN_LIVE_GEMMA_TEST=1 and GEMMA_API_KEY to opt in to a paid live Gemma request.")


def test_live_gemma_reads_a_synthetic_image():
    image = Image.new("RGB", (600, 400), "white")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(image)
    draw.text((60, 100), "Q1: 2 + 2 = 4", fill="#222")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    scheme = MarkingScheme(questions=[MarkingQuestion(number=1, prompt="What is 2 + 2?", expected_answer="4", max_marks=1, key_concepts=["4"])])
    result = grade_pages([buffer.getvalue()], scheme, "Synthetic test learner")
    assert result.question_evaluations[0].question_number == 1
