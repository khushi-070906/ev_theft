"""
Confirms whether a person is actually present in a snapshot before the
system commits to a full theft alert. This is what filters out false
triggers from wind, sensor noise, or an animal near the charger.

Two backends, auto-selected:

1. YOLOv8n ONNX (if you provide a model file) — more accurate, but you
   need to supply the .onnx file yourself (export one with `yolo export
   model=yolov8n.pt format=onnx`, or download a pre-exported one from a
   source you trust). Runs fine on a Pi via onnxruntime, just slower
   than on real hardware with a GPU.

2. OpenCV's built-in HOG people detector — ships with opencv-python,
   needs no download, noticeably less accurate on partial/side views
   but good enough as a baseline and works out of the box.

The code picks whichever is available at startup and logs which one
it's using, so you always know which detector produced a given result.
"""

import os

import cv2
import numpy as np

import config

try:
    import onnxruntime
    ONNXRUNTIME_AVAILABLE = True
except ImportError:
    ONNXRUNTIME_AVAILABLE = False


class PersonDetector:
    def __init__(self):
        self.backend = "none"
        self._session = None
        self._hog = None

        if not config.PERSON_DETECTION_ENABLED:
            return

        if ONNXRUNTIME_AVAILABLE and os.path.exists(config.YOLO_ONNX_MODEL_PATH):
            self._session = onnxruntime.InferenceSession(config.YOLO_ONNX_MODEL_PATH)
            self.backend = "yolov8n_onnx"
        else:
            self._hog = cv2.HOGDescriptor()
            self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            self.backend = "opencv_hog"

        print(f"[person_detection] using backend: {self.backend}")

    def is_person_present(self, image_path):
        """
        Returns (found: bool, confidence: float). Confidence is a rough
        proxy — for HOG it's normalized detection weight, for YOLO it's
        the model's own class confidence.
        """
        if not config.PERSON_DETECTION_ENABLED:
            return True, 1.0  # detection disabled — don't gate anything

        if not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
            return False, 0.0  # dev-mode stub file, nothing to actually check

        image = cv2.imread(image_path)
        if image is None:
            return False, 0.0

        if self.backend == "yolov8n_onnx":
            return self._detect_yolo(image)
        elif self.backend == "opencv_hog":
            return self._detect_hog(image)
        return False, 0.0

    def _detect_hog(self, image):
        boxes, weights = self._hog.detectMultiScale(
            image, winStride=(8, 8), padding=(8, 8), scale=1.05
        )
        if len(weights) == 0:
            return False, 0.0
        best = float(max(weights))
        # HOG weights aren't a clean 0-1 probability; a rough usable
        # normalization for the default SVM is dividing by ~2.0
        confidence = min(best / 2.0, 1.0)
        return confidence >= config.PERSON_DETECTION_MIN_CONFIDENCE, confidence

    def _detect_yolo(self, image):
        input_size = 640
        resized = cv2.resize(image, (input_size, input_size))
        blob = resized.transpose(2, 0, 1)[np.newaxis].astype(np.float32) / 255.0

        input_name = self._session.get_inputs()[0].name
        outputs = self._session.run(None, {input_name: blob})[0]

        # YOLOv8 ONNX output: (1, 84, 8400) — class 0 is "person" in COCO
        best_conf = 0.0
        for detection in outputs[0].T:
            person_conf = detection[4]  # class 0 confidence, index depends on export
            if person_conf > best_conf:
                best_conf = float(person_conf)

        return best_conf >= config.PERSON_DETECTION_MIN_CONFIDENCE, best_conf
