#!/usr/bin/env python3
"""
PCF8574 I/O expander manager (read inputs)
- Supports multiple PCF8574(P) devices on the same I2C bus
- Safe "input" usage by writing 1s before reads (quasi-bidirectional)
"""

import time
from typing import Dict, List, Optional

try:
    from smbus2 import SMBus
except ImportError:
    SMBus = None


class PCF8574Device:
    def __init__(self, bus: int, address: int, name: Optional[str] = None):
        self.bus_num = bus
        self.address = address
        self.name = name or f"PCF8574@0x{address:02X}"
        self._bus: Optional[SMBus] = None

    def _ensure_bus(self) -> bool:
        if SMBus is None:
            return False
        if self._bus is None:
            try:
                self._bus = SMBus(self.bus_num)
                # Write all 1s so pins float high => can be used as inputs
                self._bus.write_byte(self.address, 0xFF)
                time.sleep(0.01)
            except Exception:
                self._bus = None
                return False
        return True

    def read_raw(self) -> Optional[int]:
        """Return 8-bit value or None on error. Bit=1 means pin HIGH, 0 means LOW."""
        if not self._ensure_bus():
            return None
        try:
            # Ensure inputs by writing 1s (recommended pattern for PCF8574 inputs)
            self._bus.write_byte(self.address, 0xFF)
            time.sleep(0.002)
            value = self._bus.read_byte(self.address)  # 0..255
            return value
        except Exception:
            return None

    def read_inputs(self) -> Optional[Dict[int, int]]:
        """Return dict {pin: level} with pin in 0..7 and level 0/1, or None on error."""
        raw = self.read_raw()
        if raw is None:
            return None
        return {pin: (raw >> pin) & 0x01 for pin in range(8)}

    def close(self):
        if self._bus:
            try:
                self._bus.close()
            except Exception:
                pass
            self._bus = None


class PCF8574Manager:
    def __init__(self, bus: int, addresses: List[int]):
        self.bus_num = bus
        self.devices = [PCF8574Device(bus, addr) for addr in addresses]

    def snapshot(self) -> Dict[str, Optional[Dict[int, int]]]:
        """Read all devices once."""
        out = {}
        for dev in self.devices:
            out[dev.name] = dev.read_inputs()
        return out

    def close(self):
        for dev in self.devices:
            dev.close()
