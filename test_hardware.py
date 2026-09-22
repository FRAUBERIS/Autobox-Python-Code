import time
import sys

try:
    import RPi.GPIO as GPIO
except ImportError:
    print("[ERROR] RPi.GPIO is only available on Raspberry Pi.")
    sys.exit(1)

# GPIO Pin Configuration
SOLENOIDS = {
    "Slot 1 (GPIO 27)": 27,
    "Slot 2 (GPIO 22)": 22,
    "Slot 3 (GPIO 17)": 17,
    "Main Lock (GPIO 23)": 23,
}

ALL_SOLENOID_PINS = [17, 22, 23, 27]

LEDS = {
    "Slot 1 Green (GPIO 5)": 5,
    "Slot 1 Red   (GPIO 12)": 12,
    "Slot 2 Green (GPIO 6)": 6,
    "Slot 2 Red   (GPIO 16)": 16,
    "Slot 3 Green (GPIO 20)": 20,
    "Slot 3 Red   (GPIO 13)": 13,
}

IR_SENSORS = {
    "Slot 1 IR (GPIO 4)": 4,
    "Slot 2 IR (GPIO 7)": 7,
    "Slot 3 IR (GPIO 8)": 8,
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
    print(f"--> {name} OFF.")


def test_all_solenoids_sequence():
    print("\n=== TESTING EACH SOLENOID PIN ONE BY ONE ===")
    for name, pin in SOLENOIDS.items():
        test_solenoid(name, pin)
        time.sleep(1.0)


def test_leds():
    print("\n=== TESTING LEDS ONE BY ONE ===")
    for name, pin in LEDS.items():
        print(f"Turning ON: {name}")
        GPIO.output(pin, GPIO.HIGH)
        time.sleep(1.2)
        GPIO.output(pin, GPIO.LOW)
        time.sleep(0.3)


def test_ir_sensors():
    print("\n=== LIVE IR SENSOR MONITOR (Press Ctrl+C to stop) ===")
    print("Block/unblock each slot to verify which GPIO reacts:")
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
        print("\nIR test stopped.")


def main():
    setup()
    try:
        while True:
            print("\n" + "=" * 50)
            print("     AUTOBOX HARDWARE DIAGNOSTIC TOOL")
            print("=" * 50)
            print("1. Pulse Slot 1 Solenoid (GPIO 27)")
            print("2. Pulse Slot 2 Solenoid (GPIO 22)")
            print("3. Pulse Slot 3 Solenoid (GPIO 17)")
            print("4. Pulse Main Door Solenoid (GPIO 23)")
            print("5. Test ALL Solenoids one-by-one")
            print("6. Test ALL LEDs one-by-one")
            print("7. Live IR Sensor Monitor")
            print("8. Exit")
            choice = input("Enter choice (1-8): ").strip()

            if choice == "1":
                test_solenoid("Slot 1 (GPIO 27)", 27)
            elif choice == "2":
                test_solenoid("Slot 2 (GPIO 22)", 22)
            elif choice == "3":
                test_solenoid("Slot 3 (GPIO 17)", 17)
            elif choice == "4":
                test_solenoid("Main Lock (GPIO 23)", 23)
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
        print("[GPIO] Cleanup complete.")


if __name__ == "__main__":
    main()
