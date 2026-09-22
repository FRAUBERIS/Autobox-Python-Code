import time
import sys

try:
    import RPi.GPIO as GPIO
except ImportError:
    print("[ERROR] RPi.GPIO is only available on Raspberry Pi.")
    sys.exit(1)

# GPIO Pin Configuration based strictly on Components pin.txt
SOLENOIDS = {
    "Slot 1 Solenoid (GPIO 17 / Pin 11 - IN1)": 17,
    "Slot 2 Solenoid (GPIO 27 / Pin 13 - IN2)": 27,
    "Slot 3 Solenoid (GPIO 22 / Pin 15 - IN3)": 22,
    "Main Door Lock  (GPIO 23 / Pin 16 - IN4)": 23,
}

ALL_SOLENOID_PINS = [17, 27, 22, 23]

LEDS = {
    "Slot 1 Green (GPIO 5  / Pin 29)": 5,
    "Slot 1 Red   (GPIO 12 / Pin 32)": 12,
    "Slot 2 Green (GPIO 6  / Pin 31)": 6,
    "Slot 2 Red   (GPIO 16 / Pin 36)": 16,
    "Slot 3 Green (GPIO 13 / Pin 33)": 13,
    "Slot 3 Red   (GPIO 20 / Pin 38)": 20,
}

IR_SENSORS = {
    "Slot 1 IR (GPIO 4 / Pin 7)":  4,
    "Slot 2 IR (GPIO 8 / Pin 24)": 8,
    "Slot 3 IR (GPIO 7 / Pin 26)": 7,
}

RELAY_ACTIVE_LOW = True
RELAY_ON = GPIO.LOW if RELAY_ACTIVE_LOW else GPIO.HIGH
RELAY_OFF = GPIO.HIGH if RELAY_ACTIVE_LOW else GPIO.LOW


def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    for pin in ALL_SOLENOID_PINS:
        GPIO.setup(pin, GPIO.OUT, initial=RELAY_OFF)
        GPIO.output(pin, RELAY_OFF)

    for pin in LEDS.values():
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
        GPIO.output(pin, GPIO.LOW)

    for pin in IR_SENSORS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)


def test_solenoid(name, pin):
    print(f"\n--> PULSING {name} for 2 seconds...")
    GPIO.output(pin, RELAY_ON)
    time.sleep(2.0)
    GPIO.output(pin, RELAY_OFF)
    print(f"--> {name} DE-ENERGIZED (OFF).")


def test_all_solenoids_sequence():
    print("\n=== TESTING ALL SOLENOIDS IN ORDER (1 -> 2 -> 3 -> Main) ===")
    for name, pin in SOLENOIDS.items():
        test_solenoid(name, pin)
        time.sleep(1.0)


def test_leds():
    print("\n=== TESTING ALL LEDS IN ORDER ===")
    for name, pin in LEDS.items():
        print(f"Turning ON: {name}")
        GPIO.output(pin, GPIO.HIGH)
        time.sleep(1.2)
        GPIO.output(pin, GPIO.LOW)
        time.sleep(0.3)


def test_ir_sensors():
    print("\n=== LIVE IR SENSOR MONITOR (Components pin.txt) ===")
    print("Press Ctrl+C to stop.")
    print("Place or remove key in each slot to verify readings:")
    try:
        while True:
            readings = []
            for name, pin in IR_SENSORS.items():
                val = GPIO.input(pin)
                status = "DETECTED (LOW)" if val == GPIO.LOW else "EMPTY (HIGH)"
                readings.append(f"{name}: {status}")
            print(" | ".join(readings), end="\r")
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nIR sensor test stopped.")


def main():
    setup()
    try:
        while True:
            print("\n" + "=" * 55)
            print("   AUTOBOX HARDWARE TEST (Based on Components pin.txt)")
            print("=" * 55)
            print("1. Pulse Slot 1 Solenoid (GPIO 17 / Pin 11 - IN1)")
            print("2. Pulse Slot 2 Solenoid (GPIO 27 / Pin 13 - IN2)")
            print("3. Pulse Slot 3 Solenoid (GPIO 22 / Pin 15 - IN3)")
            print("4. Pulse Main Door Lock  (GPIO 23 / Pin 16 - IN4)")
            print("5. Test ALL Solenoids (1 -> 2 -> 3 -> Main)")
            print("6. Test ALL LEDs one-by-one")
            print("7. Live IR Sensor Monitor (Slots 1, 2, 3)")
            print("8. Exit")
            choice = input("Enter choice (1-8): ").strip()

            if choice == "1":
                test_solenoid("Slot 1 Solenoid (GPIO 17)", 17)
            elif choice == "2":
                test_solenoid("Slot 2 Solenoid (GPIO 27)", 27)
            elif choice == "3":
                test_solenoid("Slot 3 Solenoid (GPIO 22)", 22)
            elif choice == "4":
                test_solenoid("Main Door Lock (GPIO 23)", 23)
            elif choice == "5":
                test_all_solenoids_sequence()
            elif choice == "6":
                test_leds()
            elif choice == "7":
                test_ir_sensors()
            elif choice == "8":
                break
            else:
                print("Invalid choice, please select 1-8.")
    finally:
        for pin in ALL_SOLENOID_PINS:
            GPIO.output(pin, RELAY_OFF)
        for pin in LEDS.values():
            GPIO.output(pin, GPIO.LOW)
        GPIO.cleanup()
        print("\n[GPIO] All pins safely cleaned up.")


if __name__ == "__main__":
    main()
