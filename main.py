#!/usr/bin/env python3
"""
Main entry point for Dual WiFi Interface GoPro Controller
Fixed with robust terminal handling and proper cursor management
"""

import asyncio
import logging
import signal
import sys
import os
import time
import subprocess

from config import (SLEEP_MENU, SHOW_DEBUGGING_INFO, 
                    I2C_BUS, PCF8574_ADDRESSES, PCF8574_POLL_INTERVAL,
                    TRIGGER_INPUT, RECORDING_TIME)

from dual_wifi_manager import DualWiFiGoProManager
from gopro_downloader import download_both_latest, combine_side_by_side_background
import rtc_manager
from pcf8574_manager import PCF8574Manager

logger = logging.getLogger(__name__)

class GoProControllerUI:
    """User interface for the GoPro controller"""
    
    def __init__(self):
        self.manager = DualWiFiGoProManager()
        self.shutdown_requested = False
        try:
            self.io_manager = PCF8574Manager(I2C_BUS, PCF8574_ADDRESSES)
        except Exception:
            self.io_manager = None
        # Persisted trigger mode
        self.trigger_mode = self.manager.config.get('trigger_mode', 'manual')

    def reset_terminal(self):
        """Completely reset terminal state"""
        try:
            # Force terminal reset using stty
            subprocess.run(['stty', 'sane'], check=False, stderr=subprocess.DEVNULL)
            
            # Reset all terminal settings
            print('\033c', end='')  # Full terminal reset
            print('\033[H\033[2J', end='')  # Clear screen and move cursor to home
            print('\033[0m', end='')  # Reset all attributes
            
            # Flush everything
            sys.stdout.flush()
            sys.stderr.flush()
            
            # Additional reset
            os.system('reset > /dev/null 2>&1')
            
        except:
            # Fallback - just clear with newlines
            print('\n' * 100)
        
        # Final flush
        sys.stdout.flush()
    
    def print_clean(self, text=""):
        """Print with proper line endings and flush"""
        print(text)
        sys.stdout.flush()
    
    def get_input_clean(self, prompt):
        """Get input with proper terminal handling"""
        sys.stdout.write(prompt)
        sys.stdout.flush()
        try:
            return input().strip()
        except (EOFError, KeyboardInterrupt):
            return "0"
    
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
            
            if choice == '1':
                self.print_clean(f"\n[PHOTO] Taking photo on {camera.camera_name}...")
                if wifi_ctrl.take_photo():
                    self.print_clean("[OK] Photo command sent!")
                else:
                    self.print_clean("X Photo command failed")
                if SHOW_DEBUGGING_INFO == "ON":
                    self.get_input_clean("\nPress Enter to continue...")
            
            elif choice == '2':
                self.print_clean(f"\n[REC] Starting recording on {camera.camera_name}...")
                if wifi_ctrl.start_recording():
                    self.print_clean("[OK] Recording started!")
                else:
                    self.print_clean("X Recording start failed")
                if SHOW_DEBUGGING_INFO == "ON":
                    self.get_input_clean("\nPress Enter to continue...")
            
            elif choice == '3':
                self.print_clean(f"\n[STOP] Stopping recording on {camera.camera_name}...")
                if wifi_ctrl.stop_recording():
                    self.print_clean("[OK] Recording stopped!")
                else:
                    self.print_clean("X Recording stop failed")
                if SHOW_DEBUGGING_INFO == "ON":    
                    self.get_input_clean("\nPress Enter to continue...")
            
            elif choice == '4':
                self.print_clean(f"\n[STATUS] Getting status from {camera.camera_name}...")
                status = wifi_ctrl.get_status()
                if status:
                    battery = status.get('status', {}).get('70', 'Unknown')
                    recording = status.get('status', {}).get('8', 0)
                    mode = status.get('status', {}).get('43', 'Unknown')
                    self.print_clean(f"[BATTERY] Battery: {battery}%")
                    self.print_clean(f"[REC] Recording: {'Yes' if recording else 'No'}")
                    self.print_clean(f"[MODE] Mode: {mode}")
                else:
                    self.print_clean("X No status received")
                self.get_input_clean("\nPress Enter to continue...")
            
            elif choice == '5':
                self.print_clean(f"\n[CHECK] Testing connection to {camera.camera_name}...")
                if wifi_ctrl.test_connection():
                    self.print_clean("[OK] Connection test passed!")
                else:
                    self.print_clean("X Connection test failed")
                self.get_input_clean("\nPress Enter to continue...")
            
            elif choice == '0':
                break
            else:
                self.print_clean("Invalid choice. Please try again.")
                time.sleep(1)
    
    def _save_trigger_mode(self):
        """Persist trigger mode in the shared config file."""
        try:
            self.manager.config['trigger_mode'] = self.trigger_mode
            self.manager.save_config()
        except Exception:
            pass  # Don't crash the UI if saving fails

    def _trigger_mode_label(self) -> str:
        return "Manual" if self.trigger_mode == "manual" else f"I2C (P{TRIGGER_INPUT})"


    async def start_recording_all_cameras(self):
        """Start recording on ALL cameras SIMULTANEOUSLY via WiFi - MILLISECOND PRECISION"""
        if not self.manager.wifi_controllers:
            self.print_clean("[ERROR] No WiFi controllers available! Use option 91 first.")
            return 0
        
        self.print_clean(f"[MILLISECOND] Starting recording on {len(self.manager.wifi_controllers)} cameras...")
        
        # Create truly async WiFi tasks with asyncio subprocess
        async def start_single_wifi_async(camera_id, wifi_ctrl):
            try:
                self.print_clean(f"[START] {wifi_ctrl.camera_name} via {wifi_ctrl.wifi_interface}...")
                
                # Set video mode first (async)
                mode_url = f"http://{wifi_ctrl.ip}:8080/gp/gpControl/command/mode?p=0"
                mode_success = await self.async_curl_request(mode_url, wifi_ctrl.wifi_interface)
                
                if not mode_success:
                    self.print_clean(f"[FAIL] {wifi_ctrl.camera_name} mode setting failed")
                    return 0
                
                # Small delay for mode change
                await asyncio.sleep(0.5)
                
                # Start recording (async)
                record_url = f"http://{wifi_ctrl.ip}:8080/gp/gpControl/command/shutter?p=1"
                record_success = await self.async_curl_request(record_url, wifi_ctrl.wifi_interface)
                
                if record_success:
                    self.print_clean(f"[OK] {wifi_ctrl.camera_name} RECORDING")
                    return 1
                else:
                    self.print_clean(f"[FAIL] {wifi_ctrl.camera_name} recording failed")
                    return 0
                    
            except Exception as e:
                self.print_clean(f"[ERROR] {wifi_ctrl.camera_name}: {e}")
                return 0
        
        # Execute ALL cameras in parallel - TRUE MILLISECOND SIMULTANEITY
        tasks = [
            start_single_wifi_async(camera_id, wifi_ctrl) 
            for camera_id, wifi_ctrl in self.manager.wifi_controllers.items()
        ]
        
        results = await asyncio.gather(*tasks)
        return sum(results)

    async def timed_recording_all_cameras(self):
        """Start both cameras, record for configured time, then stop."""
        if not self.manager.wifi_controllers:
            self.print_clean("[ERROR] No WiFi controllers available! Use option 91 first.")
            self.get_input_clean("\nPress Enter to continue...")
            return

        self.print_clean(f"[ARMED] Timed recording armed ({RECORDING_TIME:.1f}s). Trigger mode: {self._trigger_mode_label()}")

        # 1) Wait for trigger
        if self.trigger_mode == "manual":
            self.get_input_clean("\nPress Enter to TRIGGER...")
        else:
            await self._wait_for_i2c_trigger()

        # 2) Start recording on all cameras
        started = await self.start_recording_all_cameras()
        if started == 0:
            self.print_clean("[FAIL] No cameras started recording.")
            self.get_input_clean("\nPress Enter to continue...")
            return

        self.print_clean(f"[RUNNING] Recording for {RECORDING_TIME:.1f}s...")
        await asyncio.sleep(RECORDING_TIME)

        # 3) Stop all cameras
        stopped = await self.stop_recording_all_cameras()
        
        # 4) ... after STOP on both cameras:
        downloads = await download_both_latest(self.manager.wifi_controllers)

        left = downloads.get("camera_1")
        right = downloads.get("camera_2")

        # Only attempt combine when BOTH exist:
        if left and right:
            combine_side_by_side_background(left, right)
        else:
            print("[FFMPEG] Not combining because a clip is missing.")

            self.print_clean(f"[DONE] Stopped {stopped} cameras.")
            self.get_input_clean("\nPress Enter to continue...")

    
    async def async_curl_request(self, url: str, interface: str) -> bool:
        """Make async HTTP request using asyncio subprocess for true parallelism"""
        try:
            # Build curl command
            curl_cmd = [
                'curl',
                '--interface', interface,
                '--connect-timeout', '5',
                '--max-time', '10',
                '-s',
                url
            ]
            
            # Execute async subprocess
            process = await asyncio.create_subprocess_exec(
                *curl_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            return process.returncode == 0
            
        except Exception as e:
            self.print_clean(f"[CURL ERROR] {e}")
            return False

    async def stop_recording_all_cameras(self):
        """Stop recording on ALL cameras SIMULTANEOUSLY via WiFi - MILLISECOND PRECISION"""
        if not self.manager.wifi_controllers:
            self.print_clean("[ERROR] No WiFi controllers available!")
            return 0
        
        self.print_clean(f"[MILLISECOND] Stopping recording on {len(self.manager.wifi_controllers)} cameras...")
        
        # Create truly async WiFi tasks
        async def stop_single_wifi_async(camera_id, wifi_ctrl):
            try:
                self.print_clean(f"[STOP] {wifi_ctrl.camera_name} via {wifi_ctrl.wifi_interface}...")
                
                # Stop recording (async)
                stop_url = f"http://{wifi_ctrl.ip}:8080/gp/gpControl/command/shutter?p=0"
                success = await self.async_curl_request(stop_url, wifi_ctrl.wifi_interface)
                
                if success:
                    self.print_clean(f"[OK] {wifi_ctrl.camera_name} STOPPED")
                    return 1
                else:
                    self.print_clean(f"[FAIL] {wifi_ctrl.camera_name} failed")
                    return 0
            except Exception as e:
                self.print_clean(f"[ERROR] {wifi_ctrl.camera_name}: {e}")
                return 0
        
        # Execute ALL cameras in parallel - TRUE MILLISECOND SIMULTANEITY
        tasks = [
            stop_single_wifi_async(camera_id, wifi_ctrl) 
            for camera_id, wifi_ctrl in self.manager.wifi_controllers.items()
        ]
        
        results = await asyncio.gather(*tasks)
        return sum(results)

    async def take_photos_all_cameras(self):
        """Take photos on ALL cameras SIMULTANEOUSLY via WiFi - MILLISECOND PRECISION"""
        if not self.manager.wifi_controllers:
            self.print_clean("[ERROR] No WiFi controllers available! Use option 91 first.")
            return 0
        
        self.print_clean(f"[MILLISECOND] Taking photos on {len(self.manager.wifi_controllers)} cameras...")
        
        # Create truly async WiFi tasks
        async def photo_single_wifi_async(camera_id, wifi_ctrl):
            try:
                self.print_clean(f"[PHOTO] {wifi_ctrl.camera_name} via {wifi_ctrl.wifi_interface}...")
                
                # Set photo mode first (async)
                mode_url = f"http://{wifi_ctrl.ip}:8080/gp/gpControl/command/mode?p=1"
                mode_success = await self.async_curl_request(mode_url, wifi_ctrl.wifi_interface)
                
                if not mode_success:
                    self.print_clean(f"[FAIL] {wifi_ctrl.camera_name} mode setting failed")
                    return 0
                
                # Small delay for mode change
                await asyncio.sleep(0.5)
                
                # Take photo (async)
                photo_url = f"http://{wifi_ctrl.ip}:8080/gp/gpControl/command/shutter?p=1"
                photo_success = await self.async_curl_request(photo_url, wifi_ctrl.wifi_interface)
                
                if photo_success:
                    self.print_clean(f"[OK] {wifi_ctrl.camera_name} PHOTO TAKEN")
                    return 1
                else:
                    self.print_clean(f"[FAIL] {wifi_ctrl.camera_name} failed")
                    return 0
            except Exception as e:
                self.print_clean(f"[ERROR] {wifi_ctrl.camera_name}: {e}")
                return 0
        
        # Execute ALL cameras in parallel - TRUE MILLISECOND SIMULTANEITY
        tasks = [
            photo_single_wifi_async(camera_id, wifi_ctrl) 
            for camera_id, wifi_ctrl in self.manager.wifi_controllers.items()
        ]
        
        results = await asyncio.gather(*tasks)
        return sum(results)

    async def _wait_for_i2c_trigger(self):
        """Wait for PCF8574 pin TRIGGER_INPUT to go LOW (active)."""
        if self.io_manager is None:
            self.print_clean("[IO] PCF8574 not available; falling back to manual trigger.")
            self.get_input_clean("\nPress Enter to TRIGGER...")
            return

        self.print_clean(f"\n[WAIT] Waiting for I2C trigger on P{TRIGGER_INPUT} (active LOW)...")
        last = None
        stable_low = 0
        required_stable = 2  # two consecutive reads

        while True:
            snapshot = self.io_manager.snapshot()
            # For simplicity, read the first device in your list
            pins = None
            for _, pins in snapshot.items():
                break  # first device
            if pins is None:
                await asyncio.sleep(PCF8574_POLL_INTERVAL)
                continue

            level = pins.get(TRIGGER_INPUT, 1)  # default HIGH if missing
            # Looking for LOW (0)
            if level == 0:
                stable_low += 1
                if stable_low >= required_stable:
                    self.print_clean("[TRIGGER] I2C input asserted.")
                    return
            else:
                stable_low = 0

            await asyncio.sleep(PCF8574_POLL_INTERVAL)

    
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
            
            if choice == '1':
                self.print_clean("[PHOTO] Taking photos on all cameras...")
                success_count = await self.take_photos_all_cameras()
                time.sleep(SLEEP_MENU)
                if SHOW_DEBUGGING_INFO == "ON":
                    self.print_clean(f"[RESULT] {success_count}/{len(self.manager.cameras)} photos taken")
                    self.get_input_clean("\nPress Enter to continue...")
            
            elif choice == '2':
                await self.timed_recording_all_cameras()

            elif choice == '3':
                self.print_clean("[STOP] Stopping recording on all cameras...")
                success_count = await self.stop_recording_all_cameras()
                time.sleep(SLEEP_MENU)
                if SHOW_DEBUGGING_INFO == "ON":
                    self.print_clean(f"[RESULT] {success_count}/{len(self.manager.cameras)} cameras stopped")
                    self.get_input_clean("\nPress Enter to continue...")
            
            elif choice == '4':
                self.print_clean("[WIFI] Enabling WiFi on all cameras...")
                tasks = [camera.enable_wifi() for camera in self.manager.cameras.values()]
                results = await asyncio.gather(*tasks)
                success_count = sum(results)
                time.sleep(SLEEP_MENU)
                if SHOW_DEBUGGING_INFO == "ON":
                    self.print_clean(f"[OK] {success_count}/{len(self.manager.cameras)} WiFi enabled")
                    self.get_input_clean("\nPress Enter to continue...")

            elif choice == '5':
                # Toggle between manual and i2c, persist to config
                self.trigger_mode = "i2c" if self.trigger_mode == "manual" else "manual"
                self._save_trigger_mode()
                self.print_clean(f"[MODE] Trigger mode set to: {self._trigger_mode_label()}")
                time.sleep(1)

            elif choice == '6':
                # Choose which camera to wipe
                self.reset_terminal()
                self.print_clean("=" * 60)
                self.print_clean("    DELETE ALL MEDIA (Single Camera)")
                self.print_clean("=" * 60)
                if not self.manager.wifi_controllers:
                    self.print_clean("\n[ERROR] No WiFi controllers available. Use 91 to connect first.")
                    self.get_input_clean("\nPress Enter to continue...")
                    continue

                # Build a stable, numbered list based on the main camera list order
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

                _, cam_id, cam = choices[n-1]
                if cam_id not in self.manager.wifi_controllers:
                    self.print_clean("\n[ERROR] Selected camera is not connected over Wi‑Fi.")
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
                    self.print_clean("[OK] Camera acknowledged delete‑all request.")
                else:
                    self.print_clean("X Delete‑all request failed (check Wi‑Fi connection).")
                self.get_input_clean("\nPress Enter to continue...")
                
            elif choice == '0':
                break
            else:
                self.print_clean("Invalid choice. Please try again.")
                time.sleep(1)
    
    def show_main_menu(self):
        """Display the main menu with clean, robust formatting"""
        self.reset_terminal()
        
        camera_list = list(self.manager.cameras.items())
        
        # Build menu step by step with explicit flushes
        self.print_clean("    DUAL WIFI GOPRO CONTROLLER")
        
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
        
        # Two-column menu layout
        menu_items = [
            ("21. Control Camera 1",   "31. Connect Camera 1 WiFi"),
            ("22. Control Camera 2",   "32. Connect Camera 2 WiFi"),
            ("80. I/O (PCF8574) status",""                        ),
            ("90. Simultaneous control","91. AUTO: WiFi setup"),
            ("92. Add new camera",     "93. Show config"),
            ("94. Network debug",      "95. WiFi debug"),
            ("96. Manual WiFi enable", "0. Exit / 00. Force Exit")
        ]
        
        self.print_clean("Main Menu:")
        for left, right in menu_items:
            self.print_clean(f"  {left:<30} {right}")
        
        self.print_clean("-" * 60)
    
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

            if choice == '1':
                self.reset_terminal()
                self.print_clean("PCF8574 Snapshot:\n")
                data = self.io_manager.snapshot()
                for dev_name, pins in data.items():
                    if pins is None:
                        self.print_clean(f"{dev_name}: X read failed")
                    else:
                        # Render pins 7..0 to match typical labeling
                        bits = "".join(str(pins[p]) for p in reversed(range(8)))
                        self.print_clean(f"{dev_name}: {bits}  (bit7..bit0)")
                        #self.print_clean("           " + " ".join(f"P{p}:{pins[p]}" for p in range(8)))
                self.get_input_clean("\nPress Enter to continue...")

            elif choice == '2':
                # One-time screen setup
                self.reset_terminal()
                print("\033[?25l", end="")  # hide cursor
                try:
                    while True:
                        data = self.io_manager.snapshot()

                        # Move cursor to top-left and clear only the area we rewrite
                        # (home + clear-to-end-of-screen)
                        sys.stdout.write("\033[H\033[J")
                        sys.stdout.flush()

                        self.print_clean("PCF8574 Live View (type 'q' + Enter to stop)\n")

                        for dev_name, pins in data.items():
                            if pins is None:
                                self.print_clean(f"{dev_name}: X read failed")
                            else:
                                bits = "".join(str(pins[p]) for p in reversed(range(8)))
                                self.print_clean(f"{dev_name}: {bits}  (bit7..bit0)")
                                #self.print_clean("           " + " ".join(f"P{p}:{pins[p]}" for p in range(8)))

                        # Timed, quiet check for 'q' without printing extra lines every loop
                        import select
                        rlist, _, _ = select.select([sys.stdin], [], [], PCF8574_POLL_INTERVAL)
                        if rlist:
                            cmd = sys.stdin.readline().strip().lower()
                            if cmd == 'q':
                                break
                finally:
                    # Restore cursor visibility
                    print("\033[?25h", end="")
                    sys.stdout.flush()

            elif choice == '0':
                break
            else:
                self.print_clean("Invalid choice. Please try again.")
                time.sleep(1)
    

    async def handle_menu_choice(self, choice: str):
        """Handle user menu choice"""
        camera_list = list(self.manager.cameras.items())
        
        if choice == '0':
            return False  # Normal exit
        
        elif choice == '00':
            self.print_clean("[EXIT] Force exit requested - skipping disconnect")
            self.shutdown_requested = True
            return False
        
        elif choice == '80':
            self.show_pcf8574_menu()

        elif choice == '90':
            await self.simultaneous_control()
        
        elif choice == '91':
            self.reset_terminal()
            self.print_clean("=" * 60)
            self.print_clean("    AUTOMATIC WIFI ENABLE + CONNECT ALL CAMERAS")
            self.print_clean("=" * 60)
            self.print_clean("")
            await self.manager.auto_enable_all_wifi_and_connect()
            self.print_clean("")
            self.print_clean("=" * 60)
            self.get_input_clean("\nPress Enter to continue...")
        
        elif choice == '92':
            self.print_clean("\n[DISCOVER] Searching for new cameras...")
            await self.manager.discover_and_pair_cameras()
            self.get_input_clean("\nPress Enter to continue...")
        
        elif choice == '93':
            self.reset_terminal()
            self.manager.show_config_status()
            self.get_input_clean("\nPress Enter to continue...")
        
        elif choice == '94':
            self.reset_terminal()
            self.manager.show_network_debug()
            self.get_input_clean("\nPress Enter to continue...")
        
        elif choice == '95':
            self.reset_terminal()
            self.manager.show_wifi_controller_debug()
            self.get_input_clean("\nPress Enter to continue...")
        
        elif choice == '96':
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
                        camera_id, camera = camera_list[camera_index]
                        self.control_camera_wifi(camera_id)
                    else:
                        self.print_clean(f"X Camera {camera_index + 1} not available")
                        self.get_input_clean("\nPress Enter to continue...")
                
                # WiFi connection (31-39)
                elif 31 <= choice_num <= 39:
                    camera_index = choice_num - 31
                    if camera_index < len(camera_list):
                        camera_id, camera = camera_list[camera_index]
                        self.print_clean(f"\n[CONNECT] Connecting {camera.camera_name} WiFi...")
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

        # NEW: Sync time with RTC/NTP at startup
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
    
    # Set up signal handlers for graceful shutdown
    def signal_handler():
        print("\n[SIGNAL] Shutdown signal received")
        app.shutdown_requested = True
    
    if sys.platform != 'win32':
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, signal_handler)
    
    try:
        await app.run()
    except KeyboardInterrupt:
        print("\n[EXIT] Keyboard interrupt")
    except Exception as e:
        print(f"[ERROR] Fatal error: {e}")
        logger.exception("Fatal error details:")


if __name__ == "__main__":
    # Initial setup with clean terminal
    print('\033c', end='')  # Full reset
    print('\033[H\033[2J', end='')  # Clear and home
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