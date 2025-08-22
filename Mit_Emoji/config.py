#!/usr/bin/env python3
"""
Configuration constants for GoPro Controller
"""

import logging
from pathlib import Path

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# BLE Characteristics for GoPro cameras
BLE_CHARACTERISTICS = {
    'wifi_ssid': "b5f90002-aa8d-11e3-9046-0002a5d5c51b",
    'wifi_password': "b5f90003-aa8d-11e3-9046-0002a5d5c51b", 
    'wifi_power': "b5f90004-aa8d-11e3-9046-0002a5d5c51b",
    'command': "b5f90072-aa8d-11e3-9046-0002a5d5c51b"
}

# WiFi interface assignments
INTERFACE_ASSIGNMENTS = {
    "camera_1": "wlan0",  # GoPro 3811 -> built-in WiFi
    "camera_2": "wlan1"   # Second camera -> USB WiFi
}

# Network configuration
GOPRO_IP = "10.5.5.9"
STATIC_IPS = {
    "wlan0": "10.5.5.100/24",  # Camera 1
    "wlan1": "10.5.5.101/24"   # Camera 2
}

ROUTING_METRICS = {
    "wlan0": 10,  # Lower metric = higher priority
    "wlan1": 20
}

# File paths
CONFIG_FILE = Path.home() / ".dual_wifi_gopro_config.json"

# Timeouts and delays
TIMEOUTS = {
    'bluetooth_discover': 15,
    'bluetooth_connect': 10,
    'wifi_connect': 15,
    'dhcp': 5,
    'http_request': 10,
    'wifi_enable_delay': 4
}

# GoPro device detection patterns
GOPRO_DEVICE_PATTERNS = ["GoPro", "GP", "HERO", "Cam"]

# HTTP timeouts
HTTP_TIMEOUT = 8
CURL_TIMEOUT = 10