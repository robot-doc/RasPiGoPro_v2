#!/usr/bin/env python3
"""
Main entry point for Dual WiFi Interface GoPro Controller
- Unified trigger system (Manual / I²C) with single-key exit
- BUSY output asserted while recording and while concat is running
"""

import asyncio
import select
import logging
import sys
import os
import time
import subprocess
import termios
import tty

# Only import signal on Unix-like systems where it's available
try:
    import signal
    HAS_SIGNAL = True
except ImportError:
    HAS_SIGNAL = False

from config import (
    SLEEP_MENU, SHOW_DEBUGGING_INFO,
    I2C_BUS, PCF8574_INPUT_ADDRESSES, PCF8574_POLL_INTERVAL,
    TRIGGER_INPUT, RECORDING_TIME,
    PCF8574_OUTPUT_ADDRESSES, PCF8574_OUTPUT_ACTIVE_LOW, BUSY_OUTPUT_PIN
)

from dual_wifi_manager import DualWiFiGoProManager
from gopro_downloader import ensure_clip_dirs, download_both_latest, start_concat_background
import rtc_manager
from pcf8574_manager import PCF8574Manager

logger = logging.getLogger(__name__)


class GoProControllerUI:
    """User interface for the GoPro controller"""

    def __init__(self):
        self.manager = DualWiFiGoProManager()
        self.shutdown_requested = False

        # PCF8574 I/O (inputs + outputs)
        try:
            self.io_manager = PCF8574Manager(
                I2C_BUS,
                PCF8574_INPUT_ADDRESSES,
                PCF8574_OUTPUT_ADDRESSES,
                PCF8574_OUTPUT_ACTIVE_LOW,
            )
        except Exception:
            self.io_manager = None

        # Persisted trigger mode from config (manual | i2c)
        self.trigger_mode = self.manager.config.get("trigger_mode", "manual")

    # ---------- terminal helpers ----------

    def reset_terminal(self):
        """Completely reset terminal state"""
        try:
            subprocess.run(["stty", "sane"], check=False, stderr=subprocess.DEVNULL)
            print("\033c", end="")           # Full reset
            print("\033[H\033[2J", end="")   # Clear + home
            print("\033[0m", end="")         # Reset attrs
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            print("\n" * 50)

    def print_clean(self, text: str = ""):
        print(text)
        sys.stdout.flush()

    def get_input_clean(self, prompt: str) -> str:
        sys.stdout.write(prompt)
        sys.stdout.flush()
        try:
            return input().strip()
        except (EOFError, KeyboardInterrupt):
            return "0"

    # ---------- small persistence helpers ----------

    def _save_trigger_mode(self):
        """Persist trigger mode in the shared config file."""
        try:
            self.manager.config["trigger_mode"] = self.trigger_mode
            self.manager.save_config()
        except Exception:
            pass

    def _trigger_mode_label(self) -> str:
        return "Manual" if self.trigger_mode == "manual" else f"I²C (P{TRIGGER_INPUT})"

    # ---------- PCF8574 output (BUSY) ----------

    def _set_busy_output(self, state: bool):
        """Set BUSY output pin on first PCF8574 output board, if available."""
        try:
            if self.io_manager and getattr(self.io_manager, "output_devices", None):
                self.io_manager.set_output_pin(0, BUSY_OUTPUT_PIN, state)
        except Exception:
            pass

    # ---------- camera controls (per camera via Wi‑Fi menu) ----------

    def control_camera_wifi(self, camera_id: str):
        """Control individual camera via WiFi with enhanced debugging"""
        if camera_id not in self.manager.wifi_controllers:
            self.print_clean(f"\nX WiFi not connected to camera {camera_id}")
            self.print_clean("[HELP] Use option 91 or 31/32 to connect WiFi first")
            self.print_clean(f"[CONFIG] Available WiFi controllers: {list(self.manager.wifi_controllers.keys())}")
            self.get_input_clean("\nPress Enter to continue...")
            return

        camera = self.manager.cameras[camera_id]
        wifi_ctrl = self.manager.wifi_controllers[camera_id]

        while True:
            self.reset_terminal()

            self.print_clean("=" * 60)
            self.print_clean(f"    CAMERA WIFI CONTROL: {camera.camera_name}")
            self.print_clean("=" * 60)
            self.print_clean(f"Interface: {wifi_ctrl.wifi_interface}")
            self.print_clean(f"Interface IP: {wifi_ctrl.interface_ip}")
            self.print_clean("")
            self.print_clean("1. Take photo")
            self.print_clean("2. Start recording")
            self.print_clean("3. Stop recording")
            self.print_clean("4. Get status")
            self.print_clean("5. Test connection")
            self.print_clean("0. Back to main menu")
            self.print_clean("")

            choice = self.get_input_clean("Choice: ")

            if choice == "1":
                self.print_clean(f"\n[PHOTO] Taking photo on {camera.camera_name}...")
                if wifi_ctrl.take_photo():
                    self.print_clean("[OK] Photo command sent!")
                else:
                    self.print_clean("X Photo command failed")
                if SHOW_DEBUGGING_INFO == "ON":
                    self.get_input_clean("\nPress Enter to continue...")

            elif choice == "2":
                self.print_clean(f"\n[REC] Starting recording on {camera.camera_name}...")
                if wifi_ctrl.start_recording():
                    self.print_clean("[OK] Recording started!")
                else:
                    self.print_clean("X Recording start failed")
                if SHOW_DEBUGGING_INFO == "ON":
                    self.get_input_clean("\nPress Enter to continue...")

            elif choice == "3":
                self.print_clean(f"\n[STOP] Stopping recording on {camera.camera_name}...")
                if wifi_ctrl.stop_recording():
                    self.print_clean("[OK] Recording stopped!")
                else:
                    self.print_clean("X Recording stop failed")
                if SHOW_DEBUGGING_INFO == "ON":
                    self.get_input_clean("\nPress Enter to continue...")

            elif choice == "4":
                self.print_clean(f"\n[STATUS] Getting status from {camera.camera_name}...")
                status = wifi_ctrl.get_status()
                if status:
                    battery = status.get("status", {}).get("70", "Unknown")
                    recording = status.get("status", {}).get("8", 0)
                    mode = status.get("status", {}).get("43", "Unknown")
                    self.print_clean(f"[BATTERY] Battery: {battery}%")
                    self.print_clean(f"[REC] Recording: {'Yes' if recording else 'No'}")
                    self.print_clean(f"[MODE] Mode: {mode}")
                else:
                    self.print_clean("X No status received")
                self.get_input_clean("\nPress Enter to continue...")

            elif choice == "5":
                self.print_clean(f"\n[CHECK] Testing connection to {camera.camera_name}...")
                if wifi_ctrl.test_connection():
                    self.print_clean("[OK] Connection test passed!")
                else:
                    self.print_clean("X Connection test failed")
                self.get_input_clean("\nPress Enter to continue...")

            elif choice == "0":
                break
            else:
                self.print_clean("Invalid choice. Please try again.")
                time.sleep(1)

    # ---------- async Wi‑Fi HTTP helpers ----------

    async def async_curl_request(self, url: str, interface: str) -> bool:
        """Make async HTTP request using asyncio subprocess for parallelism"""
        try:
            curl_cmd = [
                "curl",
                "--interface",
                interface,
                "--connect-timeout",
                "5",
                "--max-time",
                "10",
                "-s",
                url,
            ]
            process = await asyncio.create_subprocess_exec(
                *curl_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, _ = await process.communicate()
            return process.returncode == 0
        except Exception as e:
            self.print_clean(f"[CURL ERROR] {e}")
            return False

    # ---------- multi-camera actions ----------

    async def start_recording_all_cameras(self) -> int:
        """Start recording on ALL cameras SIMULTANEOUSLY via Wi‑Fi"""
        if not self.manager.wifi_controllers:
            self.print_clean("[ERROR] No WiFi controllers available! Use option 91 first.")
            return 0

        self.print_clean(f"[MILLISECOND] Starting recording on {len(self.manager.wifi_controllers)} cameras...")

        async def start_single_wifi_async(camera_id, wifi_ctrl):
            try:
                self.print_clean(f"[START] {wifi_ctrl.camera_name} via {wifi_ctrl.wifi_interface}...")
                mode_url = f"http://{wifi_ctrl.ip}:8080/gp/gpControl/command/mode?p=0"
                if not await self.async_curl_request(mode_url, wifi_ctrl.wifi_interface):
                    self.print_clean(f"[FAIL] {wifi_ctrl.camera_name} mode setting failed")
                    return 0
                await asyncio.sleep(0.5)
                record_url = f"http://{wifi_ctrl.ip}:8080/gp/gpControl/command/shutter?p=1"
                if await self.async_curl_request(record_url, wifi_ctrl.wifi_interface):
                    self.print_clean(f"[OK] {wifi_ctrl.camera_name} RECORDING")
                    return 1
                self.print_clean(f"[FAIL] {wifi_ctrl.camera_name} recording failed")
                return 0
            except Exception as e:
                self.print_clean(f"[ERROR] {wifi_ctrl.camera_name}: {e}")
                return 0

        tasks = [start_single_wifi_async(cid, w) for cid, w in self.manager.wifi_controllers.items()]
        results = await asyncio.gather(*tasks)
        return sum(results)

    async def stop_recording_all_cameras(self) -> int:
        """Stop recording on ALL cameras SIMULTANEOUSLY via Wi‑Fi"""
        if not self.manager.wifi_controllers:
            self.print_clean("[ERROR] No WiFi controllers available!")
            return 0

        self.print_clean(f"[MILLISECOND] Stopping recording on {len(self.manager.wifi_controllers)} cameras...")

        async def stop_single_wifi_async(camera_id, wifi_ctrl):
            try:
                self.print_clean(f"[STOP] {wifi_ctrl.camera_name} via {wifi_ctrl.wifi_interface}...")
                stop_url = f"http://{wifi_ctrl.ip}:8080/gp/gpControl/command/shutter?p=0"
                if await self.async_curl_request(stop_url, wifi_ctrl.wifi_interface):
                    self.print_clean(f"[OK] {wifi_ctrl.camera_name} STOPPED")
                    return 1
                self.print_clean(f"[FAIL] {wifi_ctrl.camera_name} failed")
                return 0
            except Exception as e:
                self.print_clean(f"[ERROR] {wifi_ctrl.camera_name}: {e}")
                return 0

        tasks = [stop_single_wifi_async(cid, w) for cid, w in self.manager.wifi_controllers.items()]
        results = await asyncio.gather(*tasks)
        return sum(results)

    async def take_photos_all_cameras(self) -> int:
        """Take photos on ALL cameras SIMULTANEOUSLY via Wi‑Fi"""
        if not self.manager.wifi_controllers:
            self.print_clean("[ERROR] No WiFi controllers available! Use option 91 first.")
            return 0

        self.print_clean(f"[MILLISECOND] Taking photos on {len(self.manager.wifi_controllers)} cameras...")

        async def photo_single_wifi_async(camera_id, wifi_ctrl):
            try:
                self.print_clean(f"[PHOTO] {wifi_ctrl.camera_name} via {wifi_ctrl.wifi_interface}...")
                mode_url = f"http://{wifi_ctrl.ip}:8080/gp/gpControl/command/mode?p=1"
                if not await self.async_curl_request(mode_url, wifi_ctrl.wifi_interface):
                    self.print_clean(f"[FAIL] {wifi_ctrl.camera_name} mode setting failed")
                    return 0
                await asyncio.sleep(0.5)
                photo_url = f"http://{wifi_ctrl.ip}:8080/gp/gpControl/command/shutter?p=1"
                if await self.async_curl_request(photo_url, wifi_ctrl.wifi_interface):
                    self.print_clean(f"[OK] {wifi_ctrl.camera_name} PHOTO TAKEN")
                    return 1
                self.print_clean(f"[FAIL] {wifi_ctrl.camera_name} failed")
                return 0
            except Exception as e:
                self.print_clean(f"[ERROR] {wifi_ctrl.camera_name}: {e}")
                return 0

        tasks = [photo_single_wifi_async(cid, w) for cid, w in self.manager.wifi_controllers.items()]
        results = await asyncio.gather(*tasks)
        return sum(results)

    # ---------- timed recording (menu 90 → 2) ----------

    async def timed_recording_all_cameras(self):
        """Start both cameras, record for configured time, then stop.
        Trigger source is selected by menu item 5 (Manual / I²C).
        BUSY output stays TRUE during recording and while concat is running.
        """
        if not self.manager.wifi_controllers:
            self.print_clean("[ERROR] No WiFi controllers available! Use option 91 first.")
            self.get_input_clean("\nPress Enter to continue...")
            return

        self.print_clean(f"\n[ARMED] Timed recording mode ({RECORDING_TIME:.1f}s)")
        self.print_clean(f"[MODE] Trigger mode: {self._trigger_mode_label()}")
        self.print_clean("")

        while True:
            # Wait for trigger (manual or I²C)
            if not await self._wait_for_trigger():
                self.print_clean("[EXIT] Exiting recording mode...")
                return

            # BUSY ON
            self._set_busy_output(True)

            try:
                started = await self.start_recording_all_cameras()
                if started == 0:
                    self.print_clean("[FAIL] No cameras started recording.")
                    self._set_busy_output(False)
                    continue

                self.print_clean(f"[RUNNING] Recording for {RECORDING_TIME:.1f}s...")
                await asyncio.sleep(RECORDING_TIME)

                await self.stop_recording_all_cameras()
                await asyncio.sleep(2)

                # Download + concat
                self.print_clean("[DL] Fetching latest clips from cameras...")
                downloads = await download_both_latest(self.manager.wifi_controllers)

                cam1_path = downloads.get("camera_1")
                cam2_path = downloads.get("camera_2")

                if cam1_path and cam2_path:
                    out_path = start_concat_background(cam1_path, cam2_path)
                    if out_path:
                        self.print_clean("[COMBINE] Waiting for combine to finish...")
                        try:
                            await self._wait_for_concat(out_path)
                        except Exception:
                            await asyncio.sleep(2.0)
                    else:
                        self.print_clean("[COMBINE] Could not start concat.")
                else:
                    missing = []
                    if not cam1_path:
                        missing.append("camera_1")
                    if not cam2_path:
                        missing.append("camera_2")
                    self.print_clean(f"[COMBINE] Skipped: missing downloads from {', '.join(missing)}")

            finally:
                # BUSY OFF (after recording + concat wait)
                self._set_busy_output(False)

            self.print_clean("[READY] Ready for next trigger...\n")

    async def _wait_for_concat(self, out_path):
        """Wait until the background ffmpeg that writes out_path finishes."""
        pattern = f"ffmpeg.*{out_path.name}"
        while True:
            proc = await asyncio.create_subprocess_exec(
                "pgrep", "-f", pattern,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, _ = await proc.communicate()
            if proc.returncode != 0:  # no process found
                break
            await asyncio.sleep(0.5)

    # ---------- unified trigger (manual + I²C) with single-key 'q' exit ----------

    async def _wait_for_trigger(self) -> bool:
        """
        Unified trigger: supports 'manual' and 'i2c' modes with single-key exit.
        Returns True to trigger, False to exit.
        """

        def _enter_cbreak():
            use_single_key = False
            old_settings = None
            fd = None
            if sys.stdin.isatty():
                try:
                    fd = sys.stdin.fileno()
                    old_settings = termios.tcgetattr(fd)
                    tty.setcbreak(fd)  # single-key without Enter
                    use_single_key = True
                except Exception:
                    use_single_key = False
            return use_single_key, old_settings, fd

        def _leave_cbreak(use_single_key, old_settings, fd):
            if use_single_key and old_settings is not None and fd is not None:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                except Exception:
                    pass

        # Manual mode: Enter triggers; 'q' exits
        if self.trigger_mode == "manual":
            self.print_clean("[INFO] Press Enter to TRIGGER. Press 'q' to return to the previous menu.")
            use_single_key, old_settings, fd = _enter_cbreak()
            try:
                if use_single_key:
                    while True:
                        r, _, _ = select.select([sys.stdin], [], [], 0.05)
                        if r:
                            ch = os.read(fd, 1)
                            if ch in (b"\n", b"\r"):
                                return True
                            if ch in (b"q", b"Q"):
                                self.print_clean("[EXIT] Returning to previous menu.")
                                return False
                        await asyncio.sleep(0.05)
                else:
                    user_input = self.get_input_clean("Press Enter to TRIGGER (or 'q' to quit): ")
                    return user_input.lower() not in ["q", "quit", "exit"]
            finally:
                _leave_cbreak(use_single_key, old_settings, fd)

        # I²C trigger mode
        if self.io_manager is None:
            self.print_clean("[IO] PCF8574 not available; falling back to manual trigger.")
            user_input = self.get_input_clean("Press Enter to TRIGGER (or 'q' to quit): ")
            return user_input.lower() not in ["q", "quit", "exit"]

        self.print_clean(f"[WAIT] Waiting for I²C trigger on P{TRIGGER_INPUT} (active LOW)...")
        self.print_clean("[INFO] Press 'q' to return to the previous menu.")

        stable_low = 0
        required_stable = 2
        use_single_key, old_settings, fd = _enter_cbreak()
        try:
            while True:
                # quit?
                if use_single_key:
                    r, _, _ = select.select([sys.stdin], [], [], 0)
                    if r:
                        ch = os.read(fd, 1)
                        if ch in (b"q", b"Q"):
                            self.print_clean("[EXIT] Returning to previous menu.")
                            return False
                else:
                    r, _, _ = select.select([sys.stdin], [], [], 0)
                    if r:
                        line = sys.stdin.readline().strip().lower()
                        if line in ("q", "quit", "exit"):
                            self.print_clean("[EXIT] Returning to previous menu.")
                            return False

                snapshot = self.io_manager.snapshot_inputs()
                pins = next(iter(snapshot.values()), None)
                if pins is None:
                    await asyncio.sleep(PCF8574_POLL_INTERVAL)
                    continue

                level = pins.get(TRIGGER_INPUT, 1)
                if level == 0:
                    stable_low += 1
                    if stable_low >= required_stable:
                        self.print_clean("[TRIGGER] I²C input asserted!")
                        return True
                else:
                    stable_low = 0

                await asyncio.sleep(PCF8574_POLL_INTERVAL)
        finally:
            _leave_cbreak(use_single_key, old_settings, fd)

    # ---------- simultaneous control menu (90) ----------

    async def simultaneous_control(self):
        """Control multiple cameras simultaneously"""
        if len(self.manager.cameras) < 2:
            self.print_clean("X Need at least 2 cameras for simultaneous control")
            self.get_input_clean("\nPress Enter to continue...")
            return

        while True:
            self.reset_terminal()

            self.print_clean("=" * 60)
            self.print_clean(f"    SIMULTANEOUS CONTROL - {len(self.manager.cameras)} Cameras")
            self.print_clean("=" * 60)
            self.print_clean("")
            self.print_clean("1. Take photos on ALL cameras")
            self.print_clean("2. Timed recording on ALL cameras (uses selected trigger)")
            self.print_clean("3. Stop recording on ALL cameras")
            self.print_clean("4. Enable WiFi on ALL cameras")
            self.print_clean(f"5. Trigger mode: {self._trigger_mode_label()}")
            self.print_clean("6. Delete ALL media on ONE camera")
            self.print_clean("0. Back to main menu")
            self.print_clean("")

            choice = self.get_input_clean("Choice: ")

            if choice == "1":
                self.print_clean("[PHOTO] Taking photos on all cameras...")
                success_count = await self.take_photos_all_cameras()
                time.sleep(SLEEP_MENU)
                if SHOW_DEBUGGING_INFO == "ON":
                    self.print_clean(f"[RESULT] {success_count}/{len(self.manager.cameras)} photos taken")
                    self.get_input_clean("\nPress Enter to continue...")

            elif choice == "2":
                await self.timed_recording_all_cameras()

            elif choice == "3":
                self.print_clean("[STOP] Stopping recording on all cameras...")
                success_count = await self.stop_recording_all_cameras()
                time.sleep(SLEEP_MENU)
                if SHOW_DEBUGGING_INFO == "ON":
                    self.print_clean(f"[RESULT] {success_count}/{len(self.manager.cameras)} cameras stopped")
                    self.get_input_clean("\nPress Enter to continue...")

            elif choice == "4":
                self.print_clean("[WIFI] Enabling WiFi on all cameras...")
                tasks = [camera.enable_wifi() for camera in self.manager.cameras.values()]
                results = await asyncio.gather(*tasks)
                success_count = sum(results)
                time.sleep(SLEEP_MENU)
                if SHOW_DEBUGGING_INFO == "ON":
                    self.print_clean(f"[OK] {success_count}/{len(self.manager.cameras)} WiFi enabled")
                    self.get_input_clean("\nPress Enter to continue...")

            elif choice == "5":
                # Toggle between manual and i2c, persist to config
                self.trigger_mode = "i2c" if self.trigger_mode == "manual" else "manual"
                self._save_trigger_mode()
                self.print_clean(f"[MODE] Trigger mode set to: {self._trigger_mode_label()}")
                time.sleep(1)

            elif choice == "6":
                # Choose which camera to wipe
                self.reset_terminal()
                self.print_clean("=" * 60)
                self.print_clean("    DELETE ALL MEDIA (Single Camera)")
                self.print_clean("=" * 60)
                if not self.manager.wifi_controllers:
                    self.print_clean("\n[ERROR] No WiFi controllers available. Use 91 to connect first.")
                    self.get_input_clean("\nPress Enter to continue...")
                    continue

                # Build numbered list
                camera_list = list(self.manager.cameras.items())
                self.print_clean("\nSelect camera to erase:")
                choices = []
                for idx, (cam_id, cam) in enumerate(camera_list, start=1):
                    wifi_ok = "WIFI" if cam_id in self.manager.wifi_controllers else "X"
                    self.print_clean(f"  {idx}. {cam.camera_name} [{wifi_ok}]")
                    choices.append((idx, cam_id, cam))

                sel = self.get_input_clean("\nCamera number (or 0 to cancel): ")
                try:
                    n = int(sel)
                except ValueError:
                    self.print_clean("Invalid input.")
                    time.sleep(1)
                    continue
                if n == 0:
                    continue
                if not (1 <= n <= len(choices)):
                    self.print_clean("Invalid selection.")
                    time.sleep(1)
                    continue

                _, cam_id, cam = choices[n - 1]
                if cam_id not in self.manager.wifi_controllers:
                    self.print_clean("\n[ERROR] Selected camera is not connected over WiFi.")
                    self.get_input_clean("\nPress Enter to continue...")
                    continue

                # Safety confirmation
                self.print_clean(f"\n!!! WARNING !!! This will ERASE ALL media on {cam.camera_name}.")
                confirm = self.get_input_clean("Type 'ERASE' to proceed, or anything else to cancel: ")
                if confirm != "ERASE":
                    self.print_clean("Cancelled.")
                    time.sleep(1)
                    continue

                wifi_ctrl = self.manager.wifi_controllers[cam_id]
                self.print_clean(f"\n[DELETE] Sending erase command to {cam.camera_name}...")
                ok = wifi_ctrl.delete_all_media()
                if ok:
                    self.print_clean("[OK] Camera acknowledged delete-all request.")
                else:
                    self.print_clean("X Delete-all request failed (check WiFi connection).")
                self.get_input_clean("\nPress Enter to continue...")

            elif choice == "0":
                break
            else:
                self.print_clean("Invalid choice. Please try again.")
                time.sleep(1)

    # ---------- main menu & helpers ----------

    def show_main_menu(self):
        """Display the main menu"""
        self.reset_terminal()

        camera_list = list(self.manager.cameras.items())

        self.print_clean("=" * 60)
        self.print_clean("    DUAL WIFI GOPRO CONTROLLER")
        self.print_clean("=" * 60)
        self.print_clean("")

        # Show camera status
        self.print_clean("Connected Cameras:")
        if camera_list:
            for i, (camera_id, camera) in enumerate(camera_list, 1):
                bt_status = "BT" if camera.connected else "X"
                wifi_status = "WIFI" if camera_id in self.manager.wifi_controllers else "X"
                cam_num = "3811" if "3811" in camera.camera_name else "4511"
                interface = camera.wifi_interface
                self.print_clean(f"  {i}. GoPro {cam_num} [{bt_status}] [{wifi_status}] {interface}")
        else:
            self.print_clean("  No cameras connected")

        self.print_clean("")
        menu_items = [
            ("21. Control Camera 1", "31. Connect Camera 1 WiFi"),
            ("22. Control Camera 2", "32. Connect Camera 2 WiFi"),
            ("80. I/O (PCF8574) status", ""),
            ("90. Simultaneous control", "91. AUTO: WiFi setup"),
            ("92. Add new camera", "93. Show config"),
            ("94. Network debug", "95. WiFi debug"),
            ("96. Manual WiFi enable", "0. Exit / 00. Force Exit"),
        ]

        self.print_clean("Main Menu:")
        for left, right in menu_items:
            if right:
                self.print_clean(f"  {left:<30} {right}")
            else:
                self.print_clean(f"  {left}")

        self.print_clean("=" * 60)

    def show_pcf8574_menu(self):
        """Submenu to view PCF8574 input status."""
        if self.io_manager is None:
            self.print_clean("\n[IO] PCF8574 manager not available (missing smbus2 or init error).")
            self.get_input_clean("\nPress Enter to continue...")
            return

        while True:
            self.reset_terminal()
            self.print_clean("=" * 60)
            self.print_clean("    PCF8574 INPUT STATUS")
            self.print_clean("=" * 60)
            self.print_clean("")
            self.print_clean("1. Snapshot (read once)")
            self.print_clean("2. Live view (press 'q' + Enter to exit)")
            self.print_clean("0. Back to main menu")
            self.print_clean("")

            choice = self.get_input_clean("Choice: ")

            if choice == "1":
                self.reset_terminal()
                self.print_clean("PCF8574 Snapshot:\n")
                data = self.io_manager.snapshot_inputs()
                for dev_name, pins in data.items():
                    if pins is None:
                        self.print_clean(f"{dev_name}: X read failed")
                    else:
                        bits = "".join(str(pins[p]) for p in reversed(range(8)))
                        self.print_clean(f"{dev_name}: {bits}  (bit7..bit0)")
                self.get_input_clean("\nPress Enter to continue...")

            elif choice == "2":
                self.reset_terminal()
                print("\033[?25l", end="")  # hide cursor
                try:
                    while True:
                        data = self.io_manager.snapshot_inputs()
                        sys.stdout.write("\033[H\033[J")
                        sys.stdout.flush()

                        self.print_clean("PCF8574 Live View (type 'q' + Enter to stop)\n")

                        for dev_name, pins in data.items():
                            if pins is None:
                                self.print_clean(f"{dev_name}: X read failed")
                            else:
                                bits = "".join(str(pins[p]) for p in reversed(range(8)))
                                self.print_clean(f"{dev_name}: {bits}  (bit7..bit0)")

                        rlist, _, _ = select.select([sys.stdin], [], [], PCF8574_POLL_INTERVAL)
                        if rlist:
                            cmd = sys.stdin.readline().strip().lower()
                            if cmd == "q":
                                break
                finally:
                    print("\033[?25h", end="")  # restore cursor
                    sys.stdout.flush()

            elif choice == "0":
                break
            else:
                self.print_clean("Invalid choice. Please try again.")
                time.sleep(1)

    async def handle_menu_choice(self, choice: str) -> bool:
        """Handle user menu choice"""
        camera_list = list(self.manager.cameras.items())

        if choice == "0":
            return False  # Normal exit

        elif choice == "00":
            self.print_clean("[EXIT] Force exit requested - skipping disconnect")
            self.shutdown_requested = True
            return False

        elif choice == "80":
            self.show_pcf8574_menu()

        elif choice == "90":
            await self.simultaneous_control()

        elif choice == "91":
            self.reset_terminal()
            self.print_clean("=" * 60)
            self.print_clean("    AUTOMATIC WIFI ENABLE + CONNECT ALL CAMERAS")
            self.print_clean("=" * 60)
            self.print_clean("")
            await self.manager.auto_enable_all_wifi_and_connect()
            self.print_clean("")
            self.print_clean("=" * 60)
            self.get_input_clean("\nPress Enter to continue...")

        elif choice == "92":
            self.print_clean("\n[DISCOVER] Searching for new cameras...")
            await self.manager.discover_and_pair_cameras()
            self.get_input_clean("\nPress Enter to continue...")

        elif choice == "93":
            self.reset_terminal()
            self.manager.show_config_status()
            self.get_input_clean("\nPress Enter to continue...")

        elif choice == "94":
            self.reset_terminal()
            self.manager.show_network_debug()
            self.get_input_clean("\nPress Enter to continue...")

        elif choice == "95":
            self.reset_terminal()
            self.manager.show_wifi_controller_debug()
            self.get_input_clean("\nPress Enter to continue...")

        elif choice == "96":
            self.print_clean("[WIFI] Enabling WiFi on all cameras (manual)...")
            for camera in self.manager.cameras.values():
                await camera.enable_wifi()
            self.get_input_clean("\nPress Enter to continue...")

        else:
            try:
                choice_num = int(choice)

                # WiFi control (21-29)
                if 21 <= choice_num <= 29:
                    camera_index = choice_num - 21
                    if camera_index < len(camera_list):
                        camera_id, _camera = camera_list[camera_index]
                        self.control_camera_wifi(camera_id)
                    else:
                        self.print_clean(f"X Camera {camera_index + 1} not available")
                        self.get_input_clean("\nPress Enter to continue...")

                # WiFi connection (31-39)
                elif 31 <= choice_num <= 39:
                    camera_index = choice_num - 31
                    if camera_index < len(camera_list):
                        camera_id, cam = camera_list[camera_index]
                        self.print_clean(f"\n[CONNECT] Connecting {cam.camera_name} WiFi...")
                        self.manager.connect_to_wifi_interface(camera_id)
                        self.get_input_clean("\nPress Enter to continue...")
                    else:
                        self.print_clean(f"X Camera {camera_index + 1} not available")
                        self.get_input_clean("\nPress Enter to continue...")

                else:
                    self.print_clean("Invalid choice")
                    time.sleep(1)

            except ValueError:
                self.print_clean("Invalid choice")
                time.sleep(1)

        return True  # Continue running

    async def graceful_shutdown(self):
        """Perform graceful shutdown"""
        if self.shutdown_requested:
            self.print_clean("[EXIT] Force exit - cleanup skipped")
            return

        self.print_clean("\n[EXIT] Shutting down gracefully...")
        try:
            await asyncio.wait_for(self.manager.disconnect_all(), timeout=15.0)
            self.print_clean("[EXIT] Graceful shutdown completed")
        except asyncio.TimeoutError:
            self.print_clean("[EXIT] Shutdown timeout - forcing exit")
        except Exception as e:
            self.print_clean(f"[EXIT] Shutdown error: {e}")

    async def run(self):
        """Main application loop with robust error handling"""
        self.reset_terminal()

        self.print_clean("=" * 60)
        self.print_clean("    DUAL WIFI INTERFACE GOPRO CONTROLLER")
        self.print_clean("=" * 60)
        self.print_clean("")
        self.print_clean("[CONFIG] Camera 1 (GoPro 3811) -> wlan0")
        self.print_clean("[CONFIG] Camera 2 (TBD) -> wlan1")
        self.print_clean("")

        # Sync time with RTC/NTP at startup
        self.print_clean("[RTC] Synchronizing system time...")
        rtc_manager.sync_time()

        self.manager.show_config_status()

        try:
            # Step 1: Connect to cameras
            self.print_clean("\n[INIT] Step 1: Camera Connection")

            # Try known cameras first
            if not await self.manager.connect_known_cameras():
                self.print_clean("[CHECK] No known cameras found, starting discovery...")
                if not await self.manager.discover_and_pair_cameras():
                    self.print_clean("X No cameras available")
                    self.get_input_clean("\nPress Enter to exit...")
                    return

            # Auto-setup WiFi
            if len(self.manager.cameras) > 0 and len(self.manager.wifi_controllers) == 0:
                self.print_clean("\n[AUTO] Cameras connected via Bluetooth!")
                self.print_clean("[AUTO] Starting automatic WiFi setup...")
                await self.manager.auto_enable_all_wifi_and_connect()

                self.print_clean("\n[READY] Setup complete!")
                time.sleep(2)

            # Step 2: Main control loop
            while True:
                try:
                    self.show_main_menu()
                    choice = self.get_input_clean("Choice: ")

                    if not await self.handle_menu_choice(choice):
                        break

                except KeyboardInterrupt:
                    self.print_clean("\n[INT] Ctrl+C detected - starting graceful shutdown...")
                    break
                except EOFError:
                    self.print_clean("\n[EOF] Input stream closed - exiting...")
                    break

        except Exception as e:
            logger.error(f"Runtime error: {e}")
            self.print_clean(f"[ERROR] Unexpected error: {e}")

        finally:
            await self.graceful_shutdown()


async def main():
    """Main entry point with signal handling"""
    app = GoProControllerUI()

    def signal_handler():
        print("\n[SIGNAL] Shutdown signal received")
        app.shutdown_requested = True

    if HAS_SIGNAL and sys.platform != "win32":
        try:
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, signal_handler)
        except Exception as e:
            print(f"[WARN] Could not set signal handlers: {e}")

    try:
        await app.run()
    except KeyboardInterrupt:
        print("\n[EXIT] Keyboard interrupt")
    except Exception as e:
        print(f"[ERROR] Fatal error: {e}")
        logger.exception("Fatal error details:")


if __name__ == "__main__":
    # Initial terminal cleanup
    print("\033c", end="")
    print("\033[H\033[2J", end="")
    sys.stdout.flush()

    print("=" * 60)
    print("    DUAL WIFI INTERFACE GOPRO CONTROLLER")
    print("=" * 60)
    print("")
    print("[CONFIG] Camera 1 -> wlan0 (built-in WiFi)")
    print("[CONFIG] Camera 2 -> wlan1 (USB WiFi adapter)")
    print("[AUTO] Automatic interface assignment and management")
    print("")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[EXIT] Program interrupted")
    except Exception as e:
        print(f"[FATAL] {e}")
    finally:
        print("[EXIT] Program terminated")
