#!/usr/bin/env python3
"""
GoPro clip downloader + background combiner

- Ensures folders:
    /home/pi/GoPro_Clips/
        GoPro1/
        GoPro2/
        Combined/
- Downloads the latest clip from each camera via its Wi‑Fi interface (curl bound to iface)
- Starts an ffmpeg background process to combine two clips (side-by-side) into Combined/
"""

import asyncio
import json
import os
import shutil
import subprocess
import time
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

# ---- Folders ----
BASE = Path("/home/pi/GoPro_Clips")
DIR_G1 = BASE / "GoPro1"
DIR_G2 = BASE / "GoPro2"
DIR_COMBINED = BASE / "Combined"

def ensure_dirs():
    for d in (BASE, DIR_G1, DIR_G2, DIR_COMBINED):
        d.mkdir(parents=True, exist_ok=True)

def _sanitize(name: str) -> str:
    # filesystem-friendly camera name (no spaces/slashes)
    keep = "-_.()abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(c if c in keep else "_" for c in (name or "GoPro"))

# ---- Helpers to query last clip ----
def _curl_json(url: str, interface: str, timeout: int = 10) -> Optional[dict]:
    try:
        cmd = [
            "curl", "--interface", interface, "--connect-timeout", "5",
            "--max-time", str(timeout), "-s", url
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout)
    except Exception:
        pass
    return None

def _curl_file(url: str, interface: str, out_path: Path, timeout: int = 0) -> bool:
    # timeout=0 -> no max-time so large files aren’t aborted
    cmd = [
        "curl", "--interface", interface, "--connect-timeout", "5",
        "-L", "-s", url, "-o", str(out_path)
    ]
    if timeout > 0:
        cmd[4:4] = ["--max-time", str(timeout)]
    try:
        res = subprocess.run(cmd)
        return res.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False

def _build_media_url(ip: str, folder: str, filename: str) -> str:
    # Standard GoPro layout: /videos/DCIM/<FOLDER>/<FILE>
    return f"http://{ip}:8080/videos/DCIM/{folder}/{filename}"

def _pick_newest_mp4_from_media_json(data) -> Optional[Tuple[str, str]]:
    """
    Accepts either modern {'media':[{'d': '100GOPRO','fs':[{'n': 'GX...MP4','mod': 171...}, ...]}]}
    or any similar variant. Returns (folder, filename) of the newest MP4.
    """
    if not data:
        return None

    media = data.get("media") or data.get("Media") or []
    newest = None

    for entry in media:
        folder = entry.get("d") or entry.get("folder") or entry.get("name")
        files = entry.get("fs") or entry.get("files") or []
        for f in files:
            # name variants
            name = f.get("n") or f.get("name") or f.get("file") or ""
            if not name or not name.lower().endswith(".mp4"):
                continue

            # timestamp-ish variants
            mod = f.get("mod") or f.get("cre") or f.get("t") or 0
            # Some firmwares return ISO strings; some return int secs
            try:
                stamp = int(mod)
            except Exception:
                stamp = 0

            # fallback to parsing incrementing index from filename (GH/GX/GOPR digits)
            if stamp == 0:
                m = re.search(r'(\d{4,})', name)
                stamp = int(m.group(1)) if m else 0

            if newest is None or stamp > newest[0]:
                newest = (stamp, folder, name)

    if newest:
        _, folder, name = newest
        return folder, name
    return None

def _get_last_asset(ip: str, interface: str, retries: int = 5, initial_delay: float = 1.2) -> Optional[Tuple[str, str]]:
    """
    Be patient and robust:
      1) wait a bit, then try /gopro/media/last_captured
      2) fall back to /gopro/media/list
      3) fall back to /gp/gpMediaList
    Do this with a few retries because Camera 1 may need time to finalize the clip.
    """
    delay = initial_delay
    debug = os.environ.get("DL_DEBUG") == "1"

    for attempt in range(1, retries + 1):
        # 1) modern last_captured
        data = _curl_json(f"http://{ip}:8080/gopro/media/last_captured", interface)
        if debug and data:
            print(f"[DLDBG] last_captured attempt {attempt}: {data}")

        if data:
            asset = data.get("asset") or data.get("media") or {}
            folder = asset.get("folder") or asset.get("d")
            filename = asset.get("filename") or asset.get("n")
            if folder and filename and filename.lower().endswith(".mp4"):
                return folder, filename

        # 2) modern list
        data = _curl_json(f"http://{ip}:8080/gopro/media/list", interface)
        if not data:
            # 3) legacy list
            data = _curl_json(f"http://{ip}:8080/gp/gpMediaList", interface)

        if debug and data:
            print(f"[DLDBG] media list attempt {attempt}: keys={list(data.keys())}")

        pick = _pick_newest_mp4_from_media_json(data)
        if pick:
            return pick

        # Wait a bit more and retry
        time.sleep(delay)
        delay *= 1.5

    return None

# ---- Public API ----

async def download_latest_clip(camera_name: str, interface: str, ip: str, dest_dir: Path) -> Optional[Path]:
    """
    Fetch latest clip JSON → build URL → download to dest_dir with timestamp+camera name.
    Prints size and elapsed time. Returns the local file path, or None on failure.
    """
    ensure_dirs()

    # Give the camera a moment to finalize the file if we were just recording
    asset = _get_last_asset(ip, interface, retries=6, initial_delay=1.0)
    if not asset:
        print(f"[DL] {camera_name}: No last asset found")
        return None

    folder, filename = asset
    url = _build_media_url(ip, folder, filename)
    #ts = time.strftime("%Y%m%d_%H%M%S")
    ts = time.strftime("%Y-%m-%d_%H:%M:%S")
    # Build a nice, informative filename
    #safe_cam = camera_name.replace(" ", "_").replace("/", "_")
    #out = dest_dir / f"{ts}_{safe_cam}_{filename}"
    cam_tag = camera_name.split()[0] + "_" + camera_name.split()[1]  # e.g. "GoPro_2"
    out = dest_dir / f"{ts}_{cam_tag}.MP4"

    print(f"[DL] {camera_name}: {folder}/{filename} → {out.name}")

    # Time the download
    t0 = time.perf_counter()
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, _curl_file, url, interface, out, 0)
    dt = time.perf_counter() - t0

    if ok and out.exists() and out.stat().st_size > 0:
        mb = out.stat().st_size / 1e6
        print(f"[DL] {camera_name}: DONE in {dt:.1f}s ({mb:.1f} MB)")
        return out
    else:
        print(f"[DL] {camera_name}: FAILED after {dt:.1f}s")
        try:
            if out.exists():
                out.unlink()
        except Exception:
            pass
        return None

async def download_both_latest(wifi_controllers: Dict[str, object]) -> Dict[str, Optional[Path]]:
    """
    Launch two downloads concurrently for camera_1 and camera_2 (if present).
    Returns: {"camera_1": path_or_None, "camera_2": path_or_None}
    """
    ensure_dirs()

    async def maybe_add(camera_id: str, dest: Path):
        wc = wifi_controllers.get(camera_id)
        if wc:
            return await download_latest_clip(wc.camera_name, wc.wifi_interface, wc.ip, dest)
        return None

    results: Dict[str, Optional[Path]] = {"camera_1": None, "camera_2": None}
    r1 = asyncio.create_task(maybe_add("camera_1", DIR_G1))
    r2 = asyncio.create_task(maybe_add("camera_2", DIR_G2))
    results["camera_1"], results["camera_2"] = await asyncio.gather(r1, r2)
    return results

def combine_side_by_side_background(left: Path, right: Path, out_dir: Path = DIR_COMBINED) -> Optional[Path]:
    """
    Spawn an ffmpeg process (background) that stacks the two clips horizontally.
    - Scales right video to the height of left (keeps aspect) to avoid size mismatch.
    - Writes stderr to a log file for debugging.
    Returns output path (immediately), or None if spawn fails/prereqs missing.
    """
    ensure_dirs()

    if not left or not right:
        print("[FFMPEG] Skipped combine: need two clips")
        return None
    if not left.exists() or not right.exists():
        print(f"[FFMPEG] Skipped combine: file missing ({left} / {right})")
        return None

    if shutil.which("ffmpeg") is None:
        print("[FFMPEG] Not installed: sudo apt-get install -y ffmpeg")
        return None

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{ts}_combined.mp4"
    log_path = out_dir / f"{ts}_ffmpeg.log"

    # Scale right to match left's height, then hstack
    filter_str = (
        "[1:v]scale2ref=oh=ih:ow=iw[rs][ref];"
        "[0:v][rs]hstack=inputs=2[v]"
    )

    try:
        proc = subprocess.Popen([
            "ffmpeg",
            "-y",
            "-i", str(left),
            "-i", str(right),
            "-filter_complex", filter_str,
            "-map", "[v]",
            "-map", "0:a?",
            "-map", "1:a?",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-shortest",
            str(out_path)
        ], stdout=subprocess.DEVNULL, stderr=open(log_path, "w"))
        print(f"[FFMPEG] Combining in background (pid {proc.pid}) → {out_path}")
        print(f"[FFMPEG] Log: {log_path}")
        return out_path
    except Exception as e:
        print(f"[FFMPEG] Spawn failed: {e}")
        return None
