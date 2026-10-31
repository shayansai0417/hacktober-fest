from __future__ import annotations

from io import BytesIO

import fitz
import pytest
from PIL import Image

from utils.image_processing import expand_uploads, normalize_image, validate_file


def image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (640, 840), "white").save(output, format="PNG")
    return output.getvalue()


def pdf_bytes(pages=2) -> bytes:
    document = fitz.open()
    for i in range(pages):
        page = document.new_page(width=612, height=792)
        page.insert_text((72, 80), f"Answer sheet page {i + 1}")
    content = document.tobytes()
    document.close()
    return content


def test_valid_image_and_orientation_safe_normalization():
    image = image_bytes()
    assert validate_file("answer.png", image, 2) == ".png"
    normalized = normalize_image(image)
    with Image.open(BytesIO(normalized)) as output:
        assert output.format == "JPEG"
        assert output.size == (640, 840)


@pytest.mark.parametrize("name,data,limit,message", [
    ("notes.txt", b"hello", 2, "Use a JPG"),
    ("empty.png", b"", 2, "empty"),
    ("corrupt.png", b"not-image", 2, "could not be opened"),
    ("large.png", b"x" * (1024 * 1024 + 1), 1, "exceeds"),
    ("broken.pdf", b"not a PDF", 2, "valid PDF"),
], ids=["unknown-type", "empty-file", "corrupt-image", "oversized-image", "invalid-pdf"])
def test_invalid_files_are_rejected(name, data, limit, message):
    with pytest.raises(ValueError, match=message):
        validate_file(name, data, limit)


def test_pdf_conversion_preserves_multiple_pages():
    pages = expand_uploads([("answers.pdf", pdf_bytes(3))], 2)
    assert len(pages) == 3
    assert all(name.endswith(".jpg") for name, _ in pages)
    assert all(data.startswith(b"\xff\xd8") for _, data in pages)


def test_empty_pdf_and_too_many_pdf_pages_fail():
    with pytest.raises(ValueError):
        expand_uploads([("empty.pdf", b"")], 2)
    with pytest.raises(ValueError, match="30 pages"):
        expand_uploads([("many.pdf", pdf_bytes(31))], 5)

