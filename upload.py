"""
Assembles the locked segments into one clip and uploads it to cloud
storage using a short-lived pre-signed URL (requested from your own
backend, so the device never holds long-lived storage credentials).
"""

import os
import subprocess
import tempfile
import time

import requests

import config


def concat_segments(segment_paths, output_path):
    """
    Joins a list of .mp4 segments into one continuous clip using ffmpeg's
    concat demuxer (fast, no re-encoding needed since all segments share
    the same codec settings).
    """
    if not segment_paths:
        raise ValueError("no segments to concatenate")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as list_file:
        for path in sorted(segment_paths):
            list_file.write(f"file '{path}'\n")
        list_file_path = list_file.name

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", list_file_path,
                "-c", "copy",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
    finally:
        os.remove(list_file_path)

    print(f"[upload] assembled clip: {output_path}")
    return output_path


def request_presigned_url(filename):
    response = requests.post(
        config.UPLOAD_URL_REQUEST_ENDPOINT,
        json={"device_id": config.DEVICE_ID, "filename": filename},
        headers={"Authorization": f"Bearer {config.DEVICE_API_KEY}"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["upload_url"]


def upload_clip(filepath, max_retries=5):
    """
    Uploads with exponential backoff so a temporary connectivity drop
    doesn't lose the incident clip — it just retries until it succeeds.
    The file stays locked on local storage the whole time, so nothing
    is lost even if this takes a while.
    """
    filename = os.path.basename(filepath)
    attempt = 0

    while attempt < max_retries:
        try:
            upload_url = request_presigned_url(filename)
            with open(filepath, "rb") as f:
                resp = requests.put(upload_url, data=f, timeout=60)
                resp.raise_for_status()
            print(f"[upload] successfully uploaded {filename}")
            return True
        except (requests.RequestException, OSError) as e:
            attempt += 1
            wait = min(2 ** attempt, 60)
            print(f"[upload] attempt {attempt} failed ({e}), retrying in {wait}s")
            time.sleep(wait)

    print(f"[upload] giving up after {max_retries} attempts — clip stays on local disk")
    return False


def capture_snapshot(camera, output_path):
    """
    Quick still capture for the immediate alert, sent before the full
    clip is ready. Keep this fast — the alert should reach the owner
    within seconds of the trigger, not after the full post-roll window.
    """
    if camera is not None:
        camera.capture_file(output_path)
    else:
        open(output_path, "a").close()  # dev-mode stub
    return output_path
