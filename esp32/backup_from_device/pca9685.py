class PCA9685:

    def __init__(self, i2c, address=0x40):
        self.i2c = i2c
        self.address = address

        self.reset()

    def reset(self):
        self.i2c.writeto_mem(
            self.address,
            0x00,
            b'\x00'
        )

    def freq(self, freq):

        prescale = int(
            25000000.0 / 4096.0 / freq - 1
        )

        old_mode = self.i2c.readfrom_mem(
            self.address,
            0x00,
            1
        )[0]

        sleep_mode = (old_mode & 0x7F) | 0x10

        self.i2c.writeto_mem(
            self.address,
            0x00,
            bytes([sleep_mode])
        )

        self.i2c.writeto_mem(
            self.address,
            0xFE,
            bytes([prescale])
        )

        self.i2c.writeto_mem(
            self.address,
            0x00,
            bytes([old_mode])
        )

        self.i2c.writeto_mem(
            self.address,
            0x00,
            bytes([old_mode | 0xA1])
        )

    def duty(self, channel, value):

        if value < 0:
            value = 0

        if value > 4095:
            value = 4095

        reg = 0x06 + (4 * channel)

        self.i2c.writeto_mem(
            self.address,
            reg,
            bytes([
                0x00,
                0x00,
                value & 0xFF,
                value >> 8
            ])
        )
        