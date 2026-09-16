import ntptime
import time

def sync_time():
    try:
        ntptime.settime()
        print("Time synchronized successfully.")
    except Exception as e:
        print("Failed to synchronize time:", e)