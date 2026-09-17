from machine import ADC, Pin

soil1 = ADC(Pin(32))
soil2 = ADC(Pin(33))

soil1.atten(ADC.ATTN_11DB)
soil2.atten(ADC.ATTN_11DB)


def read_soil_left():
    try:
        raw = soil1.read()
        moisture = 100 - ((raw / 4095.0) * 100)
        return round(max(0, min(100, moisture)), 1)
    except Exception as e:
        print("Error reading soil left:", e)
        return None


def read_soil_right():
    try:
        raw = soil2.read()
        moisture = 100 - ((raw / 4095.0) * 100)
        return round(max(0, min(100, moisture)), 1)
    except Exception as e:
        print("Error reading soil right:", e)
        return None