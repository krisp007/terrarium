from pca9685 import PCA9685

class VentController:

    def __init__(self, pca):
        self.pca = pca

    def set_fan(self, channel, percent):

        percent = max(0, min(100, percent))

        value = int(percent * 4095 / 100)

        self.pca.duty(channel, value)

    def all_off(self):

        for ch in range(6):
            self.pca.duty(ch, 0)

    def all_on(self):

        for ch in range(6):
            self.pca.duty(ch, 4095)

    def set_all(self, percent):

        for ch in range(6):
            self.set_fan(ch, percent)