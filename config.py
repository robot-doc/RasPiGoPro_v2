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
CONFIG_FILE = Path(__file__).parent / ".dual_wifi_gopro_config.json"

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
CURL_TIMEOUT = 10

# Show debugging information
SLEEP_MENU = 3.0
SHOW_DEBUGGING_INFO = "OFF" 

# I2C / PCF8574 configuration
I2C_BUS = 1

# INPUT modules (read-only)
PCF8574_INPUT_ADDRESSES = [0x38]    # your current input expander(s)

# OUTPUT modules (write-only / latched by us)
PCF8574_OUTPUT_ADDRESSES = [0x20]   # your new output expander

PCF8574_POLL_INTERVAL = 0.1  # seconds for live view refresh

# Output wiring semantics
# NOTE: Most PCF8574 “LED boards” are wired ACTIVE-LOW (0 = LED ON).
# Set this to True if your board is active-low, else False if active-high.
PCF8574_OUTPUT_ACTIVE_LOW = True

# Which output pin we toggle as a “BUSY” signal (0..7)
# True while: (1) cameras are recording in trigger mode AND (2) the combined video is still being saved
BUSY_OUTPUT_PIN = 7

# Hardware triggered recording (unchanged)
TRIGGER_INPUT = 7

RECORDING_TIME = 38.0 #Approx cycle time of robot
#RECORDING_TIME = 10.0
MIN_RECORDING_TIME = 1.0    # Minimum recording time in seconds
MAX_RECORDING_TIME = 300.0  # Maximum recording time in seconds (5 minutes)