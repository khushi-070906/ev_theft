"""
Entry point. Run this on the Raspberry Pi to start the full system:
continuous rolling-buffer recording, sensor monitoring, and the theft
detection state machine.

Usage:
    python3 main.py
"""

import signal
import sys
import time

from fire_smoke import FireSmokeMonitor
from mqtt_client import ChargerMQTTClient
from recorder import RollingBufferRecorder
from sensors import SensorHub
from state_machine import TheftDetectionStateMachine


def main():
    print("[main] starting EV charger theft detection system")

    sensors = SensorHub()
    recorder = RollingBufferRecorder()
    mqtt_client = ChargerMQTTClient(sensors)
    machine = TheftDetectionStateMachine(recorder, sensors, mqtt_client, camera=recorder._camera)
    fire_monitor = FireSmokeMonitor(sensors, recorder, mqtt_client)

    mqtt_client.connect()
    recorder.start()
    machine.start()
    fire_monitor.start()

    print("[main] tip: run `python3 dashboard/app.py` in a separate "
          "process/terminal to view incidents in a browser")

    def shutdown(signum, frame):
        print("\n[main] shutting down...")
        machine.stop()
        fire_monitor.stop()
        recorder.stop()
        sensors.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("[main] system running. Press Ctrl+C to stop.")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
