"""
A minimal incident log. Uses a plain JSON file rather than a database —
deliberately simple, since a single device generates at most a handful
of incidents per day and doesn't need real database machinery. If you
later centralize multiple stations, swap this for a real DB/API without
changing the calling code elsewhere (same add_incident/get_incidents
interface).
"""

import json
import os
import threading
import time

import config

_lock = threading.Lock()


def _load():
    if not os.path.exists(config.incidents_db_path()):
        return []
    try:
        with open(config.incidents_db_path(), "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(incidents):
    os.makedirs(os.path.dirname(config.incidents_db_path()), exist_ok=True)
    with open(config.incidents_db_path(), "w") as f:
        json.dump(incidents, f, indent=2)


def add_incident(event_type, snapshot_path=None, clip_path=None,
                  person_confidence=None, plate=None, high_priority=False):
    with _lock:
        incidents = _load()
        incident = {
            "id": len(incidents) + 1,
            "device_id": config.DEVICE_ID,
            "event_type": event_type,
            "timestamp": time.time(),
            "snapshot_path": snapshot_path,
            "clip_path": clip_path,
            "person_confidence": person_confidence,
            "plate": plate,
            "high_priority": high_priority,
            "acknowledged": False,
        }
        incidents.append(incident)
        _save(incidents)
        return incident


def get_incidents(limit=50):
    with _lock:
        incidents = _load()
        return list(reversed(incidents))[:limit]


def acknowledge(incident_id):
    with _lock:
        incidents = _load()
        for incident in incidents:
            if incident["id"] == incident_id:
                incident["acknowledged"] = True
        _save(incidents)
