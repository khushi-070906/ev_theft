"""
Minimal web dashboard for viewing incidents. Run this alongside main.py
(it's a separate process — the theft detection system doesn't depend on
the dashboard being up, and vice versa).

Usage:
    python3 dashboard/app.py

Then visit http://<pi-ip>:5000 from your phone or laptop on the same
network.
"""

import os
import sys

from flask import Flask, jsonify, send_file, abort

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import incidents_store

app = Flask(__name__)


@app.route("/")
def index():
    incidents = incidents_store.get_incidents()
    rows = "".join(_render_incident_row(i) for i in incidents)
    if not rows:
        rows = "<p class='empty'>No incidents yet. That's a good thing.</p>"

    return f"""
    <html>
    <head>
        <title>Charger Security — {config.DEVICE_ID}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: -apple-system, sans-serif; max-width: 700px;
                    margin: 0 auto; padding: 16px; background: #f5f5f5; }}
            h1 {{ font-size: 20px; }}
            .incident {{ background: white; border-radius: 10px; padding: 14px;
                         margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            .incident.high-priority {{ border-left: 4px solid #E24B4A; }}
            .incident img {{ max-width: 100%; border-radius: 6px; margin-top: 8px; }}
            .meta {{ color: #666; font-size: 13px; }}
            .badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px;
                      font-size: 12px; background: #eee; margin-right: 6px; }}
            .badge.plate {{ background: #d4edda; }}
            .empty {{ color: #888; text-align: center; margin-top: 40px; }}
        </style>
    </head>
    <body>
        <h1>Charger Security — {config.DEVICE_ID}</h1>
        {rows}
    </body>
    </html>
    """


def _render_incident_row(incident):
    import datetime
    dt = datetime.datetime.fromtimestamp(incident["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
    priority_class = "high-priority" if incident.get("high_priority") else ""
    plate_badge = f"<span class='badge plate'>Plate: {incident['plate']}</span>" if incident.get("plate") else ""
    confidence = incident.get("person_confidence")
    conf_badge = f"<span class='badge'>Person confidence: {confidence:.0%}</span>" if confidence is not None else ""
    ack_badge = "<span class='badge'>Acknowledged</span>" if incident.get("acknowledged") else ""

    img_tag = ""
    if incident.get("snapshot_path") and os.path.exists(incident["snapshot_path"]):
        img_tag = f"<img src='/snapshot/{incident['id']}' />"

    return f"""
    <div class="incident {priority_class}">
        <strong>{incident['event_type'].replace('_', ' ').title()}</strong>
        <div class="meta">{dt}</div>
        <div>{plate_badge}{conf_badge}{ack_badge}</div>
        {img_tag}
    </div>
    """


@app.route("/snapshot/<int:incident_id>")
def snapshot(incident_id):
    for incident in incidents_store.get_incidents(limit=1000):
        if incident["id"] == incident_id and incident.get("snapshot_path"):
            if os.path.exists(incident["snapshot_path"]):
                return send_file(incident["snapshot_path"])
    abort(404)


@app.route("/api/incidents")
def api_incidents():
    return jsonify(incidents_store.get_incidents())


@app.route("/api/incidents/<int:incident_id>/acknowledge", methods=["POST"])
def api_acknowledge(incident_id):
    incidents_store.acknowledge(incident_id)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT)
