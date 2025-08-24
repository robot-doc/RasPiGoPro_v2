#!/usr/bin/env python3
"""
PCF8574 I/O expander manager
- Supports multiple INPUT devices (safe read pattern)
- Supports multiple OUTPUT devices with latched writes
"""

import time
from typing import Dict, List, Optional, Tuple

try:
    from smbus2 import SMBus
except ImportError:
    SMBus = None


# -------------------- INPUT device (unchanged behavior) --------------------

class PCF8574Device:
    def __init__(self, bus: int, address: int, name: Optional[str] = None):
        self.bus_num = bus
        self.address = address
        self.name = name or f"PCF8574_IN@0x{address:02X}"
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


# -------------------- OUTPUT device (new) --------------------

class PCF8574OutputDevice:
    """
    Simple latched-writes helper for a PCF8574 used as OUTPUTS.
    - We maintain a local 8-bit latch (1 bit per pin).
    - Writing 1 on PCF8574 'releases' the line (weak-high via pull-up).
      On typical LED boards, that means LED OFF (active-low).
    """
    def __init__(self, bus: int, address: int, active_low: bool = True, name: Optional[str] = None):
        self.bus_num = bus
        self.address = address
        self.active_low = active_low
        self.name = name or f"PCF8574_OUT@0x{address:02X}"
        self._bus: Optional[SMBus] = None
        self._latch: int = 0xFF  # start as all released (HIGH)

    def _ensure_bus(self) -> bool:
        if SMBus is None:
            return False
        if self._bus is None:
            try:
                self._bus = SMBus(self.bus_num)
                # Initialize hardware to current latch (all high by default)
                self._bus.write_byte(self.address, self._latch)
                time.sleep(0.002)
            except Exception:
                self._bus = None
                return False
        return True

    def _apply(self) -> bool:
        if not self._ensure_bus():
            return False
        try:
            self._bus.write_byte(self.address, self._latch & 0xFF)
            return True
        except Exception:
            return False

    def set_all(self, logical_high: bool) -> bool:
        """
        Set all pins to logical_high (True/False) according to active_low.
        """
        # Map logical level to physical bit for the expander
        phys_bit = 0 if (logical_high and self.active_low) else (1 if (logical_high and not self.active_low) else (1 if self.active_low else 0))
        # phys_bit meaning:
        #   active_low=True:  logical True -> drive LOW (0), logical False -> release HIGH (1)
        #   active_low=False: logical True -> drive HIGH (1), logical False -> drive LOW (0)
        self._latch = 0x00 if phys_bit == 0 else 0xFF
        return self._apply()

    def set_pin(self, pin: int, logical_high: bool) -> bool:
        """
        Set one pin to logical_high (True/False) according to active_low.
        """
        if not (0 <= pin <= 7):
            return False

        # Determine physical bit to write
        want_low = (logical_high and self.active_low) or (not logical_high and not self.active_low)
        if want_low:
            # drive LOW -> clear bit
            self._latch &= ~(1 << pin)
        else:
            # drive/release HIGH -> set bit
            self._latch |= (1 << pin)

        return self._apply()

    def close(self):
        if self._bus:
            try:
                self._bus.close()
            except Exception:
                pass
            self._bus = None


# -------------------- Manager for both INPUTS and OUTPUTS --------------------

class PCF8574Manager:
    def __init__(self, bus: int,
                 input_addresses: List[int],
                 output_addresses: Optional[List[int]] = None,
                 output_active_low: bool = True):
        self.bus_num = bus
        self.input_devices = [PCF8574Device(bus, addr) for addr in (input_addresses or [])]
        self.output_devices = [PCF8574OutputDevice(bus, addr, active_low=output_active_low)
                               for addr in (output_addresses or [])]

    # ----- INPUT API -----
    def snapshot_inputs(self) -> Dict[str, Optional[Dict[int, int]]]:
        """Read all INPUT devices once."""
        out = {}
        for dev in self.input_devices:
            out[dev.name] = dev.read_inputs()
        return out

    # ----- OUTPUT API -----
    def set_output_pin(self, device_index: int, pin: int, value: bool) -> bool:
        """Set a single output pin on a given OUTPUT device."""
        if device_index < 0 or device_index >= len(self.output_devices):
            return False
        return self.output_devices[device_index].set_pin(pin, value)

    def set_output_all(self, device_index: int, value: bool) -> bool:
        """Set all 8 outputs at once on a given OUTPUT device."""
        if device_index < 0 or device_index >= len(self.output_devices):
            return False
        return self.output_devices[device_index].set_all(value)

    def close(self):
        for dev in self.input_devices:
            dev.close()
        for dev in self.output_devices:
            dev.close()