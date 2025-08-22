#!/usr/bin/env python3
"""
Individual GoPro Camera Controller via Bluetooth
Fixed version with robust disconnect error handling
"""

import asyncio
import logging
from typing import Optional
from bleak import BleakClient
from bleak.backends.device import BLEDevice

from config import BLE_CHARACTERISTICS, TIMEOUTS

logger = logging.getLogger(__name__)

class SingleGoProController:
    """Controller for individual GoPro camera with assigned WiFi interface"""
    
    def __init__(self, camera_id: str, camera_name: str = "GoPro", wifi_interface: str = "wlan0"):
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.wifi_interface = wifi_interface
        self.device = None
        self.client = None
        self.wifi_ssid = None
        self.wifi_password = None
        self.connected = False
        
        # BLE Characteristics from config
        self.wifi_ssid_char = BLE_CHARACTERISTICS['wifi_ssid']
        self.wifi_password_char = BLE_CHARACTERISTICS['wifi_password']
        self.wifi_power_char = BLE_CHARACTERISTICS['wifi_power']
        self.command_char = BLE_CHARACTERISTICS['command']
    
    async def connect(self, device: BLEDevice) -> bool:
        """Connect to this GoPro via Bluetooth"""
        try:
            self.client = BleakClient(device)
            await self.client.connect()
            
            if self.client.is_connected:
                self.device = device
                self.connected = True
                await self.discover_services()
                logger.info(f"[OK] {self.camera_name} connected via Bluetooth")
                return True
            
            return False
        except Exception as e:
            logger.error(f"X {self.camera_name} connection failed: {e}")
            return False
    
    async def discover_services(self):
        """Discover BLE services"""
        try:
            services = list(self.client.services)
            logger.info(f"[CONFIG] {self.camera_name}: {len(services)} services discovered")
        except Exception as e:
            logger.warning(f"Service discovery failed for {self.camera_name}: {e}")
    
    async def enable_wifi(self) -> bool:
        """Enable WiFi on this camera"""
        try:
            logger.info(f"[WPA] Enabling WiFi on {self.camera_name}")
            await self.client.write_gatt_char(self.wifi_power_char, bytes([0x01]))
            await asyncio.sleep(TIMEOUTS['wifi_enable_delay'])
            
            # Read WiFi credentials
            return await self.read_wifi_credentials()
        except Exception as e:
            logger.error(f"WiFi enable failed for {self.camera_name}: {e}")
            return False
    
    async def read_wifi_credentials(self) -> bool:
        """Read WiFi credentials from camera"""
        try:
            # Read SSID
            ssid_data = await self.client.read_gatt_char(self.wifi_ssid_char)
            self.wifi_ssid = ssid_data.decode('utf-8').rstrip('\x00')
            
            # Read Password
            password_data = await self.client.read_gatt_char(self.wifi_password_char)
            self.wifi_password = password_data.decode('utf-8').rstrip('\x00')
            
            logger.info(f"[WIFI] {self.camera_name} WiFi: {self.wifi_ssid} -> {self.wifi_interface}")
            return True
        except Exception as e:
            logger.error(f"Failed to read WiFi credentials for {self.camera_name}: {e}")
            return False
    
    async def send_command(self, command_bytes: bytes, description: str = "") -> bool:
        """Send command to camera via Bluetooth"""
        try:
            if not self.client or not self.client.is_connected:
                return False
            
            await self.client.write_gatt_char(self.command_char, command_bytes)
            logger.info(f"[CMD] {self.camera_name}: {description}")
            await asyncio.sleep(1)
            return True
        except Exception as e:
            logger.error(f"Command failed for {self.camera_name}: {e}")
            return False
    
    async def take_photo_bt(self) -> bool:
        """Take photo via Bluetooth"""
        await self.send_command(bytes([0x02, 0x02, 0x01]), "Set photo mode")
        await asyncio.sleep(1)
        return await self.send_command(bytes([0x02, 0x01, 0x01]), "Take photo")
    
    async def start_recording_bt(self) -> bool:
        """Start recording via Bluetooth"""
        await self.send_command(bytes([0x02, 0x02, 0x00]), "Set video mode")
        await asyncio.sleep(1)
        return await self.send_command(bytes([0x02, 0x01, 0x01]), "Start recording")
    
    async def stop_recording_bt(self) -> bool:
        """Stop recording via Bluetooth"""
        return await self.send_command(bytes([0x02, 0x01, 0x00]), "Stop recording")
    
    async def disconnect(self):
        """Disconnect Bluetooth with robust error handling"""
        if not self.client:
            return
        
        try:
            if self.client.is_connected:
                logger.info(f"[DISC] Disconnecting {self.camera_name}...")
                
                # Set a timeout for disconnect to prevent hanging
                await asyncio.wait_for(self.client.disconnect(), timeout=5.0)
                logger.info(f"[OK] {self.camera_name} disconnected cleanly")
            else:
                logger.info(f"[INFO] {self.camera_name} already disconnected")
                
        except asyncio.TimeoutError:
            logger.warning(f"[TIMEOUT] Disconnect timeout for {self.camera_name} - forcing disconnect")
            self.connected = False
            self.client = None
            
        except EOFError:
            logger.warning(f"[EOF] Connection already closed for {self.camera_name}")
            self.connected = False
            self.client = None
            
        except Exception as e:
            logger.warning(f"[DISC] Disconnect error for {self.camera_name}: {e}")
            # Force disconnect state even if error occurs
            self.connected = False
            self.client = None
        
        finally:
            # Always ensure we're marked as disconnected
            self.connected = False