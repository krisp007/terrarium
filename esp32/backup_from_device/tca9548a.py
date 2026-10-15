TCA_ADDR = 0x70

def select_channel(i2c, channel):
    if channel > 7:
        raise ValueError("Kanaal moet 0-7 zijn")

    i2c.writeto(TCA_ADDR, bytes([1 << channel]))
    