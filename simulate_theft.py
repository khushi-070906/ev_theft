"""
DEV-ONLY: simulates an unauthorized unplug so you can watch the full
theft-alert pipeline run on a laptop, with no real hardware attached.

This does NOT touch main.py or any hardware code. It just:
  1. Starts the recorder + state machine like main.py does.
  2. Waits a few seconds in the normal "docked" state.
  3. Flips the (stubbed) holster switch to "undocked" with no auth tap
     recorded -- exactly what a real theft looks like to the state
     machine -- and lets the ALERT flow run for real.
  4. Prints the resulting incident from incidents.json when it's done.

Speeds up POST_EVENT_MINUTES for this run only, so you don't have to
wait 15 real minutes to see it finish. Run it the same way as main.py:

    python simulate_theft.py
"""

import time

import config

# Shrink the post-event window just for this demo run so the full
# ALERT -> IDLE cycle finishes in well under a minute instead of 15+.
config.POST_EVENT_MINUTES = 0.15   # ~9 seconds
config.PLATE_OCR_FRAME_COUNT = 2

from recorder import RollingBufferRecorder
from sensors import SensorHub
from mqtt_client import ChargerMQTTClient
from state_machine import TheftDetectionStateMachine
import incidents_store


def main():
    print("[sim] starting recorder + state machine (dev mode)")
    sensors = SensorHub()
    recorder = RollingBufferRecorder()
    mqtt_client = ChargerMQTTClient(sensors)
    machine = TheftDetectionStateMachine(recorder, sensors, mqtt_client, camera=recorder._camera)

    # Override the stubbed holster switch so we control it directly,
    # instead of the dev-mode default that's always "docked".
    docked = {"value": True}
    sensors.is_plug_docked = lambda: docked["value"]

    recorder.start()
    machine.start()

    print("[sim] system idle, plug 'docked'. Waiting 3s...")
    time.sleep(3)

    print("[sim] simulating unauthorized unplug (no auth tap recorded) ...")
    docked["value"] = False

    seen_alert = False
    deadline = time.time() + 60
    while time.time() < deadline:
        if machine.state.name == "ALERT":
            if not seen_alert:
                print("[sim] state machine entered ALERT -- watch the logs above")
            seen_alert = True
        if seen_alert and machine.state.name == "IDLE":
            break
        time.sleep(0.5)

    if not seen_alert:
        print("[sim] never saw ALERT fire -- something's off, check the logs above")
    else:
        print("[sim] incident cycle complete, back to IDLE")

    incidents = incidents_store.get_incidents(limit=1)
    if incidents:
        print(f"[sim] last incident recorded: {incidents[0]}")
    else:
        print(f"[sim] check {config.incidents_db_path()} and the dashboard for the new incident")

    machine.stop()
    recorder.stop()
    sensors.cleanup()
    print("[sim] done")


if __name__ == "__main__":
    main()
