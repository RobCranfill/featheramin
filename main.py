"""Make noises, based on a time-of-flight sensor.
    With VL53L4CD.
"""

import array
import audiocore
import audiopwmio
import board
import busio
import digitalio as feather_digitalio
import math
import time
import sys

import feathereminDisplay

import adafruit_vl53l0x
import adafruit_vl53l4cd

# https://learn.adafruit.com/adafruit-apds9960-breakout/circuitpython
from adafruit_apds9960.apds9960 import APDS9960

# https://docs.circuitpython.org/projects/seesaw/en/latest/
from adafruit_seesaw import seesaw, rotaryio, digitalio

# GPIO pins used:
L0X_RESET_OUT = board.A0
AUDIO_OUT_PIN = board.A1

L4CD_ALTERNATE_I2C_ADDR = 0x31

ONE_OCTAVE = [440.00, 466.16, 493.88, 523.25, 554.37, 587.33, 622.25, 659.25, 698.46, 739.99, 83.99, 830.61]

print("Hello, fetheremin!")

# Generate one period of various waveforms.
# TODO: Should there be an odd or even number of samples? we want to start and end with zeros, or at least some number.
#
length = 8000 // 440 + 1

sine_wave_data = array.array("H", [0] * length)
square_wave_data = array.array("H", [0] * length)
triangle_wave_data = array.array("H", [0] * length)
sawtooth_up_wave_data = array.array("H", [0] * length)
sawtooth_down_wave_data = array.array("H", [0] * length)

waves = [
    ("sine", sine_wave_data), 
    ("square", square_wave_data), 
    ("triangle", triangle_wave_data),
    ("saw up", sawtooth_up_wave_data),
    ("saw down", sawtooth_down_wave_data)]


for i in range(length):
    sine_wave_data[i] = int(math.sin(math.pi * 2 * i / length) * (2 ** 15) + 2 ** 15)
    if i < length/2:
        square_wave_data[i] = 0
        triangle_wave_data[i] = 2 * int(2**16 * i/length)
    else:
        square_wave_data[i] = int(2 ** 16)-1
        triangle_wave_data[i] = triangle_wave_data[length-i-1]
    sawtooth_up_wave_data[i] = int(i*2**16/length)
    sawtooth_down_wave_data[i] = 2**16 - sawtooth_up_wave_data[i] - 1

print(f"Wave tables: {length} entries")
print(f"{[w[0] for w in waves]}")
for i in range(length):
    print(f"({i},\t{sine_wave_data[i]},\t{square_wave_data[i]},\t{triangle_wave_data[i]},\t{sawtooth_up_wave_data[i]},\t{sawtooth_down_wave_data[i]})")


def showI2Cbus():
    i2c = board.I2C()
    if i2c.try_lock():
        print(f"I2C: {[hex(x) for x in i2c.scan()]}")
    i2c.unlock()


def init_hardware():
    """Initialize various hardware items.
    Namely, the I2C bus, Time of Flight sensors, gesture sensor, and display.

    None of this checks for errors (missing hardware) yet - it will just malf.

    Returns:
        list of objects: the various harware items initialized.
    """

    # Easist way to init I2C on a Feather:
    i2c = board.STEMMA_I2C()

    # For fun
    showI2Cbus()


    # ----------------- VL53L0X time-of-flight sensor 
    
    # Turn off the ToF sensor - take XSHUT pin low
    print("Turning off VL53L0X...")
    L0X_reset = feather_digitalio.DigitalInOut(L0X_RESET_OUT)
    L0X_reset.direction = feather_digitalio.Direction.OUTPUT
    L0X_reset.value = 0
    # VL53L0X sensor is now turned off


    # L4CD ToF

    # First, see if it's there with the new address (left over from a previous run)
    try:
        L4CD = adafruit_vl53l4cd.VL53L4CD(i2c, address=L4CD_ALTERNATE_I2C_ADDR)
        print(f"Found VL53L4CD at {hex(L4CD_ALTERNATE_I2C_ADDR)}")
    except:
        print(f"Did not find VL53L4CD at {hex(L4CD_ALTERNATE_I2C_ADDR)}, trying default....")

        #TODO: catch error here if no device at all
        L4CD = adafruit_vl53l4cd.VL53L4CD(i2c)
        L4CD.set_address(L4CD_ALTERNATE_I2C_ADDR)  # address assigned should NOT be already in use
        print(f"Found VL53L4CD at default address; now set to {hex(L4CD_ALTERNATE_I2C_ADDR)}")
    finally:

        # OPTIONAL: can set non-default values
        # TODO: move this to above initial setup?
        L4CD.inter_measurement = 0
        L4CD.timing_budget = 100 # must be low enough for ou

        print("--------------------")
        print("VL53L4CD:")
        model_id, module_type = L4CD.model_info
        print(f"    Model ID: 0x{model_id:0X}")
        print(f"    Module Type: 0x{module_type:0X}")
        print(f"    Timing Budget: {L4CD.timing_budget}")
        print(f"    Inter-Measurement: {L4CD.inter_measurement}")
        print("--------------------")

        L4CD.start_ranging()
        print("VL53L4CD init OK")



    # Turn L0X back on and instantiate its object
    print("Turning VL53L0X back on...")
    L0X_reset.value = 1
    L0X = adafruit_vl53l0x.VL53L0X(i2c)  # also performs VL53L0X hardware check

    showI2Cbus()

    tof = adafruit_vl53l0x.VL53L0X(i2c)
    print("VL53L0X init OK")


    # ----------------- APDS9960 gesture/proximity/color sensor 
    apds = APDS9960(i2c)
    apds.enable_proximity = True
    apds.enable_gesture = True
    apds.rotation = 180



    # ----------------- OLED display
    oledDisp = feathereminDisplay.FeathereminDisplay()

    return L0X, L4CD, apds, oledDisp


# map distance in millimeters to a sample rate in Hz
# mm in range (0,500)
#
def rangeToRate(mm: int) -> float:

    # simple, no chunking:
    if False:
        sr = int(30*mm + 1000)

    # 10 chunks - ok
    if False:
        sr = mm // 50  # sr = {0..10}
        sr = sr * 1000 # sr = {0K..10K}

    sr = ONE_OCTAVE[mm // 50] * (8000 // 440)
    
    return sr


tof_L0X, tof_L4CD, gesture, display = init_hardware()
 
dac = audiopwmio.PWMAudioOut(AUDIO_OUT_PIN)

sleepTime = 0.2
bleepTime = 0.2

nTries = 100
iter = 1
sampleRateLast = -1

useSineWave = True
wheelPositionLast = None

chunkMode = False
chunkSleep = 0.1
display.setTextArea2(f"Sleep: {chunkSleep:.2f}")

waveIndex = 0
waveName  = waves[waveIndex][0]
waveTable = waves[waveIndex][1]

print(f"Wave #{waveIndex}: {waveName}")
display.setTextArea1(f"Waveform: {waveName}")

while True:

    g = gesture.gesture()
    if g == 1:
        waveIndex += 1
        if waveIndex >= len(waves):
            waveIndex = 0
        waveName  = waves[waveIndex][0]
        waveTable = waves[waveIndex][1]
        print(f"Wave #{waveIndex}: {waves[waveIndex][0]}")
        display.setTextArea1(f"Waveform: {waveName}")
    elif g == 2:
        waveIndex -= 1
        if waveIndex < 0:
            waveIndex = len(waves) - 1
        waveName  = waves[waveIndex][0]
        waveTable = waves[waveIndex][1]
        print(f"Wave #{waveIndex}: {waves[waveIndex][0]}")
        display.setTextArea1(f"Waveform: {waveName}")
    elif g == 3:
        print("left")
        chunkSleep -= 0.01
        if chunkSleep < 0:
            chunkSleep = 0
        display.setTextArea2(f"Sleep: {chunkSleep:.2f}")
    elif g == 4:
        print("right")
        chunkSleep += 0.01
        display.setTextArea2(f"Sleep: {chunkSleep:.2f}")

    r1 = tof_L0X.range
    if tof_L4CD.data_ready:
        r2 = tof_L4CD.distance
        tof_L4CD.clear_interrupt()
        print(f"r2: {r2}")

    if r1 > 0 and r1 < 500:

        if chunkMode:
            sampleRate = int(rangeToRate(r1))
            if sampleRate != sampleRateLast:

                dac.stop()

                # sampleRate = int(30*(500-r) + 1000)
                # sampleRate = int(30*r + 1000)

                print(f"#{iter}: {r1} mm -> {sampleRate} Hz {'sine' if useSineWave else 'square'}")

                waveSample = audiocore.RawSample(waveTable, sample_rate=sampleRate)

                sampleRateLast = sampleRate
                dac.play(waveSample, loop=True)
                time.sleep(0.1)
            # time.sleep(bleepTime)
            # dac.stop()

        else: # "continuous", not chunkMode
            
            # sampleRate = int(rangeToRate(r))
            sampleRate = int(30*r1 + 1000)

            # dac.stop()

            print(f"Cont: {waveName} #{iter}: {r1} mm -> {sampleRate} Hz {chunkSleep} ")

            waveSample = audiocore.RawSample(waveTable, sample_rate=sampleRate)
            
            dac.play(waveSample, loop=True)

            time.sleep(chunkSleep)

            # time.sleep(bleepTime)
            # dac.stop()
            
    else:
        dac.stop()
        # pass
        # time.sleep(sleepTime)
        
    iter += 1
    # print("Done!")
