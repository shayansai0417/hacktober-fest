"""Upload validation, image normalization, and safe page serialization."""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

from PIL import Image, ImageOps
import cv2
import numpy as np


ALLOWED = {".jpg", ".jpeg", ".png", ".pdf"}


def safe_name(name: str) -> str:
    name = Path(name or "answer-sheet").name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._")
    return name[:120] or "answer-sheet"


def validate_file(name: str, data: bytes, max_size_mb: int) -> str:
    extension = Path(name).suffix.lower()
    if extension not in ALLOWED:
        raise ValueError("Use a JPG, PNG, or PDF answer sheet.")
    if not data:
        raise ValueError(f"{name}: the file is empty.")
    if len(data) > max_size_mb * 1024 * 1024:
        raise ValueError(f"{name}: file exceeds the {max_size_mb} MB limit.")
    if extension == ".pdf" and not data.startswith(b"%PDF"):
        raise ValueError(f"{name}: this does not look like a valid PDF.")
    if extension in {".jpg", ".jpeg", ".png"}:
        try:
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
        except Exception as exc:
            raise ValueError(f"{name}: this image could not be opened.") from exc
    return extension


def normalize_image(data: bytes, enhance: bool = True) -> bytes:
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        if max(image.size) > 2000:
            ratio = 2000 / max(image.size)
            image = image.resize((round(image.width * ratio), round(image.height * ratio)), Image.Resampling.LANCZOS)
        if enhance:
            pixels = np.asarray(image)
            gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
            low, high = np.percentile(gray, [3, 97])
            if high - low < 105:
                # A low clip-limit keeps pencil strokes legible without aggressive thresholding.
                lab = cv2.cvtColor(pixels, cv2.COLOR_RGB2LAB)
                luminance, channel_a, channel_b = cv2.split(lab)
                luminance = cv2.createCLAHE(clipLimit=1.15, tileGridSize=(8, 8)).apply(luminance)
                image = Image.fromarray(cv2.cvtColor(cv2.merge((luminance, channel_a, channel_b)), cv2.COLOR_LAB2RGB))
            angle = _estimate_skew_degrees(gray)
            if 0.8 < abs(angle) < 4.0:
                image = image.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=88, optimize=True)
        return out.getvalue()


def _estimate_skew_degrees(gray: np.ndarray) -> float:
    """Estimate a small page tilt from long horizontal text/rule segments."""
    edges = cv2.Canny(gray, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80, minLineLength=max(120, gray.shape[1] // 5), maxLineGap=16)
    if lines is None:
        return 0.0
    angles = []
    for line in lines[:, 0]:
        x1, y1, x2, y2 = map(int, line)
        angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        if abs(angle) < 12:
            angles.append(angle)
    return float(np.median(angles)) if angles else 0.0


def pdf_to_images(data: bytes, max_pages: int = 30) -> list[bytes]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PDF support requires PyMuPDF. Install the project dependencies.") from exc
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        if doc.page_count > max_pages:
            raise ValueError(f"PDFs are limited to {max_pages} pages per answer sheet.")
        result = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            result.append(normalize_image(pix.tobytes("png")))
        if not result:
            raise ValueError("This PDF contains no pages.")
        return result
    finally:
        doc.close()


def extract_pdf_text(data: bytes, max_pages: int = 30) -> str:
    """Return selectable PDF text without rasterizing pages for OCR."""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PDF support requires PyMuPDF. Install the project dependencies.") from exc
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        if doc.page_count > max_pages:
            raise ValueError(f"PDFs are limited to {max_pages} pages per marking scheme.")
        text_pages = []
        for page in doc:
            page_text = page.get_text("text").strip()
            if page_text:
                text_pages.append(page_text)
        return "\n\n".join(text_pages)
    finally:
        doc.close()


def expand_uploads(files: list[tuple[str, bytes]], max_size_mb: int) -> list[tuple[str, bytes]]:
    pages: list[tuple[str, bytes]] = []
    total = 0
    for name, data in files:
        ext = validate_file(name, data, max_size_mb)
        total += len(data)
        if total > max_size_mb * 4 * 1024 * 1024:
            raise ValueError("Combined answer sheet uploads exceed the 4× file size limit.")
        if ext == ".pdf":
            pages.extend((safe_name(f"{Path(name).stem}-page-{i + 1}.jpg"), image) for i, image in enumerate(pdf_to_images(data)))
        else:
            pages.append((safe_name(name), normalize_image(data)))
    if not pages:
        raise ValueError("Upload at least one answer sheet page.")
    return pages


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

