from machine import Pin
import onewire
import ds18x20
import time

ow = onewire.OneWire(Pin(4))
ds = ds18x20.DS18X20(ow)
roms = ds.scan()

def read_aquarium_temp():

    if not roms:
        return None

    ds.convert_temp()
    time.sleep_ms(750)

    return ds.read_temp(roms[0])
