"""
The brain of the system. Implements the state machine:

  IDLE -> ARMED_CHECK -> CHARGING_SESSION -> IDLE   (normal customer)
  IDLE -> ARMED_CHECK -> ALERT                       (theft, no auth)
  CHARGING_SESSION -> ALERT                          (cable cut mid-session)

On ALERT, it locks the rolling buffer, sends an immediate snapshot alert,
waits out the post-event window, assembles the full clip, and uploads it.
"""

import enum
import threading
import time

import os

import config
import incidents_store
import person_detection
import plate_ocr
import upload


class State(enum.Enum):
    IDLE = "idle"
    ARMED_CHECK = "armed_check"
    CHARGING_SESSION = "charging_session"
    ALERT = "alert"


class TheftDetectionStateMachine:
    def __init__(self, recorder, sensors, mqtt_client, camera=None):
        self.recorder = recorder
        self.sensors = sensors
        self.mqtt_client = mqtt_client
        self.camera = camera
        self.person_detector = person_detection.PersonDetector()
        self.state = State.IDLE
        self._armed_check_started_at = None
        self._last_alert_at = 0
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            self._tick()
            time.sleep(1.0 / config.CURRENT_SAMPLE_HZ if self.state == State.CHARGING_SESSION else 0.5)

    def _tick(self):
        if self.state == State.IDLE:
            self._tick_idle()
        elif self.state == State.ARMED_CHECK:
            self._tick_armed_check()
        elif self.state == State.CHARGING_SESSION:
            self._tick_charging_session()
        # ALERT state runs its own blocking sequence in _trigger_alert(),
        # so there's nothing to poll here.

    def _tick_idle(self):
        # In a full build, motion/mmWave sensor GPIO would set a flag here.
        # Simplified: treat "plug undocked" itself as the wake condition too,
        # since a docked->undocked edge always needs a decision either way.
        if not self.sensors.is_plug_docked():
            print("[state] motion/undock detected -> ARMED_CHECK")
            self.state = State.ARMED_CHECK
            self._armed_check_started_at = time.time()

    def _tick_armed_check(self):
        if self.sensors.is_auth_recent():
            print("[state] authorized session confirmed -> CHARGING_SESSION")
            self.sensors.set_baseline_current()
            self.state = State.CHARGING_SESSION
            return

        elapsed = time.time() - self._armed_check_started_at
        if not self.sensors.is_plug_docked() and elapsed > 2:
            # plug removed, still no auth after a couple seconds — theft
            print("[state] plug removed with no auth -> ALERT")
            self._trigger_alert("unauthorized_removal")
            return

        if elapsed > config.ARMED_CHECK_TIMEOUT_SECONDS:
            print("[state] armed-check timed out with no activity -> IDLE")
            self.state = State.IDLE

    def _tick_charging_session(self):
        if self.sensors.check_current_anomaly():
            print("[state] current anomaly during active session -> ALERT")
            self._trigger_alert("cable_cut_mid_session", high_priority=True)
            return

        if self.sensors.is_plug_docked():
            # normal end of session
            print("[state] session ended normally -> IDLE")
            self.state = State.IDLE

    def _trigger_alert(self, event_type, high_priority=False):
        if time.time() - self._last_alert_at < config.ALERT_COOLDOWN_SECONDS:
            print("[state] alert suppressed (cooldown active)")
            return

        self.state = State.ALERT
        self._last_alert_at = time.time()
        incident_id = int(time.time())

        # 1. Lock the buffer immediately — protects the "before" footage.
        #    This happens before any vision checks, since we'd rather have
        #    footage we don't end up needing than lose footage we do.
        self.recorder.lock_incident()

        # 2. Quick snapshot + person-detection check. A miss doesn't
        #    cancel the alert (better a low-confidence alert than a
        #    missed theft) — it just gets flagged so a human reviewing
        #    it knows to double check.
        snapshot_path = f"{config.STORAGE_DIR}/snapshot_{incident_id}.jpg"
        upload.capture_snapshot(self.camera, snapshot_path)
        person_found, confidence = self.person_detector.is_person_present(snapshot_path)
        if not person_found:
            print(f"[state] person detection: no person found (confidence {confidence:.2f}) "
                  f"— sending alert anyway, flagged low-confidence")
        else:
            print(f"[state] person detection: confirmed (confidence {confidence:.2f})")

        # 3. Sound the buzzer and send a fast, lightweight alert.
        self.sensors.sound_buzzer(duration_seconds=5)
        self.mqtt_client.publish_alert(event_type, extra={
            "high_priority": high_priority,
            "person_confidence": confidence,
            "incident_id": incident_id,
        })

        # 4. Wait out the post-event window (recording continues normally
        #    in the recorder's own thread; we just wait here). Along the
        #    way, grab a few more frames to attempt a plate read.
        print(f"[state] recording post-event window ({config.POST_EVENT_MINUTES} min)")
        plate = None
        if config.PLATE_OCR_ENABLED:
            plate_frame_paths = []
            frame_interval = max(
                (config.POST_EVENT_MINUTES * 60) / config.PLATE_OCR_FRAME_COUNT, 1
            )
            for i in range(config.PLATE_OCR_FRAME_COUNT):
                time.sleep(frame_interval)
                frame_path = f"{config.STORAGE_DIR}/plate_frame_{incident_id}_{i}.jpg"
                upload.capture_snapshot(self.camera, frame_path)
                plate_frame_paths.append(frame_path)
            plate = plate_ocr.read_plate_from_frames(plate_frame_paths)
        else:
            time.sleep(config.POST_EVENT_MINUTES * 60)

        # 5. Assemble and upload the full clip.
        segment_paths = self.recorder.get_locked_segment_paths()
        output_path = f"{config.STORAGE_DIR}/incident_{incident_id}.mp4"
        try:
            upload.concat_segments(segment_paths, output_path)
            upload.upload_clip(output_path)
        except Exception as e:
            print(f"[state] clip assembly/upload failed: {e}")
            output_path = None

        # 6. Log it so the dashboard can show it.
        incidents_store.add_incident(
            event_type=event_type,
            snapshot_path=snapshot_path,
            clip_path=output_path,
            person_confidence=confidence,
            plate=plate,
            high_priority=high_priority,
        )

        # 7. Resume normal loop recording.
        self.recorder.unlock_and_resume()
        self.state = State.IDLE
