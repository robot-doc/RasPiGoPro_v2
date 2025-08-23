#!/usr/bin/env python3
"""
RTC Manager for Raspberry Pi with DS3231
- Sync system time from RTC on startup
- If NTP available, sync system time from NTP and update RTC
Handles busy I2C device errors gracefully.
2025.08.23
ACHTUNG: Das Programm wird aktuell nicht verwendet bzw. bricht ab.
Ein Kernel Treiber beansprucht die Echtzeiuhr aktuell schon.
ToDo: Herausfinden, welcher Prozess die Echtzeituhr beansprucht.
"""

import subprocess
import datetime
import logging
from smbus2 import SMBus

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


def bcd_to_dec(bcd: int) -> int:
    return (bcd & 0x0F) + ((bcd >> 4) * 10)


def dec_to_bcd(dec: int) -> int:
    return ((dec // 10) << 4) + (dec % 10)


def read_rtc_time(bus: SMBus) -> datetime.datetime:
    data = bus.read_i2c_block_data(DS3231_ADDR, REG_SECONDS, 7)
    seconds = bcd_to_dec(data[0] & 0x7F)
    minutes = bcd_to_dec(data[1])
    hours   = bcd_to_dec(data[2] & 0x3F)
    day     = bcd_to_dec(data[4])
    month   = bcd_to_dec(data[5] & 0x1F)
    year    = bcd_to_dec(data[6]) + 2000
    return datetime.datetime(year, month, day, hours, minutes, seconds)


def write_rtc_time(bus: SMBus, dt: datetime.datetime):
    data = [
        dec_to_bcd(dt.second),
        dec_to_bcd(dt.minute),
        dec_to_bcd(dt.hour),
        dec_to_bcd(dt.isoweekday()),
        dec_to_bcd(dt.day),
        dec_to_bcd(dt.month),
        dec_to_bcd(dt.year - 2000)
    ]
    bus.write_i2c_block_data(DS3231_ADDR, REG_SECONDS, data)


def set_system_time(dt: datetime.datetime):
    timestr = dt.strftime('%Y-%m-%d %H:%M:%S')
    logging.info(f"[SYS] Setting system time: {timestr}")
    subprocess.run(["sudo", "date", "-s", timestr], check=False)


def get_ntp_time(server: str = "pool.ntp.org", timeout: int = 3):
    try:
        import ntplib
        client = ntplib.NTPClient()
        response = client.request(server, version=3, timeout=timeout)
        return datetime.datetime.utcfromtimestamp(response.tx_time)
    except Exception as e:
        logging.warning(f"[NTP] Could not get NTP time: {e}")
        return None


def sync_time():
    try:
        with SMBus(1) as bus:
            rtc_time = read_rtc_time(bus)
            logging.info(f"[RTC] Current RTC time: {rtc_time}")

            # Step 1: Set system time from RTC
            set_system_time(rtc_time)

            # Step 2: Try NTP sync
            ntp_time = get_ntp_time()
            if ntp_time:
                logging.info(f"[NTP] Synced time: {ntp_time}")
                set_system_time(ntp_time)
                # Update RTC with NTP time
                write_rtc_time(bus, ntp_time)
                logging.info("[RTC] RTC updated from NTP")
            else:
                logging.info("[NTP] No NTP sync available, keeping RTC time")
    except OSError as e:
        if e.errno == 16:
            logging.error("[RTC] I2C device busy. Another process may be using the RTC.")
        else:
            logging.error(f"[RTC] I2C error: {e}")
    except Exception as e:
        logging.error(f"[RTC] Unexpected error during sync: {e}")
