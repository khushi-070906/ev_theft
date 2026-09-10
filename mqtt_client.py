"""
MQTT client: subscribes to auth events (from your app/RFID backend) and
publishes theft alerts. Uses mutual TLS so a compromised device can't
impersonate others on the broker.
"""

import json
import time

import config

import os

try:
    import paho.mqtt.client as mqtt
    _PAHO_INSTALLED = True
except ImportError:
    _PAHO_INSTALLED = False

# Only treat MQTT as "available" if the library is installed AND the
# TLS certs actually exist on disk — otherwise fall back to dev-mode
# stubs instead of crashing on a missing cert file.
HARDWARE_AVAILABLE = _PAHO_INSTALLED and os.path.exists(config.MQTT_CA_CERT) \
    if _PAHO_INSTALLED else False


class ChargerMQTTClient:
    def __init__(self, sensor_hub):
        self.sensor_hub = sensor_hub
        self._client = None

        if HARDWARE_AVAILABLE:
            self._client = mqtt.Client(client_id=config.MQTT_CLIENT_ID)
            if config.MQTT_USE_TLS:
                self._client.tls_set(
                    ca_certs=config.MQTT_CA_CERT,
                    certfile=config.MQTT_CLIENT_CERT,
                    keyfile=config.MQTT_CLIENT_KEY,
                )
            self._client.on_connect = self._on_connect
            self._client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        print(f"[mqtt] connected, rc={rc}")
        client.subscribe(config.MQTT_TOPIC_AUTH, qos=1)

    def _on_message(self, client, userdata, msg):
        if msg.topic == config.MQTT_TOPIC_AUTH:
            self.sensor_hub.record_auth_event()

    def connect(self):
        if not HARDWARE_AVAILABLE:
            print("[mqtt] (dev-mode) skipping real connection")
            return
        self._client.connect(config.MQTT_BROKER, config.MQTT_PORT)
        self._client.loop_start()

    def publish_alert(self, event_type, extra=None):
        payload = {
            "device_id": config.DEVICE_ID,
            "timestamp": time.time(),
            "event_type": event_type,
        }
        extra = dict(extra) if extra else {}
        topic = extra.pop("topic_override", config.MQTT_TOPIC_ALERT)
        payload.update(extra)

        if not HARDWARE_AVAILABLE:
            print(f"[mqtt] (dev-mode) would publish to {topic}: {payload}")
            return payload

        self._client.publish(topic, json.dumps(payload), qos=1)
        print(f"[mqtt] published to {topic}: {payload}")
        return payload
