#!/usr/bin/env python3
"""
GoPro downloader & combiner - FIXED
- Downloads the *latest* clip from each camera via the assigned WiFi interface
- Filenames: YYYY-MM-DD_HH:MM:SS_GoPro_1.MP4 / ..._GoPro_2.MP4
- Deletes the downloaded file from the GoPro after a successful download
- Starts a background concat job (GoPro1 then GoPro2) into ~/GoPro_Clips/Combined
"""

import asyncio
import json
import os
import shutil
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
from config import GOPRO_IP

GOPRO_BASE = "http://10.5.5.9:8080"
CLIPS_ROOT = Path.home() / "GoPro_Clips"
GOPRO1_DIR = CLIPS_ROOT / "GoPro1"
GOPRO2_DIR = CLIPS_ROOT / "GoPro2"
COMBINED_DIR = CLIPS_ROOT / "Combined"

# ---------- filesystem helpers ----------

def ensure_clip_dirs():
    CLIPS_ROOT.mkdir(parents=True, exist_ok=True)
    GOPRO1_DIR.mkdir(parents=True, exist_ok=True)
    GOPRO2_DIR.mkdir(parents=True, exist_ok=True)
    COMBINED_DIR.mkdir(parents=True, exist_ok=True)


def _out_path_for(cam_idx: int, when: Optional[datetime] = None) -> Path:
    ts = (when or datetime.now()).strftime("%Y-%m-%d_%H:%M:%S")
    name = f"{ts}_GoPro_{cam_idx}.MP4"
    if cam_idx == 1:
        return GOPRO1_DIR / name
    return GOPRO2_DIR / name


# ---------- GoPro HTTP helpers (via curl bound to interface) ----------

def _curl_iface(url: str, iface: str) -> Optional[str]:
    cmd = [
        "curl", "--interface", iface,
        "--connect-timeout", "5", "--max-time", "8",
        "-s", url
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout if res.returncode == 0 else None

async def _curl_json(url: str, interface: str, timeout: int = 10) -> Optional[dict]:
    proc = await asyncio.create_subprocess_exec(
        "curl", "--interface", interface, "--connect-timeout", "5", "--max-time", str(timeout),
        "-s", url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0 or not out:
        return None
    try:
        return json.loads(out.decode())
    except Exception:
        return None


async def _curl_file(url: str, interface: str, dest: Path, timeout: int = 0) -> Tuple[bool, float]:
    """
    Download to file using curl (interface-bound). Returns (success, seconds).
    If timeout=0, no max-time is set (large files).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["curl", "--interface", interface, "--connect-timeout", "5", "-L", "-sS", url, "-o", str(dest)]
    if timeout > 0:
        args += ["--max-time", str(timeout)]
    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    dt = time.time() - t0
    return (proc.returncode == 0 and dest.exists() and dest.stat().st_size > 0, dt)


async def _curl_simple(url: str, interface: str, timeout: int = 10) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "curl", "--interface", interface, "--connect-timeout", "5", "--max-time", str(timeout),
        "-s", url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, _ = await proc.communicate()
    return proc.returncode == 0


# ---------- media list / latest asset ----------

async def _get_latest_media_info(interface: str) -> Optional[Tuple[str, str]]:
    """
    Returns (folder, filename) for latest media on the camera attached to 'interface'.
    """
    media = await _curl_json(f"{GOPRO_BASE}/gp/gpMediaList", interface)
    if not media or "media" not in media or not media["media"]:
        return None

    # Flatten items: collect (folder, file, mod_time?, size?) and pick the newest
    newest = None
    newest_key = None
    for folder_entry in media["media"]:
        folder = folder_entry.get("d")
        files = folder_entry.get("fs", [])
        for f in files:
            name = f.get("n")
            # Prefer modification time 'mod' if present, else fallback to name (GH01xxxx.MP4 increases)
            mod = f.get("mod", 0)
            key = (mod, name)
            if newest is None or key > newest_key:
                newest = (folder, name)
                newest_key = key

    return newest


# ---------- delete a single asset on the camera ----------

async def _delete_asset_on_camera(interface: str, folder: str, filename: str) -> bool:
    """
    Use GoPro storage delete endpoint to remove a file *on the camera*.
    We try both known forms for better compatibility.
    """
    # Form 1 (older): /gp/gpControl/command/storage/delete?p=100GOPRO/GH010123.MP4
    p = f"{folder}/{filename}"
    url1 = f"{GOPRO_BASE}/gp/gpControl/command/storage/delete?p={shlex.quote(p)}"
    ok1 = await _curl_simple(url1, interface)

    # Form 2 (newer): /gp/gpControl/command/storage/delete/file?path=100GOPRO/GH010123.MP4
    if not ok1:
        url2 = f"{GOPRO_BASE}/gp/gpControl/command/storage/delete/file?path={shlex.quote(p)}"
        ok2 = await _curl_simple(url2, interface)
        return ok2
    return ok1


# ---------- public API ----------

async def download_latest_for_camera(camera_id: str, wifi_ctrl, cam_idx: int) -> Optional[Path]:
    """
    Downloads latest asset for a single camera to the proper folder.
    - wifi_ctrl must have .wifi_interface and .camera_name
    Returns the local Path or None.
    """
    iface = wifi_ctrl.wifi_interface
    cam_name = wifi_ctrl.camera_name

    latest = await _get_latest_media_info(iface)
    if not latest:
        print(f"[DL] {cam_name} → {iface}: No last asset found")
        return None

    folder, filename = latest
    url = f"{GOPRO_BASE}/videos/DCIM/{folder}/{filename}"

    # Output file path (timestamp from the Pi now)
    out_path = _out_path_for(cam_idx)
    print(f"[DL] {cam_name} → {iface}: {folder}/{filename} → {out_path.name}")

    ok, seconds = await _curl_file(url, iface, out_path)
    if not ok:
        print(f"[DL] {cam_name} → {iface}: DOWNLOAD FAILED")
        # Clean incomplete file if any
        try:
            if out_path.exists() and out_path.stat().st_size == 0:
                out_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    mb = out_path.stat().st_size / (1024 * 1024)
    print(f"[DL] {cam_name} → {iface}: DONE in {seconds:.1f}s ({mb:.1f} MB)")

    # Delete the file on the GoPro *after* a successful download
    deleted = await _delete_asset_on_camera(iface, folder, filename)
    if deleted:
        print(f"[DEL] {cam_name} → {iface}: Deleted {folder}/{filename} on camera")
    else:
        print(f"[DEL] {cam_name} → {iface}: Could not delete {folder}/{filename} on camera")

    return out_path


async def download_both_latest(wifi_controllers: Dict[str, object]) -> Dict[str, Optional[Path]]:
    """
    FIXED: Downloads latest clip from camera_1 and camera_2 concurrently.
    Returns dict: { 'camera_1': Path|None, 'camera_2': Path|None }
    """
    ensure_clip_dirs()

    # FIXED: Use individual tasks with camera IDs to avoid indexing confusion
    async def download_camera_1():
        c1 = wifi_controllers.get("camera_1")
        if c1:
            return await download_latest_for_camera("camera_1", c1, 1)
        else:
            print("[DL] camera_1 WiFi controller missing")
            return None
    
    async def download_camera_2():
        c2 = wifi_controllers.get("camera_2")
        if c2:
            return await download_latest_for_camera("camera_2", c2, 2)
        else:
            print("[DL] camera_2 WiFi controller missing")
            return None

    # Execute both downloads concurrently
    camera_1_result, camera_2_result = await asyncio.gather(
        download_camera_1(),
        download_camera_2()
    )

    # Return results with clear camera assignments
    return {
        "camera_1": camera_1_result,
        "camera_2": camera_2_result
    }

def get_latest_file_in_dir(directory: Path) -> Path:
    """Get the most recent file in a directory"""
    if not directory.exists():
        return None
    
    # Get all .MP4 files, sorted by modification time (newest first)
    video_files = list(directory.glob("*.MP4"))
    if not video_files:
        return None
    
    # Return the newest file
    return max(video_files, key=lambda f: f.stat().st_mtime)

def simple_concat_latest() -> Path:
    """
    Simple concatenation: Get latest file from each camera directory and combine them
    """
    # Ensure directories exist
    COMBINED_DIR.mkdir(parents=True, exist_ok=True)
    
    # Get latest files
    cam1_file = get_latest_file_in_dir(GOPRO1_DIR)
    cam2_file = get_latest_file_in_dir(GOPRO2_DIR)
    
    print(f"[SIMPLE] Camera 1 latest: {cam1_file.name if cam1_file else 'None'}")
    print(f"[SIMPLE] Camera 2 latest: {cam2_file.name if cam2_file else 'None'}")
    
    if not cam1_file or not cam2_file:
        print("[SIMPLE] Missing files - cannot combine")
        return None
    
    # Create output filename
    ts = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
    out_path = COMBINED_DIR / f"{ts}_Combined.mp4"
    
    # Create concat file
    listfile = CLIPS_ROOT / f"simple_concat_{ts}.txt"
    with open(listfile, "w") as f:
        f.write(f"file '{cam1_file.as_posix()}'\n")
        f.write(f"file '{cam2_file.as_posix()}'\n")
    
    print(f"[SIMPLE] Combining: {cam1_file.name} + {cam2_file.name}")
    print(f"[SIMPLE] Output: {out_path.name}")
    
    # Run ffmpeg in background
    cmd = [
        "ffmpeg",
        "-loglevel", "error", 
        "-hide_banner",
        "-y",
        "-f", "concat",
        "-safe", "0", 
        "-i", str(listfile),
        "-c", "copy",
        str(out_path)
    ]
    
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    print(f"[SIMPLE] Started background concat → {out_path.name}")
    return out_path


def start_concat_background(path_cam1: Path, path_cam2: Path) -> Optional[Path]:
    """
    Start a *background* ffmpeg concat (GoPro1 first, then GoPro2) using -c copy (fast).
    Returns output path (even though the job continues in background).
    """
    try:
        ensure_clip_dirs()
        ts = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
        out_path = COMBINED_DIR / f"{ts}_Combined.mp4"

        # Build a concat list file
        listfile = CLIPS_ROOT / f"concat_{ts}.txt"
        with open(listfile, "w") as f:
            # Use absolute paths, -safe 0
            # GoPro1 first, then GoPro2
            f.write(f"file '{path_cam1.as_posix()}'\n")
            f.write(f"file '{path_cam2.as_posix()}'\n")

        # Launch background process (no shell), no colors/style set, and disown
        cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-hide_banner",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(listfile),
            "-c", "copy",
            str(out_path),
        ]
        # Start without waiting (background)
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        print(f"[COMBINE] Started background concat → {out_path.name}")
        print(f"[COMBINE] Order: {path_cam1.name} + {path_cam2.name}")
        return out_path
    except Exception as e:
        print(f"[COMBINE] Could not start concat: {e}")
        return None