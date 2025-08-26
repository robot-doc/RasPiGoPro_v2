import csv
import threading
import time
from datetime import datetime
from pathlib import Path

class EdgeLogger:
    """
    Polls a boolean 'read_pin6()' callable and logs rising edges while running.
    Starts/stops from your recording state. Thread-safe; low overhead.
    """
    def __init__(self, read_pin6_callable, logs_dir="logs", poll_hz=500, min_edge_ms=5):
        self._read_pin6 = read_pin6_callable
        self._poll_dt = 1.0 / float(poll_hz)
        self._min_edge_ms = float(min_edge_ms)
        self._running = False
        self._thread = None
        self._last_state = 0
        self._last_edge_ts = 0.0
        self._count = 0

        Path(logs_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._filepath = Path(logs_dir) / f"input6_edges_{ts}.csv"
        self._fh = None
        self._csv = None

    @property
    def filepath(self):
        return str(self._filepath)

    def start(self):
        if self._running:
            return
        self._fh = open(self._filepath, "w", newline="")
        # CSV header: date, time, edge_count (Komma between date and time is natural here)
        self._csv = csv.writer(self._fh)
        self._csv.writerow(["date", "time", "edge_count"])
        self._running = True
        try:
            self._last_state = 1 if self._read_pin6() else 0
        except Exception:
            self._last_state = 0
        self._thread = threading.Thread(target=self._run, name="EdgeLoggerThread", daemon=True)
        self._thread.start()

    def stop(self):
        if not self._running:
            return
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._fh:
            self._fh.flush()
            self._fh.close()
            self._fh = None
            self._csv = None

    def _run(self):
        while self._running:
            try:
                state = 1 if self._read_pin6() else 0
            except Exception:
                time.sleep(self._poll_dt)
                continue

            now = time.time()
            # Rising edge with debounce
            if state == 1 and self._last_state == 0:
                if (now - self._last_edge_ts) * 1000.0 >= self._min_edge_ms:
                    self._count += 1
                    self._last_edge_ts = now

                    # Format with Komma between date and time
                    dt = datetime.now()
                    date_str = dt.strftime("%Y-%m-%d")
                    time_str = dt.strftime("%H:%M:%S.%f")[:-3]  # milliseconds
                    if self._csv:
                        self._csv.writerow([date_str, time_str, self._count])
                        if (self._count % 10) == 0 and self._fh:
                            self._fh.flush()

            self._last_state = state
            time.sleep(self._poll_dt)