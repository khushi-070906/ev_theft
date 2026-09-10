"""
Attempts to find and read a license plate in post-event frames.

This uses a classic (non-deep-learning) approach: find rectangular,
high-contrast regions via edge detection + contour analysis, then run
OCR only on candidate regions. It's not as robust as a purpose-built
ALPR model, but needs no extra model download and runs fine on a Pi.

If you get poor results in practice, swapping in OpenALPR or a proper
ALPR ONNX model behind the same read_plate() interface is a drop-in
upgrade — the state machine just calls this function and doesn't care
how the answer was produced.
"""

import re

import cv2

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

# Plates are mostly uppercase letters/digits — this loose pattern filters
# out obvious OCR garbage without assuming any specific country's format.
PLATE_PATTERN = re.compile(r"[A-Z0-9]{5,10}")


def _find_plate_candidates(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)
    edged = cv2.Canny(gray, 30, 200)

    contours, _ = cv2.findContours(edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:10]

    candidates = []
    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.018 * perimeter, True)
        if len(approx) == 4:  # roughly rectangular — plate-shaped
            x, y, w, h = cv2.boundingRect(approx)
            aspect_ratio = w / float(h) if h else 0
            if 2.0 <= aspect_ratio <= 5.5:  # plates are wider than tall, within a range
                candidates.append((x, y, w, h))
    return candidates


def read_plate(image_path):
    """
    Returns the best-guess plate string, or None if nothing plate-shaped
    with readable text was found.
    """
    if not TESSERACT_AVAILABLE:
        print("[plate_ocr] pytesseract not installed, skipping")
        return None

    image = cv2.imread(image_path)
    if image is None:
        return None

    for (x, y, w, h) in _find_plate_candidates(image):
        crop = image[y:y + h, x:x + w]
        gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray_crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        text = pytesseract.image_to_string(
            thresh, config="--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        )
        cleaned = text.strip().upper().replace(" ", "")
        match = PLATE_PATTERN.search(cleaned)
        if match:
            return match.group(0)

    return None


def read_plate_from_frames(image_paths):
    """
    Tries several frames (the post-event window usually gives you a few
    chances) and returns the first plausible plate read, since a single
    frame might be blurry or at a bad angle.
    """
    for path in image_paths:
        plate = read_plate(path)
        if plate:
            print(f"[plate_ocr] read plate '{plate}' from {path}")
            return plate
    return None
