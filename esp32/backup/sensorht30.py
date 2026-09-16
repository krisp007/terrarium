from machine import Pin, I2C
import time

i2c = I2C(0, scl=Pin(22), sda=Pin(21))
SHT30_ADDR = [  0x44, 0x45]  # Possible I2C addresses for SHT30

def read_sht30(address=SHT30_ADDR[0]):
    try:
        # Send measurement command
        i2c.writeto(address, b'\x2C\x06')
        time.sleep(0.5)  # Wait for measurement to complete

        # Read 6 bytes of data
        data = i2c.readfrom(address, 6)

        # Convert the data to temperature and humidity
        temp_raw = (data[0] << 8) | data[1]
        humidity_raw = (data[3] << 8) | data[4]

        temperature = -45 + (175 * temp_raw / 65535.0)
        humidity = 100 * humidity_raw / 65535.0

        return temperature, humidity
    except Exception as e:
        print("Error reading SHT30 sensor:", e)
        return None, None
# test
while True:
    for address in SHT30_ADDR:
        temperature, humidity = read_sht30(address=address)
        if temperature is not None and humidity is not None:
            print("Temperature: {:.2f} °C, Humidity: {:.2f} %".format(temperature, humidity))
        else:
            print("Failed to read from SHT30 sensor at address 0x{:02X}.".format(address))
    time.sleep(2)
