pasted

check

The code looks good. Both fixes are correctly applied:

GPIO.cleanup() at the top of setup_gpio() ✅

python
def setup_gpio():
    GPIO.cleanup()    
    GPIO.setmode(GPIO.BCM)
try/finally wrapping the admin unlock block ✅

python
try:
    if ENABLE_SOLENOIDS:
        GPIO.output(MAIN_LOCK_PIN, GPIO.HIGH)
        ...
    slider_open()
    wait_no_hand_and_close()
finally:
    if ENABLE_SOLENOIDS:
        GPIO.output(MAIN_LOCK_PIN, GPIO.LOW)
        ...
One small thing — your print inside the finally loop is indented wrong:

python
finally:
    if ENABLE_SOLENOIDS:
        GPIO.output(MAIN_LOCK_PIN, GPIO.LOW)
        for s_num, pin in SLOT_PINS.items():
            GPIO.output(pin, GPIO.LOW)
            print("[AUTOBOX] All solenoids relocked.")  # ← inside the for loop, prints 3 times
Move it one level out so it only prints once:

python
finally:
    if ENABLE_SOLENOIDS:
        GPIO.output(MAIN_LOCK_PIN, GPIO.LOW)
        for s_num, pin in SLOT_PINS.items():
            GPIO.output(pin, GPIO.LOW)
        print("[AUTOBOX] All solenoids relocked.")  # ← outside the for loop
Everything else looks correct. Go ahead and test it.
