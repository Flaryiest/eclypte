"""Guarded OCR-signal tests: verify Tesseract actually counts credit text.

Skips cleanly without cv2 / pytesseract / the tesseract binary. The decision
logic itself is covered moviepy/tesseract-free in test_credits.py.
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pytesseract = pytest.importorskip("pytesseract")
from pytesseract import Output

from api.prototyping.video.credits import MIN_WORDS, _count_words


def _tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _tesseract_available(), reason="tesseract binary not installed"
)


def _credit_frame():
    img = np.zeros((480, 854, 3), dtype=np.uint8)
    lines = [
        "DIRECTED BY JANE DOE",
        "PRODUCED BY JOHN SMITH",
        "MUSIC BY THE BAND",
        "CAST IN ORDER OF APPEARANCE",
    ]
    y = 90
    for line in lines:
        cv2.putText(img, line, (40, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        y += 90
    return img


def test_count_words_high_on_credit_text():
    assert _count_words(_credit_frame(), cv2, pytesseract, Output) >= MIN_WORDS


def test_count_words_low_on_plain_frame():
    plain = np.full((480, 854, 3), 40, dtype=np.uint8)
    assert _count_words(plain, cv2, pytesseract, Output) < MIN_WORDS
