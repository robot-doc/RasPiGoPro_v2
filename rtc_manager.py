#!/usr/bin/env python3
"""
RTC Manager for Raspberry Pi with DS3231
- Handles kernel driver conflicts (UU in i2cdetect)
- Sync system time from RTC on startup
- If NTP available, sync system time from NTP and update RTC
- Falls back to hwclock if direct I2C access fails
2024.12.17 - Fixed version
"""

import subprocess
import datetime
import logging
import time
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

# DS3231 I2C address
DS3231_ADDR = 0x68

# DS3231 Registers
REG_SECONDS = 0x00
REG_MINUTES = 0x01
REG_HOURS   = 0x02
REG_DAY     = 0x03
REG_DATE    = 0x04
REG_MONTH   = 0x05
REG_YEAR    = 0x06
REG_TEMPERATURE_MSB = 0x11
REG_TEMPERATURE_LSB = 0x12


class RTCManager:
    """Manages DS3231 RTC with kernel driver conflict handling"""
    
    def __init__(self):
        self.bus = None
        self.use_hwclock = False
        self.rtc_available = self._initialize_rtc()
    
    def _initialize_rtc(self) -> bool:
        """Initialize RTC connection, handling kernel driver conflicts"""
        
        # First, check if hwclock works (kernel driver is loaded)
        if self._check_hwclock():
            logging.info("[RTC] Using hwclock (kernel driver interface)")
            self.use_hwclock = True
            return True
        
        # Try direct I2C access
        try:
            from smbus2 import SMBus
            
            # Try with force=True to override kernel driver if present
            try:
                self.bus = SMBus(1, force=True)
                # Test read
                self.bus.read_byte_data(DS3231_ADDR, REG_SECONDS)
                logging.info("[RTC] Direct I2C access established (forced)")
                return True
            except:
                # Try without force
                self.bus = SMBus(1)
                self.bus.read_byte_data(DS3231_ADDR, REG_SECONDS)
                logging.info("[RTC] Direct I2C access established")
                return True
                
        except OSError as e:
            if e.errno == 16:  # Device busy
                logging.warning("[RTC] I2C device busy, trying to unload kernel module")
                if self._unload_kernel_module():
                    # Retry after unloading module
                    try:
                        from smbus2 import SMBus
                        self.bus = SMBus(1)
                        self.bus.read_byte_data(DS3231_ADDR, REG_SECONDS)
                        logging.info("[RTC] Direct I2C access established after unloading module")
                        return True
                    except:
                        pass
        except ImportError:
            logging.error("[RTC] smbus2 not installed: pip install smbus2")
        except Exception as e:
            logging.error(f"[RTC] Initialization failed: {e}")
        
        return False
    
    def _check_hwclock(self) -> bool:
        """Check if hwclock command is available and working"""
        try:
            result = subprocess.run(
                ["sudo", "hwclock", "-r"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                return True
        except:
            pass
        return False
    
    def _unload_kernel_module(self) -> bool:
        """Try to unload the rtc-ds1307 kernel module"""
        try:
            # Common RTC modules that might be loaded
            modules = ["rtc_ds1307", "rtc-ds1307", "rtc_ds3231", "rtc-ds3231"]
            
            for module in modules:
                subprocess.run(
                    ["sudo", "rmmod", module],
                    capture_output=True,
                    stderr=subprocess.DEVNULL
                )
            
            time.sleep(0.5)
            return True
        except:
            return False
    
    def _bcd_to_dec(self, bcd: int) -> int:
        """Convert BCD to decimal"""
        return (bcd & 0x0F) + ((bcd >> 4) * 10)
    
    def _dec_to_bcd(self, dec: int) -> int:
        """Convert decimal to BCD"""
        return ((dec // 10) << 4) + (dec % 10)
    
    def read_rtc_time(self) -> datetime.datetime:
        """Read time from RTC using appropriate method"""
        if not self.rtc_available:
            return None
        
        if self.use_hwclock:
            return self._read_time_hwclock()
        else:
            return self._read_time_i2c()
    
    def _read_time_hwclock(self) -> datetime.datetime:
        """Read RTC time using hwclock command"""
        try:
            result = subprocess.run(
                ["sudo", "hwclock", "-r"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                # Parse hwclock output
                # Format: "2024-12-17 15:30:45.123456+01:00"
                time_str = result.stdout.strip()
                # Remove timezone and microseconds for parsing
                if '.' in time_str:
                    time_str = time_str.split('.')[0]
                if '+' in time_str or '-' in time_str[-6:]:
                    time_str = time_str[:19]
                
                return datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logging.error(f"[RTC] hwclock read failed: {e}")
        return None
    
    def _read_time_i2c(self) -> datetime.datetime:
        """Read RTC time using direct I2C access"""
        if not self.bus:
            return None
        
        try:
            data = self.bus.read_i2c_block_data(DS3231_ADDR, REG_SECONDS, 7)
            seconds = self._bcd_to_dec(data[0] & 0x7F)
            minutes = self._bcd_to_dec(data[1])
            hours   = self._bcd_to_dec(data[2] & 0x3F)
            day     = self._bcd_to_dec(data[4])
            month   = self._bcd_to_dec(data[5] & 0x1F)
            year    = self._bcd_to_dec(data[6]) + 2000
            return datetime.datetime(year, month, day, hours, minutes, seconds)
        except Exception as e:
            logging.error(f"[RTC] I2C read failed: {e}")
            return None
    
    def write_rtc_time(self, dt: datetime.datetime) -> bool:
        """Write time to RTC using appropriate method"""
        if not self.rtc_available:
            return False
        
        if self.use_hwclock:
            return self._write_time_hwclock(dt)
        else:
            return self._write_time_i2c(dt)
    
    def _write_time_hwclock(self, dt: datetime.datetime) -> bool:
        """Set RTC time using hwclock command"""
        try:
            # First set system time
            timestr = dt.strftime('%Y-%m-%d %H:%M:%S')
            subprocess.run(["sudo", "date", "-s", timestr], check=False)
            
            # Then sync RTC from system time
            result = subprocess.run(
                ["sudo", "hwclock", "-w"],
                capture_output=True,
                timeout=2
            )
            return result.returncode == 0
        except Exception as e:
            logging.error(f"[RTC] hwclock write failed: {e}")
            return False
    
    def _write_time_i2c(self, dt: datetime.datetime) -> bool:
        """Write time to RTC using direct I2C access"""
        if not self.bus:
            return False
        
        try:
            data = [
                self._dec_to_bcd(dt.second),
                self._dec_to_bcd(dt.minute),
                self._dec_to_bcd(dt.hour),
                self._dec_to_bcd(dt.isoweekday()),
                self._dec_to_bcd(dt.day),
                self._dec_to_bcd(dt.month),
                self._dec_to_bcd(dt.year - 2000)
            ]
            self.bus.write_i2c_block_data(DS3231_ADDR, REG_SECONDS, data)
            return True
        except Exception as e:
            logging.error(f"[RTC] I2C write failed: {e}")
            return False
    
    def get_temperature(self) -> float:
        """Read temperature from DS3231 (±3°C accuracy)"""
        if not self.rtc_available or self.use_hwclock:
            return None
        
        try:
            msb = self.bus.read_byte_data(DS3231_ADDR, REG_TEMPERATURE_MSB)
            lsb = self.bus.read_byte_data(DS3231_ADDR, REG_TEMPERATURE_LSB)
            
            # Calculate temperature (resolution is 0.25°C)
            temp = msb + (lsb >> 6) * 0.25
            
            # Handle negative temperatures
            if msb & 0x80:
                temp = temp - 256
            
            return temp
        except:
            return None
    
    def cleanup(self):
        """Clean up resources"""
        if self.bus:
            try:
                self.bus.close()
            except:
                pass


def set_system_time(dt: datetime.datetime):
    """Set system time"""
    timestr = dt.strftime('%Y-%m-%d %H:%M:%S')
    logging.info(f"[SYS] Setting system time: {timestr}")
    subprocess.run(["sudo", "date", "-s", timestr], check=False)


def get_ntp_time(server: str = "pool.ntp.org", timeout: int = 3):
    """Get time from NTP server"""
    try:
        # Try using ntpdate first (more reliable)
        result = subprocess.run(
            ["sudo", "ntpdate", "-q", server],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode == 0:
            # Parse ntpdate output to get time
            # Just set system time directly with ntpdate
            result = subprocess.run(
                ["sudo", "ntpdate", "-s", server],
                capture_output=True,
                timeout=timeout
            )
            if result.returncode == 0:
                return datetime.datetime.now()
    except:
        pass
    
    # Fallback to ntplib if available
    try:
        import ntplib
        client = ntplib.NTPClient()
        response = client.request(server, version=3, timeout=timeout)
        return datetime.datetime.utcfromtimestamp(response.tx_time)
    except Exception as e:
        logging.warning(f"[NTP] Could not get NTP time: {e}")
        return None


def sync_time():
    """Main sync function - sync system time from RTC, then try NTP"""
    try:
        rtc = RTCManager()
        
        if not rtc.rtc_available:
            logging.error("[RTC] RTC not available")
            logging.info("[RTC] Check connection: sudo i2cdetect -y 1")
            logging.info("[RTC] Install: pip install smbus2")
            return
        
        # Read RTC time
        rtc_time = rtc.read_rtc_time()
        if rtc_time:
            logging.info(f"[RTC] Current RTC time: {rtc_time}")
            
            # Set system time from RTC
            set_system_time(rtc_time)
        else:
            logging.warning("[RTC] Could not read RTC time")
        
        # Try NTP sync
        logging.info("[NTP] Attempting NTP sync...")
        ntp_time = get_ntp_time()
        if ntp_time:
            logging.info(f"[NTP] Got NTP time: {ntp_time}")
            
            # Update RTC with NTP time
            if rtc.write_rtc_time(ntp_time):
                logging.info("[RTC] RTC updated from NTP")
            else:
                logging.warning("[RTC] Could not update RTC")
        else:
            logging.info("[NTP] No NTP sync available, keeping RTC time")
        
        # Show temperature if available
        temp = rtc.get_temperature()
        if temp:
            logging.info(f"[RTC] Temperature: {temp:.1f}°C")
        
        # Cleanup
        rtc.cleanup()
        
    except Exception as e:
        logging.error(f"[RTC] Sync failed: {e}")


def show_status():
    """Show detailed RTC status"""
    try:
        rtc = RTCManager()
        
        if not rtc.rtc_available:
            print("[ERROR] RTC not available")
            return
        
        print("\n" + "=" * 50)
        print("DS3231 RTC STATUS")
        print("=" * 50)
        
        # RTC time
        rtc_time = rtc.read_rtc_time()
        if rtc_time:
            print(f"RTC Time:    {rtc_time}")
        
        # System time
        sys_time = datetime.datetime.now()
        print(f"System Time: {sys_time}")
        
        # Time drift
        if rtc_time:
            drift = abs((rtc_time - sys_time).total_seconds())
            print(f"Drift:       {drift:.1f} seconds")
        
        # Temperature
        temp = rtc.get_temperature()
        if temp:
            print(f"Temperature: {temp:.1f}°C")
        
        # Interface type
        if rtc.use_hwclock:
            print("Interface:   hwclock (kernel driver)")
        else:
            print("Interface:   Direct I2C")
        
        print("=" * 50)
        
        rtc.cleanup()
        
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    # If run directly, perform sync
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        show_status()
    else:
        sync_time()