from machine import Pin
import onewire
import ds18x20
import time

ow = onewire.OneWire(Pin(4))
ds = ds18x20.DS18X20(ow)


def read_aquarium_temp():

    global roms
    roms = ds.scan()

    if not roms:
        return None

    try:
        ds.convert_temp()
        time.sleep_ms(750)
        return ds.read_temp(roms[0])
    except Exception as e:
        print("Error reading aquarium temperature:", e)
        return None
