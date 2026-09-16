from machine import Pin, I2C
from pca9685 import PCA9685

i2c = I2C(
    0,
    scl=Pin(22),
    sda=Pin(21),
    freq=10000
)

pca = PCA9685(i2c)

pca.freq(500)

print("PCA9685 Ready")