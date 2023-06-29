"""Make noises, based on various sensors including time-of-flight.
    robcranfill@gmail.com
"""
import array
import audiocore
# import audiopwmio
import board
import busio
import digitalio as feather_digitalio
import math
import time
import supervisor
import sys

# Adafruit hardware libraries - www.adafruit.com
import feathereminDisplay9341
import adafruit_vl53l0x
import adafruit_vl53l4cd
import adafruit_max9744
from adafruit_apds9960.apds9960 import APDS9960
from adafruit_seesaw import seesaw, rotaryio, digitalio, neopixel

import featherSynth5

# No 'enum' in circuitpython! :-(
# from enum import Enum
# class Waveform(Enum):
#     SQUARE = 1
#     SINE = 2
#     SAW = 3
WAVEFORM_TYPES = ["Square", "Sine", "Saw"]
LFO_MODES = ["LFO Off", "Tremolo", "Vibrato", "Drone"]
lfo_tremolo_freq = 15
lfo_vibrato_freq = 4

# GPIO pins used:
L0X_RESET_OUT = board.D4

# for PWM audio output
# AUDIO_OUT_PIN = board.D5    

# for I2S audio out
AUDIO_OUT_I2S_BIT  = board.D9
AUDIO_OUT_I2S_WORD = board.D10
AUDIO_OUT_I2S_DATA = board.D11

# Display
TFT_DISPLAY_CS    = board.A2
TFT_DISPLAY_DC    = board.A0
TFT_DISPLAY_RESET = board.A1

L4CD_ALTERNATE_I2C_ADDR = 0x31

INITIAL_AMP_VOLUME = 10 # 25 is max for 20W amp and 3W 4 ohm speaker with 12v to amp.


def showI2Cbus():
    i2c = board.I2C()
    if i2c.try_lock():
        print(f"I2C addresses found: {[hex(x) for x in i2c.scan()]}")
        i2c.unlock()


def init_hardware() -> list(adafruit_vl53l0x.VL53L0X,   # 1st ToF sensor
                            adafruit_vl53l4cd.VL53L4CD, # 2nd ToF sensor
                            APDS9960,                   # gesture sensor
                            feathereminDisplay9341.FeathereminDisplay9341, # our display object
                            adafruit_max9744.MAX9744,   # amplifier, or None
                            rotaryio.IncrementalEncoder, # rotary encoder
                            digitalio.DigitalIO,        # pushbutton in rotary encoder
                            neopixel.NeoPixel           # neopixel in rotary encoder
                            ):
    
    """Initialize various hardware items.
    Namely, the I2C bus, Time of Flight sensors, gesture sensor, display, and amp (if attached).

    Mostly none of this checks for errors (missing hardware) yet - it will just malf.

    Returns:
        list of objects: the various hardware items initialized.
    """

    # supervisor.reload()

    # Easist way to init I2C on a Feather:
    i2c = board.STEMMA_I2C()

    # For fun
    showI2Cbus()

    # ----------------- VL53L0X time-of-flight sensor 
    # We will finish setting this sensor up 
    # *after* we turn it off an init the other ToF sensor.
    
    # Turn off the ToF sensor - take XSHUT pin low
    print("Turning off VL53L0X...")
    L0X_reset = feather_digitalio.DigitalInOut(L0X_RESET_OUT)
    L0X_reset.direction = feather_digitalio.Direction.OUTPUT
    L0X_reset.value = 0
    # VL53L0X sensor is now turned off

    # ----------------- VL53L4CD time-of-flight sensor
    # L4CD ToF
    # First, see if it's there with the new address (left over from a previous run).
    # If so, we don't need to re-assign it.
    try:
        L4CD = adafruit_vl53l4cd.VL53L4CD(i2c, address=L4CD_ALTERNATE_I2C_ADDR)
        print(f"Found VL53L4CD at {hex(L4CD_ALTERNATE_I2C_ADDR)}; OK")
    except:
        print(f"Did not find VL53L4CD at {hex(L4CD_ALTERNATE_I2C_ADDR)}, trying default....")
        try:
            L4CD = adafruit_vl53l4cd.VL53L4CD(i2c)
            print(f"Found VL53L4CD at default address; setting to {hex(L4CD_ALTERNATE_I2C_ADDR)}...")
            L4CD.set_address(L4CD_ALTERNATE_I2C_ADDR)  # address assigned should NOT be already in use
            print("VL53L4CD set_address OK")

            # # set non-default values?
            L4CD.inter_measurement = 0
            L4CD.timing_budget = 100
            L4CD.start_ranging()

            # print("--------------------")
            # print("VL53L4CD:")
            # model_id, module_type = L4CD.model_info
            # print(f"    Model ID: 0x{model_id:0X}")
            # print(f"    Module Type: 0x{module_type:0X}")
            # print(f"    Timing Budget: {L4CD.timing_budget}")
            # print(f"    Inter-Measurement: {L4CD.inter_measurement}")
            # print("--------------------")
            print("VL53L4CD init OK")
        except:
            print("**** No VL53L4CD?")
            L4CD = None


    # ----------------- VL53L0X time-of-flight sensor, part 2
    # Turn L0X back on and instantiate its object
    print("Turning VL53L0X back on...")
    L0X_reset.value = 1
    try:
        L0X = adafruit_vl53l0x.VL53L0X(i2c)  # also performs VL53L0X hardware check
        print("VL53L0X init OK")
    except:
        print("**** No VL53L0X? Continuing....")

    # Show bus again?
    # showI2Cbus()

    # ----------------- APDS9960 gesture/proximity/color sensor
    apds = None
    try:
        apds = APDS9960(i2c)
        apds.enable_proximity = True
        apds.enable_gesture = True
        apds.rotation = 90
        print("APDS9960 init OK")
    except:
        print("**** No APDS9960? Continuing....")

    # ----------------- Our display object
    display = feathereminDisplay9341.FeathereminDisplay9341(TFT_DISPLAY_CS, TFT_DISPLAY_DC, TFT_DISPLAY_RESET)
    print("Display init OK")

    # ------------------ MAX9744 amp, if any
    amp = None
    try:
        amp = adafruit_max9744.MAX9744(i2c)
        amp.volume = INITIAL_AMP_VOLUME
        print("MAX9744 amp init OK")
    except:
        print("**** No MAX9744 amplifier found; continuing....")

    # ------------------ Rotary encoder
    ss = seesaw.Seesaw(i2c, addr=0x36)
    seesaw_v = (ss.get_version() >> 16) & 0xFFFF
    # print(f"Found product {seesaw_v}")
    if seesaw_v != 4991:
        print("**** Wrong Rotary encoder firmware loaded?  Expected 4991")
        # what are we supposed to do about this??
    encoder = rotaryio.IncrementalEncoder(ss)

    # the "button" that is got by pushing down on the encoder wheel
    ss.pin_mode(24, ss.INPUT_PULLUP)
    wheel_button = digitalio.DigitalIO(ss, 24)
    # button_held = False

    # TODO: tried to do something with the Neopixel but haven't figured anything out yet. :-/
    pixel = neopixel.NeoPixel(ss, 6, 1)
    # pixel.brightness = 0.1
    pixel.fill(0x004000) # green for go!
    print("Rotary encoder init OK")


    print("\ninit_hardware OK!\n")
    return L0X, L4CD, apds, display, amp, encoder, wheel_button, pixel

def displayChromaticMode(disp, chromaticFlag):
    disp.setTextAreaL("Chromatic" if chromaticFlag else "Continuous")

def displayDelay(disp, sleepMS):
    disp.setTextArea2(f"Sleep: {sleepMS} ms")

def displayWaveformName(disp, name):
    disp.setTextArea1(f"Waveform: {name}")

def displayLFOMode(disp, mode):
    disp.setTextArea3(mode)

def clamp(num, min_value, max_value):
   return max(min(num, max_value), min_value)


# --------------------------------------------------
# ------------------- begin main -------------------
def main():
    print("\nHello, Featheremin!\n")

    # turn off auto-reload?
    import supervisor
    supervisor.runtime.autoreload = False  # CirPy 8 and above
    print("supervisor.runtime.autoreload = False")

    # Initialize the hardware, dying if something critical is missing.
    #
    tof_L0X, tof_L4CD, gestureSensor, display, amp, wheel, wheelButton, wheelLED = init_hardware()

    # My "synthezier" object that does the stuff that I need.
    #
    # synth = featherSynth5.FeatherSynth(AUDIO_OUT_PIN)
    synth = featherSynth5.FeatherSynth(
        i2s_bit_clock=AUDIO_OUT_I2S_BIT, i2s_word_select=AUDIO_OUT_I2S_WORD, i2s_data=AUDIO_OUT_I2S_DATA)
    synth.setVolume(0.1)

    waveIndex = 0
    waveName  = WAVEFORM_TYPES[waveIndex]
    displayWaveformName(display, waveName)
    synth.setWaveformSquare()

    lfoIndex = 0
    lfoMode = LFO_MODES[lfoIndex]
    displayLFOMode(display, lfoMode)

    dSleepMilliseconds = 0
    displayDelay(display, dSleepMilliseconds)

    iter = 1
    wheelPositionLast = None

    # Play notes from a chromatic scale, as opposed to a continuous range of frequencies?
    # That is, integer MIDI numbers .vs. fractional.
    chromatic = True
    displayChromaticMode(display, chromatic)

    # Instructions here?
    display.setTextAreaR("Started!")

    wheelButtonHeld = False

    # ==== Main loop ===============================================================
    while True:

        # TODO: tidy up all this gesture-handling stuff

        # Rotary encoder wheel.
        # negate the position to make clockwise rotation positive
        position = -wheel.position
        if position != wheelPositionLast:
            wheelPositionLast = position

            # FIDME: even tho we limit the value we *use*, 
            # the hidden 'position' goes way out of bounds which works oddly. Fix!
            dSleepMilliseconds = clamp(position, 0, 100)

            # print(f"Wheel {position} - > d = {dSleepMilliseconds}")
            displayDelay(display, dSleepMilliseconds)

        wheelButtonPressed = not wheelButton.value
        if wheelButtonPressed and not wheelButtonHeld:
            chromatic = not chromatic
            displayChromaticMode(display, chromatic)
            print(f"chromatic: {chromatic}")
            wheelButtonHeld = True
        if not wheelButtonPressed:
            wheelButtonHeld = False


        changedWaveform = False
        lfoChanged = False
        
        gestureValue = 0
        if gestureSensor:
            gestureValue = gestureSensor.gesture()
        # print(f"gestureValue: {gestureValue}")

        if gestureValue == 1: # down
            waveIndex = waveIndex - 1
            if waveIndex < 0:
                waveIndex = len(WAVEFORM_TYPES)-1
            changedWaveform = True
        elif gestureValue == 2: # up
            waveIndex = waveIndex + 1
            if waveIndex >= len(WAVEFORM_TYPES):
                waveIndex = 0
            changedWaveform = True
        elif gestureValue == 3: # right
            lfoIndex = lfoIndex + 1
            if lfoIndex >= len(LFO_MODES):
                lfoIndex = 0
            lfoChanged = True
        elif gestureValue == 4: # left
            lfoIndex = lfoIndex - 1
            if lfoIndex < 0:
                lfoIndex = len(LFO_MODES)-1
            lfoChanged = True

        if changedWaveform:
            waveName = WAVEFORM_TYPES[waveIndex]
            print(f" -> Wave #{waveIndex}: {waveName}")
            displayWaveformName(display, waveName)
            # FIXME: a better way to do this?
            if waveIndex == 0:
                synth.setWaveformSquare()
            elif waveIndex == 1:
                synth.setWaveformSine()
            elif waveIndex == 2:
                synth.setWaveformSaw()

        if lfoChanged:
            lfoMode = LFO_MODES[lfoIndex]
            print(f" -> LFO #{lfoIndex}: {lfoMode}")
            displayLFOMode(display, lfoMode)

            if lfoIndex == 0:
                synth.clearTremolo()
                synth.clearVibrato()

            elif lfoIndex == 1: # tremolo
                synth.setTremolo(20)
                synth.clearVibrato()

            elif lfoIndex == 2: # vibrato
                synth.setVibrato(20)
                synth.clearTremolo()

            elif lfoIndex == 3: # dual/drone
                synth.clearVibrato()
                synth.clearTremolo()
                synth.startDrone(1000, 1100)


        # Get the two ranges, as available. 
        # (FIXME: Why is one always available, but the other is not? Different hardware.)
        # TODO: if not in a mode that uses this range, don't read it?
        #
        # r1 is the main ToF detector, used for main frequency.
        # r2 is the secondary ToF, used for LFO freq, and maybe other things.
        #
        r1 = tof_L0X.range
        r2 = 0
        if tof_L4CD and tof_L4CD.data_ready:

            r2 = tof_L4CD.distance

            # r2 seems to range from r2~=25 at 10 inches down to r2~=1.0 at a few mm.
            # - We do get readings farther out, to like 50 or 60 at 2 feet, but will use the closer range.
            # TODO: Use values 5-25 for now; tailor for trem/vib?
            # sometimes there seem to be false signals of 0, so toss them out.
            if r2 > 0 and r2 < 25:
                r2a = max(5, r2)
                # print(f"r2: {r2} -> r2a = {r2a}")

                # TODO: only set if r2 has *changed*? especially if we force the value to be an int.
                
                # if mode was changed, the "other" mode has already been cleared, so we are good to go.
                if lfoIndex == 1: # tremolo 
                    synth.setTremolo(r2a) # map to 8-16?
                elif lfoIndex == 2:
                    synth.setVibrato(r2a) # map to 4-10?

            # must do this to get another reading
            tof_L4CD.clear_interrupt()

        if r1 > 0 and r1 < 1000:

            # drone mode
            if lfoIndex == 3:
                f1 = clamp(r1*100, 1000, 20000)
                
                # f2 = clamp(r2*100, 1000, 20000)
                f2 = f1 - r2
                
                print(f"drone: {f1} {f2}")
                synth.drone(f1, f2)
                pass

            midiNote = r1 / 4
            if midiNote > 120:
                midiNote = 120

            if chromatic:
                midiNote = int(midiNote)

            # print(f"{r1} -> {midiNote}")

            # FIXME: this causes too much noise! synthio bug?
            # display.setTextAreaR(f"r1={r1}\nr2={r2}")

            synth.play(midiNote)
            time.sleep(dSleepMilliseconds/100)

        else: # no proximity detected
            synth.stop()

        iter += 1


main() # :-)
