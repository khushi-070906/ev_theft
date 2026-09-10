"""
Continuous rolling-buffer recorder.

Records fixed-length video segments in a loop. Segments older than
BUFFER_MINUTES are deleted automatically UNLESS they are "locked"
(protected) because an incident is in progress.

Runs in its own thread; other modules call lock_incident() to protect
the current buffer and extend recording for the post-event window.
"""

import json
import os
import threading
import time
from datetime import datetime

import config

try:
    from picamera2 import Picamera2
    from picamera2.encoders import H264Encoder
    from picamera2.outputs import FfmpegOutput
    HARDWARE_AVAILABLE = True
except ImportError:
    # Lets you import/test the buffer logic on a dev machine without a Pi camera attached.
    HARDWARE_AVAILABLE = False


class RollingBufferRecorder:
    def __init__(self):
        os.makedirs(config.STORAGE_DIR, exist_ok=True)
        self._lock = threading.Lock()
        self._segments = []          # list of dicts: {path, created_at, locked}
        self._recording_thread = None
        self._running = False
        self._camera = None
        self._load_state()

        if HARDWARE_AVAILABLE:
            self._camera = Picamera2()
            video_config = self._camera.create_video_configuration(
                main={"size": config.VIDEO_RESOLUTION}
            )
            self._camera.configure(video_config)

    # ---------- persistence ----------

    def _load_state(self):
        if os.path.exists(config.state_file_path()):
            try:
                with open(config.state_file_path(), "r") as f:
                    self._segments = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._segments = []

    def _save_state(self):
        with open(config.state_file_path(), "w") as f:
            json.dump(self._segments, f)

    # ---------- main recording loop ----------

    def start(self):
        self._running = True
        self._recording_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._recording_thread.start()

    def stop(self):
        self._running = False
        if self._recording_thread:
            self._recording_thread.join(timeout=config.SEGMENT_SECONDS + 5)

    def _record_loop(self):
        while self._running:
            self._record_one_segment()
            self._prune_old_segments()

    def _record_one_segment(self):
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        filename = f"seg_{timestamp}.mp4"
        filepath = os.path.join(config.STORAGE_DIR, filename)

        if HARDWARE_AVAILABLE:
            encoder = H264Encoder(bitrate=config.VIDEO_BITRATE)
            output = FfmpegOutput(filepath)
            self._camera.start_recording(encoder, output)
            time.sleep(config.SEGMENT_SECONDS)
            self._camera.stop_recording()
        else:
            # dev-mode stub: just touch an empty file so the buffer logic can be tested
            open(filepath, "a").close()
            time.sleep(1)

        with self._lock:
            self._segments.append({
                "path": filepath,
                "created_at": time.time(),
                "locked": False,
            })
            self._save_state()

    def _prune_old_segments(self):
        cutoff = time.time() - (config.BUFFER_MINUTES * 60)
        with self._lock:
            keep = []
            for seg in self._segments:
                if seg["locked"] or seg["created_at"] >= cutoff:
                    keep.append(seg)
                else:
                    try:
                        os.remove(seg["path"])
                    except OSError:
                        pass
            self._segments = keep
            self._save_state()

    # ---------- incident handling ----------

    def lock_incident(self):
        """
        Protect the current buffer (the 'before' footage) from deletion.
        Call this the instant a theft trigger fires.
        """
        with self._lock:
            for seg in self._segments:
                seg["locked"] = True
            self._save_state()
        print(f"[recorder] locked {len(self._segments)} pre-incident segments")

    def get_locked_segment_paths(self):
        with self._lock:
            return [s["path"] for s in self._segments if s["locked"]]

    def unlock_and_resume(self):
        """
        Called once the post-event window has been recorded and the
        combined clip has been assembled/uploaded. Resumes normal pruning.
        """
        with self._lock:
            for seg in self._segments:
                seg["locked"] = False
            self._save_state()
        print("[recorder] buffer unlocked, resuming normal loop recording")
