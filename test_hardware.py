import time
import RPi.GPIO as GPIO

IR_SENSOR_PINS = {
    1: 4,   
    2: 7,   
    3: 8,   
}

lcd = None
try:
    from RPLCD.i2c import CharLCD
    lcd = CharLCD('PCF8574', 0x27, port=1, cols=16, rows=2)
    lcd.clear()
except Exception:
    lcd = None


def lcd_print(line1="", line2=""):
    if not lcd:
        return
    try:
        lcd.clear()
        lcd.cursor_pos = (0, 0)
        lcd.write_string(line1[:16])
        lcd.cursor_pos = (1, 0)
        lcd.write_string(line2[:16])
    except Exception:
        pass


def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for slot, pin in IR_SENSOR_PINS.items():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)


def is_key_present(pin):
    return GPIO.input(pin) == GPIO.LOW


def update_lcd(states):
    line1 = f"S1:{'KEY' if states.get(1) else '---'} S2:{'KEY' if states.get(2) else '---'}"
    line2 = f"S3:{'KEY' if states.get(3) else '---'}"
    lcd_print(line1, line2)


def main():
    setup_gpio()

    print("\n--- IR Sensor Test ---")
    previous_states = {}
    for slot, pin in sorted(IR_SENSOR_PINS.items()):
        present = is_key_present(pin)
        previous_states[slot] = present
        status = "KEY" if present else "EMPTY"
        print(f"Slot {slot} (GPIO {pin}): {status}")

    update_lcd(previous_states)

    try:
        while True:
            changed = False
            for slot, pin in sorted(IR_SENSOR_PINS.items()):
                present = is_key_present(pin)
                if present != previous_states[slot]:
                    previous_states[slot] = present
                    action = "KEY INSERTED" if present else "KEY REMOVED"
                    print(f"Slot {slot} (GPIO {pin}): {action}")
                    changed = True

            if changed:
                update_lcd(previous_states)

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nStopped.")

    finally:
        if lcd:
            lcd.clear()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
