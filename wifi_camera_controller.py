#!/usr/bin/env python3
"""
WiFi Camera Controller for GoPro via HTTP API
"""

import json
import logging
import subprocess
import time
from typing import Optional

from config import GOPRO_IP, CURL_TIMEOUT

logger = logging.getLogger(__name__)

class WiFiCameraController:
    """Enhanced WiFi controller for individual camera on specific interface"""
    
    def __init__(self, camera_name: str, wifi_interface: str, ip: str = GOPRO_IP):
        self.camera_name = camera_name
        self.wifi_interface = wifi_interface
        self.ip = ip
        self.base_url = f"http://{ip}:8080"
        
        # Store interface IP for debugging
        self.interface_ip = self._get_interface_ip()
        
        print(f"[SETUP] WiFi Controller created for {camera_name}")
        print(f"   Interface: {wifi_interface}")
        print(f"   Interface IP: {self.interface_ip}")
        print(f"   Target GoPro IP: {ip}")
    
    def _get_interface_ip(self) -> Optional[str]:
        """Get IP address of the assigned interface"""
        try:
            result = subprocess.run(f"ip addr show {self.wifi_interface}", 
                                  shell=True, capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if "inet " in line and "127.0.0.1" not in line and "169.254" not in line:
                    return line.strip().split()[1].split('/')[0]
        except:
            pass
        return None
    
    def _make_request(self, url: str, action_description: str = "") -> bool:
        """Make HTTP request with interface-specific routing and debugging"""
        print(f"[DHCP] {self.camera_name}: {action_description}")
        print(f"   URL: {url}")
        print(f"   Via interface: {self.wifi_interface} ({self.interface_ip})")
        
        try:
            # Use curl with explicit interface binding for more reliable routing
            curl_cmd = f"curl --interface {self.wifi_interface} --connect-timeout 5 --max-time {CURL_TIMEOUT} -s '{url}'"
            result = subprocess.run(curl_cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"   [OK] Success via {self.wifi_interface}")
                return True
            else:
                print(f"   X Failed via {self.wifi_interface}: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"   X Exception: {e}")
            return False
    
    def _make_request_with_response(self, url: str, action_description: str = "") -> Optional[str]:
        """Make HTTP request and return response data"""
        print(f"[STATUS] {self.camera_name}: {action_description}")
        print(f"   Via interface: {self.wifi_interface}")
        
        try:
            curl_cmd = f"curl --interface {self.wifi_interface} --connect-timeout 5 --max-time {CURL_TIMEOUT} -s '{url}'"
            result = subprocess.run(curl_cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                return result.stdout
            else:
                print(f"   X Request failed: {result.stderr}")
                return None
        except Exception as e:
            print(f"   X Exception: {e}")
            return None
    
    def test_connection(self) -> bool:
        """Test connection to camera"""
        return self._make_request(f"{self.base_url}/gp/gpControl/status", "Testing connection")
    
    def get_status(self) -> dict:
        """Get camera status with debugging"""
        response = self._make_request_with_response(f"{self.base_url}/gp/gpControl/status", "Getting status")
        
        if response:
            try:
                return json.loads(response)
            except json.JSONDecodeError as e:
                print(f"   X JSON decode error: {e}")
                return {}
        return {}
    
    def take_photo(self) -> bool:
        """Take photo with explicit interface routing"""
        # Set photo mode first
        if not self._make_request(f"{self.base_url}/gp/gpControl/command/mode?p=1", "Setting photo mode"):
            return False
        
        time.sleep(0.5)
        
        # Take photo
        return self._make_request(f"{self.base_url}/gp/gpControl/command/shutter?p=1", "Taking photo")
    
    def start_recording(self) -> bool:
        """Start recording with explicit interface routing"""
        # Set video mode first
        if not self._make_request(f"{self.base_url}/gp/gpControl/command/mode?p=0", "Setting video mode"):
            return False
        
        time.sleep(0.5)
        
        # Start recording
        return self._make_request(f"{self.base_url}/gp/gpControl/command/shutter?p=1", "Starting recording")
    
    def stop_recording(self) -> bool:
        """Stop recording with explicit interface routing"""
        return self._make_request(f"{self.base_url}/gp/gpControl/command/shutter?p=0", "Stopping recording")

    def delete_all_media(self) -> bool:
        """
        Delete ALL media on the camera's SD card over Wi‑Fi.
        Uses OpenGoPro endpoint: /gp/gpControl/command/storage/delete/all
        """
        url = f"{self.base_url}/gp/gpControl/command/storage/delete/all"
        return self._make_request(url, "Deleting ALL media on camera")