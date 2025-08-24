#!/usr/bin/env python3
"""
Dual WiFi GoPro Manager - Modified for PARALLEL WiFi connections
FIXED: Added missing imports and removed duplicate line
"""

import asyncio
import json
import logging
import subprocess
import time
import sys
import io
from typing import Dict, List, Tuple

from bleak import BleakScanner
from bleak.backends.device import BLEDevice

from config import (
    CONFIG_FILE, INTERFACE_ASSIGNMENTS, GOPRO_DEVICE_PATTERNS,
    TIMEOUTS, GOPRO_IP, STATIC_IPS, ROUTING_METRICS
)
from single_gopro_controller import SingleGoProController
from wifi_camera_controller import WiFiCameraController

logger = logging.getLogger(__name__)

class DualWiFiGoProManager:
    """Manager for dual WiFi interface GoPro setup with PARALLEL auto-connection"""
    
    def __init__(self):
        self.config_file = CONFIG_FILE
        self.config = self.load_config()
        self.cameras = {}  # camera_id -> SingleGoProController
        self.wifi_controllers = {}  # camera_id -> WiFiCameraController
        self.interface_assignments = INTERFACE_ASSIGNMENTS
        
        # Set regulatory domain for 5GHz support (US regulations)
        try:
            subprocess.run("sudo iw reg set US", shell=True, 
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info("[WIFI] Regulatory domain set to US for 5GHz support")
        except Exception as e:
            logger.warning(f"[WIFI] Could not set regulatory domain: {e}")
    
    def load_config(self) -> dict:
        """Load multi-camera configuration"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    logger.info(f"[CONFIG] Loaded config for {len(config.get('cameras', {}))} cameras")
                    return config
            except Exception as e:
                logger.warning(f"Config load error: {e}")
        
        return {"cameras": {}}
    
    def save_config(self):
        """Save multi-camera configuration"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            logger.info("[SAVE] Dual WiFi configuration saved")
        except Exception as e:
            logger.error(f"Config save error: {e}")
    
    def check_wifi_interfaces(self) -> dict:
        """Check available WiFi interfaces"""
        interfaces = {}
        
        for interface in ["wlan0", "wlan1"]:
            try:
                result = subprocess.run(f"ip link show {interface}", shell=True, 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    interfaces[interface] = "Available"
                    logger.info(f"[OK] {interface} detected")
                else:
                    interfaces[interface] = "Not found"
                    logger.warning(f"X {interface} not found")
            except:
                interfaces[interface] = "Error"
        
        return interfaces
    
    def show_config_status(self):
        """Show current configuration"""
        print("\n[CONFIG] Dual WiFi GoPro Configuration:")
        print("-" * 50)
        
        # Show interface status
        interfaces = self.check_wifi_interfaces()
        print("WiFi Interfaces:")
        for interface, status in interfaces.items():
            icon = "[OK]" if status == "Available" else "X"
            print(f"  {icon} {interface}: {status}")
        
        print()
        
        # Show camera assignments
        print("Camera -> Interface Assignments:")
        cameras = self.config.get('cameras', {})
        
        for camera_id in ["camera_1", "camera_2"]:
            interface = self.interface_assignments[camera_id]
            interface_status = interfaces.get(interface, "Unknown")
            
            if camera_id in cameras:
                camera_config = cameras[camera_id]
                name = camera_config.get('name', 'Unknown')
                wifi = camera_config.get('wifi_ssid', 'None')
                print(f"  [CAM] {name} -> {interface} ({interface_status})")
                print(f"     WiFi: {wifi}")
            else:
                print(f"  [EMPTY] {camera_id} -> {interface} ({interface_status}) [Not configured]")
        
        print("-" * 50)
    
    def show_wifi_controller_debug(self):
        """Show current WiFi controller mappings for debugging"""
        print("\n[CHECK] WiFi Controller Debug:")
        print("-" * 40)
        
        print("Camera Controllers:")
        for camera_id, camera in self.cameras.items():
            print(f"  {camera_id}: {camera.camera_name} -> {camera.wifi_interface}")
        
        print("\nWiFi Controllers:")
        for camera_id, wifi_ctrl in self.wifi_controllers.items():
            print(f"  {camera_id}: {wifi_ctrl.camera_name} -> {wifi_ctrl.wifi_interface}")
            print(f"    Interface IP: {wifi_ctrl.interface_ip}")
        
        print("\nRouting Table:")
        route_result = subprocess.run("ip route show | grep 10.5.5", shell=True, capture_output=True, text=True)
        for line in route_result.stdout.split('\n'):
            if line.strip():
                print(f"  {line.strip()}")
        
        print("-" * 40)
    
    def add_camera_config(self, camera_id: str, device: BLEDevice, controller: SingleGoProController):
        """Add camera to configuration"""
        if "cameras" not in self.config:
            self.config["cameras"] = {}
        
        # Store multiple MAC addresses for this camera
        existing_macs = self.config["cameras"].get(camera_id, {}).get('device_addresses', [])
        if device.address not in existing_macs:
            existing_macs.append(device.address)
        
        self.config["cameras"][camera_id] = {
            "name": controller.camera_name,
            "device_address": device.address,
            "device_addresses": existing_macs,
            "wifi_ssid": controller.wifi_ssid,
            "wifi_password": controller.wifi_password,
            "wifi_interface": controller.wifi_interface,
            "last_connected": time.time()
        }
        self.save_config()
    
    async def discover_and_pair_cameras(self) -> bool:
        """Discover and pair multiple GoPro cameras"""
        print("\n[CHECK] Scanning for GoPro cameras...")
        
        # Check interfaces first
        interfaces = self.check_wifi_interfaces()
        if interfaces.get("wlan1") != "Available":
            print("[WARN] WARNING: wlan1 (USB WiFi adapter) not detected!")
            print("   Camera 2 will be assigned to wlan1 but may not work until USB adapter is connected.")
        
        devices = await BleakScanner.discover(timeout=TIMEOUTS['bluetooth_discover'])
        gopro_devices = []
        
        # Find all GoPro devices
        for device in devices:
            if device.name and any(name in device.name for name in GOPRO_DEVICE_PATTERNS):
                gopro_devices.append(device)
                logger.info(f"[CAM] Found: {device.name} ({device.address})")
        
        if not gopro_devices:
            print("X No GoPro cameras found")
            return False
        
        # Pair each camera with interface assignment
        for i, device in enumerate(gopro_devices):
            camera_id = f"camera_{i+1}"
            assigned_interface = self.interface_assignments.get(camera_id, "wlan0")
            
            # Special handling for known GoPro 3811
            if "3811" in device.name:
                camera_id = "camera_1"
                assigned_interface = "wlan0"
                camera_name = f"GoPro 1 ({device.name}) -> wlan0"
            else:
                camera_id = "camera_2"
                assigned_interface = "wlan1"
                camera_name = f"GoPro 2 ({device.name}) -> wlan1"
            
            print(f"\n[CONNECT] Pairing {camera_name}...")
            
            controller = SingleGoProController(camera_id, camera_name, assigned_interface)
            
            if await controller.connect(device):
                self.cameras[camera_id] = controller
                print(f"[OK] {camera_name} paired successfully!")
            else:
                print(f"X {camera_name} pairing failed")
        
        return len(self.cameras) > 0
    
    async def connect_known_cameras(self) -> bool:
        """Connect to previously paired cameras"""
        cameras_config = self.config.get('cameras', {})
        if not cameras_config:
            return False
        
        print(f"\n[CONNECT] Connecting to {len(cameras_config)} known cameras...")
        
        # Discover available devices
        devices = await BleakScanner.discover(timeout=TIMEOUTS['bluetooth_connect'])
        device_map = {dev.address: dev for dev in devices}
        
        connected_count = 0
        
        for camera_id, camera_config in cameras_config.items():
            camera_name = camera_config.get('name', f'Camera {camera_id}')
            assigned_interface = self.interface_assignments.get(camera_id, "wlan0")
            addresses = camera_config.get('device_addresses', [camera_config.get('device_address')])
            
            connected = False
            for address in addresses:
                if address in device_map:
                    device = device_map[address]
                    
                    controller = SingleGoProController(camera_id, camera_name, assigned_interface)
                    controller.wifi_ssid = camera_config.get('wifi_ssid')
                    controller.wifi_password = camera_config.get('wifi_password')
                    
                    if await controller.connect(device):
                        self.cameras[camera_id] = controller
                        connected_count += 1
                        connected = True
                        break
            
            if not connected:
                print(f"[WARN] Could not connect to {camera_name}")
        
        print(f"[OK] Connected to {connected_count}/{len(cameras_config)} cameras")
        return connected_count > 0
    
    async def auto_enable_all_wifi_and_connect(self) -> bool:
        """ENHANCED: Auto-enable WiFi and connect all cameras with PARALLEL WiFi"""
        if not self.cameras:
            print("X No cameras available")
            return False
        
        print(f"\n[AUTO] PARALLEL Auto-enabling WiFi and connecting {len(self.cameras)} cameras...")
        
        # Step 1: Enable WiFi on all cameras (PARALLEL)
        print("[STEP 1] Enabling WiFi via Bluetooth (PARALLEL)...")
        wifi_enabled_results = await self._parallel_enable_wifi()
        
        wifi_enabled_count = sum(wifi_enabled_results.values())
        if wifi_enabled_count == 0:
            print("X No cameras had WiFi enabled")
            return False
        
        self.save_config()
        print(f"[RESULT] WiFi enabled on {wifi_enabled_count}/{len(self.cameras)} cameras")
        
        # Step 2: Wait for GoPros to start broadcasting
        print("\n[STEP 2] Waiting for cameras to start broadcasting...")
        await asyncio.sleep(6)
        
        # Step 3: Auto-connect to WiFi networks (PARALLEL)
        print("[STEP 3] Auto-connecting to WiFi networks (PARALLEL)...")
        wifi_connected_results = await self._parallel_connect_wifi()
        
        wifi_connected_count = sum(wifi_connected_results.values())
        print(f"\n[FINAL] {wifi_connected_count}/{len(self.cameras)} cameras ready for WiFi control")
        
        return wifi_connected_count > 0
    
    async def _parallel_enable_wifi(self) -> Dict[str, bool]:
        """Enable WiFi on all cameras in parallel"""
        
        async def enable_wifi_single(camera_id: str, camera: SingleGoProController) -> Tuple[str, bool]:
            """Enable WiFi for a single camera"""
            print(f"[ENABLE] {camera.camera_name}...")
            
            try:
                if await camera.enable_wifi():
                    print(f"[OK] WiFi enabled: {camera.wifi_ssid}")
                    
                    # Update config with WiFi credentials
                    if "cameras" in self.config and camera_id in self.config["cameras"]:
                        self.config["cameras"][camera_id]["wifi_ssid"] = camera.wifi_ssid
                        self.config["cameras"][camera_id]["wifi_password"] = camera.wifi_password
                    
                    return camera_id, True
                else:
                    print(f"X WiFi enable failed for {camera.camera_name}")
                    return camera_id, False
            except Exception as e:
                print(f"X WiFi enable error for {camera.camera_name}: {e}")
                return camera_id, False
        
        # Create tasks for all cameras
        tasks = []
        for camera_id, camera in self.cameras.items():
            task = enable_wifi_single(camera_id, camera)
            tasks.append(task)
        
        # Run all WiFi enable tasks in parallel
        print(f"[PARALLEL] Starting {len(tasks)} WiFi enable tasks...")
        start_time = time.time()
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        print(f"[TIMING] WiFi enable completed in {end_time - start_time:.1f}s (parallel)")
        
        # Convert results to dictionary
        result_dict = {}
        for result in results:
            if isinstance(result, tuple):
                camera_id, success = result
                result_dict[camera_id] = success
            else:
                print(f"[ERROR] Task failed with exception: {result}")
        
        return result_dict
    
    async def _parallel_connect_wifi(self) -> Dict[str, bool]:
        """Connect to WiFi networks in parallel with clean progress display"""
        
        # SIMPLIFIED: Use the same method as manual connections, just run them in parallel
        async def connect_wifi_single_async(camera_id: str, camera: SingleGoProController) -> Tuple[str, bool]:
            """Connect WiFi for a single camera (async version)"""
            if not camera.wifi_ssid or not camera.wifi_password:
                return camera_id, False
            
            # Show simple progress indicator
            cam_num = "3811" if "3811" in camera.camera_name else "4511"
            print(f"[CONNECT] GoPro {cam_num} -> {camera.wifi_interface}... ", end="", flush=True)
            
            try:
                # Use the same method as manual connections but with reduced verbosity
                success = self._setup_wifi_connection_for_auto(camera, camera.wifi_interface)
                if success:
                    print("OK")
                else:
                    print("FAILED")
                return camera_id, success
            except Exception as e:
                print(f"ERROR: {e}")
                return camera_id, False
        
        # Create async tasks for all cameras with WiFi credentials
        tasks = []
        for camera_id, camera in self.cameras.items():
            if camera.wifi_ssid and camera.wifi_password:
                task = connect_wifi_single_async(camera_id, camera)
                tasks.append(task)
        
        if not tasks:
            print("X No cameras with WiFi credentials")
            return {}
        
        # Run all WiFi connection tasks in parallel
        print(f"[PARALLEL] Connecting {len(tasks)} cameras to WiFi...")
        start_time = time.time()
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        print(f"[TIMING] WiFi connections completed in {end_time - start_time:.1f}s (parallel)")
        
        # Convert results to dictionary
        result_dict = {}
        for result in results:
            if isinstance(result, tuple):
                camera_id, success = result
                result_dict[camera_id] = success
            else:
                print(f"[ERROR] WiFi task failed with exception: {result}")
        
        return result_dict

    # SIMPLIFIED AUTO-CONNECTION METHOD (avoids async executor issues)
    def _setup_wifi_connection_for_auto(self, camera: SingleGoProController, interface: str) -> bool:
        """
        Simplified WiFi connection setup for auto-connection (avoids threading issues)
        
        Args:
            camera: Camera controller with WiFi credentials
            interface: Network interface to use (wlan0/wlan1)
        
        Returns:
            bool: Success status
        """
        try:
            # Step 1: Clean up existing connections
            subprocess.run(f"sudo nmcli device set {interface} managed no", shell=True, 
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(f"sudo pkill -f 'wpa_supplicant.*{interface}'", shell=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(f"sudo dhclient -r {interface}", shell=True, 
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(f"sudo ip addr flush dev {interface}", shell=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(f"sudo ip route flush dev {interface}", shell=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(f"sudo rm -f /var/run/wpa_supplicant/*", shell=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
            
            # Step 2: Bring interface up
            subprocess.run(f"sudo ip link set {interface} up", shell=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
            
            # Step 3: Start wpa_supplicant
            wpa_config = f'''ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
network={{
    ssid="{camera.wifi_ssid}"
    psk="{camera.wifi_password}"
    key_mgmt=WPA-PSK
    priority=1
    scan_ssid=1
}}'''
            
            config_file = f"/tmp/gopro_{interface}.conf"
            with open(config_file, "w") as f:
                f.write(wpa_config)
            
            cmd = f"sudo wpa_supplicant -B -i {interface} -c {config_file} -D nl80211,wext"
            result = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if result.returncode != 0:
                return False
            
            # Step 4: Wait for WiFi connection
            timeout = 8  # Shorter timeout for auto mode
            
            for attempt in range(timeout):
                time.sleep(0.6)
                
                try:
                    iwconfig_result = subprocess.run(f"iwconfig {interface}", shell=True, 
                                                   capture_output=True, text=True)
                    if iwconfig_result.returncode == 0:
                        # Check if actually connected
                        if camera.wifi_ssid in iwconfig_result.stdout and "Access Point:" in iwconfig_result.stdout:
                            if "Not-Associated" not in iwconfig_result.stdout:
                                break
                except:
                    pass
            else:
                return False  # Failed to connect within timeout
            
            # Step 5: Setup IP addressing
            try:
                dhcp_result = subprocess.run(f"sudo dhclient -v {interface}", shell=True, 
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           timeout=3)
                dhcp_success = dhcp_result.returncode == 0
            except subprocess.TimeoutExpired:
                dhcp_success = False
            
            if not dhcp_success:
                static_ip = STATIC_IPS[interface]
                subprocess.run(f"sudo ip addr add {static_ip} dev {interface}", shell=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.5)
            
            # Step 6: Setup routing
            metric = ROUTING_METRICS[interface]
            subprocess.run(f"sudo ip route del {GOPRO_IP} 2>/dev/null", shell=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(f"sudo ip route del 10.5.5.0/24 2>/dev/null", shell=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(f"sudo ip route add {GOPRO_IP} dev {interface} metric {metric}", shell=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(f"sudo ip route add 10.5.5.0/24 dev {interface} metric {metric}", shell=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
            
            # Step 7: Test connection and create controller
            test_cmd = f"curl --interface {interface} --connect-timeout 5 --max-time 10 http://{GOPRO_IP}:8080/gp/gpControl/status"
            test_result = subprocess.run(test_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if test_result.returncode == 0:
                # Create WiFi controller (simplified, no stdout redirection)
                try:
                    wifi_ctrl = WiFiCameraController(camera.camera_name, interface, GOPRO_IP)
                    self.wifi_controllers[camera.camera_id] = wifi_ctrl
                    return True
                except Exception:
                    return False
            else:
                return False
                
        except Exception as e:
            return False
    def _setup_wifi_connection(self, camera: SingleGoProController, interface: str, verbose: bool = True) -> bool:
        """
        Unified WiFi connection setup method
        
        Args:
            camera: Camera controller with WiFi credentials
            interface: Network interface to use (wlan0/wlan1) 
            verbose: Whether to print detailed progress (False for parallel execution)
        
        Returns:
            bool: Success status
        """
        def log(message: str, level: str = "info"):
            """Conditional logging based on verbose mode"""
            if verbose:
                if level == "error":
                    print(f"X {message}")
                else:
                    print(f"[{level.upper()}] {message}")
        
        # Determine output redirect for subprocess calls
        output_redirect = None if verbose else subprocess.DEVNULL
        
        try:
            # Step 1: Clean up existing connections
            log(f"Cleaning up {interface}...", "clean")
            subprocess.run(f"sudo nmcli device set {interface} managed no", shell=True, 
                          stdout=output_redirect, stderr=output_redirect)
            subprocess.run(f"sudo pkill -f 'wpa_supplicant.*{interface}'", shell=True,
                          stdout=output_redirect, stderr=output_redirect)
            subprocess.run(f"sudo dhclient -r {interface}", shell=True, 
                          stdout=output_redirect, stderr=output_redirect)
            subprocess.run(f"sudo ip addr flush dev {interface}", shell=True,
                          stdout=output_redirect, stderr=output_redirect)
            subprocess.run(f"sudo ip route flush dev {interface}", shell=True,
                          stdout=output_redirect, stderr=output_redirect)
            subprocess.run(f"sudo rm -f /var/run/wpa_supplicant/*", shell=True,
                          stdout=output_redirect, stderr=output_redirect)
            time.sleep(1)
            
            # Step 2: Bring interface up
            log(f"Bringing {interface} up...", "wifi")
            subprocess.run(f"sudo ip link set {interface} up", shell=True,
                          stdout=output_redirect, stderr=output_redirect)
            time.sleep(0.5)
            
            # Step 3: Start wpa_supplicant
            if not self._start_wpa_supplicant(camera, interface, verbose, output_redirect):
                return False
            
            # Step 4: Wait for WiFi connection
            if not self._wait_for_wifi_connection(camera, interface, verbose):
                return False
            
            # Step 5: Setup IP addressing
            if not self._setup_ip_addressing(interface, verbose, output_redirect):
                return False
            
            # Step 6: Setup routing
            if not self._setup_routing(interface, verbose, output_redirect):
                return False
            
            # Step 7: Test connection and create controller
            return self._test_and_create_controller(camera, interface, verbose, output_redirect)
            
        except Exception as e:
            log(f"WiFi setup failed for {camera.camera_name}: {e}", "error")
            return False
  
    def _start_wpa_supplicant(self, camera: SingleGoProController, interface: str, 
                             verbose: bool = True, output_redirect=None) -> bool:
        """Unified wpa_supplicant startup"""
        wpa_config = f'''ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
network={{
    ssid="{camera.wifi_ssid}"
    psk="{camera.wifi_password}"
    key_mgmt=WPA-PSK
    priority=1
    scan_ssid=1
}}'''
        
        config_file = f"/tmp/gopro_{interface}.conf"
        with open(config_file, "w") as f:
            f.write(wpa_config)
        
        if verbose:
            print(f"[WPA] Starting wpa_supplicant on {interface}...")
        
        cmd = f"sudo wpa_supplicant -B -i {interface} -c {config_file} -D nl80211,wext"
        result = subprocess.run(cmd, shell=True, stdout=output_redirect, stderr=output_redirect, 
                               capture_output=(output_redirect is not None), text=True)
        
        if result.returncode != 0 and verbose:
            print(f"X wpa_supplicant failed on {interface}: {result.stderr if result.stderr else 'Unknown error'}")
        
        return result.returncode == 0
    
    def _wait_for_wifi_connection(self, camera: SingleGoProController, interface: str, 
                                 verbose: bool = True) -> bool:
        """Unified WiFi connection waiting"""
        if verbose:
            print(f"[WAIT] Waiting for WiFi connection on {interface}...")
        
        timeout = 10 if verbose else 8  # Shorter timeout for parallel execution
        
        for attempt in range(timeout):
            time.sleep(0.8 if verbose else 0.6)
            
            try:
                iwconfig_result = subprocess.run(f"iwconfig {interface}", shell=True, 
                                               capture_output=True, text=True)
                if iwconfig_result.returncode == 0:
                    # Check if actually connected
                    if camera.wifi_ssid in iwconfig_result.stdout and "Access Point:" in iwconfig_result.stdout:
                        if "Not-Associated" not in iwconfig_result.stdout:
                            if verbose:
                                print(f"[OK] Connected to {camera.wifi_ssid}")
                            return True
                
                if verbose and attempt % 3 == 0:
                    print(f"   ... attempt {attempt + 1}/{timeout}")
            except:
                pass
        
        if verbose:
            print(f"X Failed to connect to {camera.wifi_ssid}")
        return False
    
    def _setup_ip_addressing(self, interface: str, verbose: bool = True, output_redirect=None) -> bool:
        """Unified IP addressing setup"""
        if verbose:
            print(f"[DHCP] Trying DHCP on {interface}...")
        
        # Try DHCP with timeout
        try:
            dhcp_timeout = TIMEOUTS['dhcp'] if verbose else 3
            dhcp_result = subprocess.run(f"sudo dhclient -v {interface}", shell=True, 
                                       stdout=output_redirect, stderr=output_redirect,
                                       timeout=dhcp_timeout, capture_output=(output_redirect is not None), text=True)
            dhcp_success = dhcp_result.returncode == 0
        except subprocess.TimeoutExpired:
            if verbose:
                print(f"[WARN] DHCP timed out on {interface}, trying static IP...")
            dhcp_success = False
        
        if not dhcp_success:
            if verbose:
                print(f"[SETUP] Setting up static IP on {interface}...")
            static_ip = STATIC_IPS[interface]
            subprocess.run(f"sudo ip addr add {static_ip} dev {interface}", shell=True,
                          stdout=output_redirect, stderr=output_redirect)
            time.sleep(0.5)
        
        # Verify IP assignment
        ip_result = subprocess.run(f"ip addr show {interface}", shell=True, 
                                 capture_output=True, text=True)
        
        for line in ip_result.stdout.split('\n'):
            if "inet " in line and "127.0.0.1" not in line and "169.254" not in line:
                interface_ip = line.strip().split()[1].split('/')[0]
                if verbose:
                    print(f"[OK] {interface} has IP: {interface_ip}")
                return True
        
        if verbose:
            print(f"X No IP address assigned to {interface}")
        return False
    
    def _setup_routing(self, interface: str, verbose: bool = True, output_redirect=None) -> bool:
        """Unified routing setup"""
        if verbose:
            print(f"[ROUTE] Setting up enhanced routing for {GOPRO_IP} via {interface}...")
        
        # Remove existing routes
        subprocess.run(f"sudo ip route del {GOPRO_IP} 2>/dev/null", shell=True,
                      stdout=output_redirect, stderr=output_redirect)
        subprocess.run(f"sudo ip route del 10.5.5.0/24 2>/dev/null", shell=True,
                      stdout=output_redirect, stderr=output_redirect)
        
        # Add new routes with metrics
        metric = ROUTING_METRICS[interface]
        subprocess.run(f"sudo ip route add {GOPRO_IP} dev {interface} metric {metric}", shell=True,
                      stdout=output_redirect, stderr=output_redirect)
        subprocess.run(f"sudo ip route add 10.5.5.0/24 dev {interface} metric {metric}", shell=True,
                      stdout=output_redirect, stderr=output_redirect)
        
        time.sleep(1)
        return True
    
    def _test_and_create_controller(self, camera: SingleGoProController, interface: str,
                                   verbose: bool = True, output_redirect=None) -> bool:
        """Unified connection testing and controller creation"""
        if verbose:
            print(f"[CHECK] Testing {camera.camera_name} with enhanced routing...")
        
        test_cmd = f"curl --interface {interface} --connect-timeout 5 --max-time 10 http://{GOPRO_IP}:8080/gp/gpControl/status"
        test_result = subprocess.run(test_cmd, shell=True, stdout=output_redirect, stderr=output_redirect,
                                   capture_output=(output_redirect is not None), text=True)
        
        if test_result.returncode == 0:
            # For non-verbose mode, capture WiFiCameraController's verbose output
            if not verbose:
                old_stdout = sys.stdout
                sys.stdout = io.StringIO()
            
            try:
                wifi_ctrl = WiFiCameraController(camera.camera_name, interface, GOPRO_IP)
                self.wifi_controllers[camera.camera_id] = wifi_ctrl
                
                if verbose:
                    print(f"[OK] {camera.camera_name} connected via {interface}")
                    print(f"   Stored in wifi_controllers['{camera.camera_id}']")
                return True
            except Exception:
                return False
            finally:
                if not verbose:
                    sys.stdout = old_stdout
        else:
            if verbose:
                print(f"X {camera.camera_name} not responding")
            return False
  
    # MANUAL CONNECTION METHOD (uses unified method)
    def connect_to_wifi_interface(self, camera_id: str) -> bool:
        """Manual connect to specific camera's WiFi (uses unified method)"""
        if camera_id not in self.cameras:
            return False
        
        camera = self.cameras[camera_id]
        if not camera.wifi_ssid or not camera.wifi_password:
            print("X No WiFi credentials available")
            print("[HELP] Try enabling WiFi first with option 91 or individual camera WiFi enable")
            return False
        
        interface = camera.wifi_interface
        print(f"\n[CONNECT] Connecting {camera.camera_name} via {interface}")
        print(f"   Network: {camera.wifi_ssid}")
        print(f"   Camera ID: {camera_id}")
        
        try:
            # FIXED: Removed duplicate line
            return self._setup_wifi_connection(camera, interface, verbose=True)
        except Exception as e:
            logger.error(f"WiFi connection error for {camera.camera_name}: {e}")
            return False
    
    def show_network_debug(self):
        """Show detailed network debugging information"""
        print("\n[CHECK] Dual WiFi Network Debug:")
        print("-" * 50)
        
        for interface in ["wlan0", "wlan1"]:
            print(f"\n[WIFI] Interface: {interface}")
            self._show_interface_debug(interface)
        
        print("\n" + "-" * 50)
    
    def _show_interface_debug(self, interface: str):
        """Show debug info for a specific interface"""
        # Interface status
        try:
            result = subprocess.run(f"ip link show {interface}", shell=True, 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                status = "[OK] UP" if "UP" in result.stdout else "X DOWN"
                print(f"   Status: {status}")
            else:
                print(f"   Status: X NOT FOUND")
                return
        except:
            print(f"   Status: X ERROR")
            return
        
        # IP Address
        try:
            result = subprocess.run(f"ip addr show {interface}", shell=True, 
                                  capture_output=True, text=True)
            ip_found = False
            for line in result.stdout.split('\n'):
                if "inet " in line and "127.0.0.1" not in line:
                    ip = line.strip().split()[1].split('/')[0]
                    print(f"   IP: {ip}")
                    ip_found = True
                    break
            if not ip_found:
                print(f"   IP: X No IP assigned")
        except:
            print(f"   IP: X Error checking IP")
        
        # Connected network
        try:
            result = subprocess.run(f"iwconfig {interface}", shell=True, 
                                  capture_output=True, text=True)
            if "ESSID" in result.stdout:
                for line in result.stdout.split('\n'):
                    if "ESSID:" in line:
                        essid = line.split('ESSID:')[1].strip().strip('"')
                        print(f"   Network: {essid}")
                        break
            else:
                print(f"   Network: X Not connected")
        except:
            print(f"   Network: X Error checking")
    
    async def disconnect_all(self):
        """Disconnect all cameras with robust error handling"""
        print("[DISC] Disconnecting all cameras...")
        
        # Disconnect all cameras in parallel with individual error handling
        async def safe_disconnect(camera):
            try:
                await camera.disconnect()
                return True
            except Exception as e:
                logger.warning(f"[DISC] Error disconnecting {camera.camera_name}: {e}")
                return False
        
        if self.cameras:
            # Create disconnect tasks for all cameras
            disconnect_tasks = [safe_disconnect(camera) for camera in self.cameras.values()]
            
            try:
                # Run all disconnects in parallel with timeout
                results = await asyncio.wait_for(
                    asyncio.gather(*disconnect_tasks, return_exceptions=True), 
                    timeout=10.0
                )
                
                success_count = sum(1 for result in results if result is True)
                print(f"[DISC] Successfully disconnected {success_count}/{len(self.cameras)} cameras")
                
            except asyncio.TimeoutError:
                print("[DISC] Disconnect timeout - forcing cleanup")
            except Exception as e:
                print(f"[DISC] Disconnect error: {e}")
        
        # Clear all references
        self.cameras.clear()
        self.wifi_controllers.clear()
        print("[DISC] Cleanup completed")