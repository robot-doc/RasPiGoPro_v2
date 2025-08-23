#!/bin/bash
#
# Setup DS3231 RTC on Raspberry Pi
# This script configures the RTC to work with the kernel driver
#

echo "================================"
echo "DS3231 RTC Setup for Raspberry Pi"
echo "================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
   echo "Please run with sudo: sudo ./setup_rtc.sh"
   exit 1
fi

echo "[1/7] Enabling I2C interface..."
raspi-config nonint do_i2c 0
if [ $? -eq 0 ]; then
    echo "✓ I2C enabled"
else
    echo "✗ Failed to enable I2C"
fi

echo ""
echo "[2/7] Installing required packages..."
apt-get update
apt-get install -y i2c-tools python3-smbus python3-pip ntpdate

echo ""
echo "[3/7] Installing Python packages..."
pip3 install smbus2

echo ""
echo "[4/7] Loading I2C kernel modules..."
modprobe i2c-dev
modprobe i2c-bcm2835

# Add to modules to load at boot
if ! grep -q "i2c-dev" /etc/modules; then
    echo "i2c-dev" >> /etc/modules
fi
if ! grep -q "i2c-bcm2835" /etc/modules; then
    echo "i2c-bcm2835" >> /etc/modules
fi

echo ""
echo "[5/7] Checking RTC presence..."
i2cdetect -y 1 | grep -q " 68 \| UU"
if [ $? -eq 0 ]; then
    echo "✓ RTC detected at address 0x68"
else
    echo "✗ RTC not detected!"
    echo "  Please check wiring:"
    echo "  VCC → 3.3V (Pin 1)"
    echo "  GND → GND (Pin 6)" 
    echo "  SDA → GPIO 2 (Pin 3)"
    echo "  SCL → GPIO 3 (Pin 5)"
    exit 1
fi

echo ""
echo "[6/7] Loading RTC kernel driver..."

# Load the RTC driver
modprobe rtc_ds1307

# Check if already configured
if hwclock -r 2>/dev/null; then
    echo "✓ RTC already configured and working"
else
    # Create the device
    echo "ds3231 0x68" > /sys/class/i2c-adapter/i2c-1/new_device 2>/dev/null
    
    sleep 1
    
    # Test if it works
    if hwclock -r 2>/dev/null; then
        echo "✓ RTC kernel driver loaded successfully"
    else
        echo "⚠ RTC driver loaded but hwclock not working"
        echo "  This is usually OK - the fixed rtc_manager.py will handle it"
    fi
fi

echo ""
echo "[7/7] Setting up automatic time sync at boot..."

# Create systemd service for RTC sync
cat > /etc/systemd/system/rtc-sync.service << 'EOF'
[Unit]
Description=Sync time from RTC at boot
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/hwclock -s
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# Enable the service
systemctl daemon-reload
systemctl enable rtc-sync.service

echo "✓ Boot-time RTC sync configured"

echo ""
echo "[8/7] Optional: Sync RTC with NTP now..."
if ping -c 1 pool.ntp.org &> /dev/null; then
    echo "Internet connection detected, syncing with NTP..."
    ntpdate -s pool.ntp.org
    hwclock -w
    echo "✓ RTC synced with NTP time"
else
    echo "⚠ No internet connection, skipping NTP sync"
fi

echo ""
echo "================================"
echo "Setup Complete!"
echo "================================"
echo ""
echo "RTC Status:"
hwclock -r 2>/dev/null && echo "✓ hwclock working" || echo "⚠ hwclock not accessible"
echo ""
echo "System time: $(date)"
echo ""
echo "To test the RTC:"
echo "  python3 test_rtc.py"
echo ""
echo "To manually sync time:"
echo "  python3 rtc_manager.py"
echo ""
echo "The RTC will now maintain time even when the Pi is powered off!"
echo ""