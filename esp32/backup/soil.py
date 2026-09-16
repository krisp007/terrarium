from machine import ADC, Pin

soil1 = ADC(Pin(32))
soil2 = ADC(Pin(33))

soil1.atten(ADC.ATTN_11DB)
soil2.atten(ADC.ATTN_11DB)

print(soil1.read())
print(soil2.read())

def read_soil_left():
    raw = soil1.read()

    moisture = 100 - ((raw / 4095) * 100)

    return round(moisture, 1)

def read_soil_right():
    raw = soil2.read()

    moisture = 100 - ((raw / 4095) * 100)

    return round(moisture, 1)