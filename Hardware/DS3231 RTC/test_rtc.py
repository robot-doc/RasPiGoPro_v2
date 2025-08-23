#!/usr/bin/env python3
"""
Test script for DS3231 RTC on Raspberry Pi
Tests different access methods and provides diagnostic information
"""

import subprocess
import sys
import time
import datetime

def test_i2cdetect():
    """Check if RTC is visible on I2C bus"""
    print("\n[1] Checking I2C devices...")
    print("-" * 40)
    
    result = subprocess.run(["i2cdetect", "-y", "1"], capture_output=True, text=True)
    print(result.stdout)
    
    if "UU" in result.stdout:
        print("✓ RTC detected at 0x68 (kernel driver loaded)")
        return "kernel"
    elif "68" in result.stdout:
        print("✓ RTC detected at 0x68 (no kernel driver)")
        return "direct"
    else:
        print("✗ RTC not detected at 0x68")
        return None

def test_hwclock():
    """Test hwclock command"""
    print("\n[2] Testing hwclock access...")
    print("-" * 40)
    
    try:
        result = subprocess.run(["sudo", "hwclock", "-r"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            print(f"✓ hwclock works: {result.stdout.strip()}")
            return True
        else:
            print(f"✗ hwclock failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"✗ hwclock error: {e}")
        return False

def test_kernel_module():
    """Check loaded kernel modules"""
    print("\n[3] Checking kernel modules...")
    print("-" * 40)
    
    result = subprocess.run(["lsmod"], capture_output=True, text=True)
    rtc_modules = []
    
    for line in result.stdout.split('\n'):
        if 'rtc' in line.lower() or 'ds1307' in line.lower() or 'ds3231' in line.lower():
            rtc_modules.append(line.split()[0])
    
    if rtc_modules:
        print(f"✓ RTC modules loaded: {', '.join(rtc_modules)}")
    else:
        print("✗ No RTC kernel modules loaded")
    
    return rtc_modules

def test_direct_i2c():
    """Test direct I2C access"""
    print("\n[4] Testing direct I2C access...")
    print("-" * 40)
    
    try:
        from smbus2 import SMBus
    except ImportError:
        print("✗ smbus2 not installed")
        print("  Install with: pip install smbus2")
        return False
    
    # Try without force
    try:
        bus = SMBus(1)
        data = bus.read_byte_data(0x68, 0x00)
        bus.close()
        print(f"✓ Direct I2C access works (seconds register: 0x{data:02x})")
        return True
    except OSError as e:
        if e.errno == 16:
            print("✗ Device busy (kernel driver using it)")
            
            # Try with force
            try:
                bus = SMBus(1, force=True)
                data = bus.read_byte_data(0x68, 0x00)
                bus.close()
                print(f"✓ Forced I2C access works (seconds register: 0x{data:02x})")
                return True
            except Exception as e2:
                print(f"✗ Forced I2C also failed: {e2}")
                return False
        else:
            print(f"✗ I2C error: {e}")
            return False
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False

def test_rtc_manager():
    """Test the RTCManager class"""
    print("\n[5] Testing RTCManager...")
    print("-" * 40)
    
    try:
        import rtc_manager
        
        rtc = rtc_manager.RTCManager()
        if rtc.rtc_available:
            print("✓ RTCManager initialized successfully")
            
            # Read time
            rtc_time = rtc.read_rtc_time()
            if rtc_time:
                print(f"  RTC time: {rtc_time}")
            
            # Read temperature
            temp = rtc.get_temperature()
            if temp:
                print(f"  Temperature: {temp:.1f}°C")
            
            # Show interface type
            if rtc.use_hwclock:
                print("  Using: hwclock (kernel interface)")
            else:
                print("  Using: Direct I2C")
            
            rtc.cleanup()
            return True
        else:
            print("✗ RTCManager initialization failed")
            return False
            
    except Exception as e:
        print(f"✗ RTCManager error: {e}")
        return False

def test_time_sync():
    """Test time synchronization"""
    print("\n[6] Testing time sync...")
    print("-" * 40)
    
    try:
        import rtc_manager
        
        print("Current system time:", datetime.datetime.now())
        print("Syncing...")
        
        rtc_manager.sync_time()
        
        print("New system time:", datetime.datetime.now())
        return True
        
    except Exception as e:
        print(f"✗ Sync error: {e}")
        return False

def suggest_fixes(i2c_status, hwclock_works, modules, direct_works):
    """Suggest fixes based on test results"""
    print("\n" + "=" * 50)
    print("RECOMMENDATIONS")
    print("=" * 50)
    
    if i2c_status is None:
        print("\n⚠ RTC not detected on I2C bus!")
        print("  1. Check wiring:")
        print("     - VCC → 3.3V (Pin 1)")
        print("     - GND → Ground (Pin 6)")
        print("     - SDA → GPIO 2 (Pin 3)")
        print("     - SCL → GPIO 3 (Pin 5)")
        print("  2. Enable I2C: sudo raspi-config")
        print("  3. Check with: sudo i2cdetect -y 1")
    
    elif i2c_status == "kernel" and not hwclock_works:
        print("\n⚠ Kernel driver loaded but hwclock not working!")
        print("  Try:")
        print("  1. sudo modprobe rtc_ds1307")
        print("  2. echo ds3231 0x68 | sudo tee /sys/class/i2c-adapter/i2c-1/new_device")
        print("  3. sudo hwclock -r")
    
    elif i2c_status == "kernel" and hwclock_works:
        print("\n✓ Everything working! RTC is accessible via hwclock.")
        print("  The fixed rtc_manager.py will use hwclock automatically.")
    
    elif i2c_status == "direct" and direct_works:
        print("\n✓ Direct I2C access works!")
        print("  You can optionally load the kernel driver:")
        print("  1. sudo modprobe rtc_ds1307")
        print("  2. echo ds3231 0x68 | sudo tee /sys/class/i2c-adapter/i2c-1/new_device")
    
    elif i2c_status == "direct" and not direct_works:
        print("\n⚠ RTC visible but I2C access failed!")
        print("  Try:")
        print("  1. Check permissions: sudo usermod -a -G i2c $USER")
        print("  2. Reboot")
        print("  3. Install: pip install smbus2")

def main():
    print("=" * 50)
    print("DS3231 RTC DIAGNOSTIC TEST")
    print("=" * 50)
    
    # Run tests
    i2c_status = test_i2cdetect()
    hwclock_works = test_hwclock()
    modules = test_kernel_module()
    direct_works = test_direct_i2c()
    rtc_manager_works = test_rtc_manager()
    
    # Summary
    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)
    print(f"I2C Detection:    {'✓' if i2c_status else '✗'}")
    print(f"hwclock:          {'✓' if hwclock_works else '✗'}")
    print(f"Kernel modules:   {'✓' if modules else '✗'}")
    print(f"Direct I2C:       {'✓' if direct_works else '✗'}")
    print(f"RTCManager:       {'✓' if rtc_manager_works else '✗'}")
    
    # Suggestions
    suggest_fixes(i2c_status, hwclock_works, modules, direct_works)
    
    # Optional time sync test
    print("\n" + "=" * 50)
    response = input("Test time synchronization? (y/n): ")
    if response.lower() == 'y':
        test_time_sync()
    
    print("\nTest complete!")

if __name__ == "__main__":
    main()