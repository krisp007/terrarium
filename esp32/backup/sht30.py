import time


def read_sht30(i2c, addr=0x44):
    try:
        # Send measurement command
        i2c.writeto(addr, b'\x2C\x06')
        time.sleep_ms(20)

        # Read 6 bytes of data
        data = i2c.readfrom(addr, 6)

        # Convert the data to temperature and humidity
        temp_raw = (data[0] << 8) | data[1]
        humidity_raw = (data[3] << 8) | data[4]

        temperature = -45 + (175 * temp_raw / 65535.0)
        humidity = 100 * humidity_raw / 65535.0

        return temperature, humidity
    except Exception as e:
        print("Error reading SHT30 sensor:", e)
        return None, None