from tca9548a import select_channel
from sht30 import read_sht30
from aquarium import read_aquarium_temp
from soil import read_soil_left
from soil import read_soil_right


def read_all_sensors(i2c):

    # SHT30 TOP
    try:
        select_channel(i2c, 0)
        temp_top, hum_top = read_sht30(i2c)
    except Exception as e:
        print("TOP sensor:", e)
        temp_top = None
        hum_top = None

    # SHT30 LEFT
    try:
        select_channel(i2c, 1)
        temp_left, hum_left = read_sht30(i2c)
    except Exception as e:
        print("LEFT sensor:", e)
        temp_left = None
        hum_left = None

    # SHT30 RIGHT
    try:
        select_channel(i2c, 2)
        temp_right, hum_right = read_sht30(i2c)
    except Exception as e:
        print("RIGHT sensor:", e)
        temp_right = None
        hum_right = None

    # Aquarium
    try:
        aquarium_temp = read_aquarium_temp()
    except Exception as e:
        print("Aquarium sensor:", e)
        aquarium_temp = None

    # Soil Left
    try:
        soil_left = read_soil_left()
    except Exception as e:
        print("Soil Left:", e)
        soil_left = None

    # Soil Right
    try:
        soil_right = read_soil_right()
    except Exception as e:
        print("Soil Right:", e)
        soil_right = None

    return {
        "temperature_top": temp_top,
        "humidity_top": hum_top,
        "temperature_left": temp_left,
        "humidity_left": hum_left,
        "temperature_right": temp_right,
        "humidity_right": hum_right,
        "aquarium_temp": aquarium_temp,
        "soil_left": soil_left,
        "soil_right": soil_right
    }