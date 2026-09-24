import time
import sys

try:
    import RPi.GPIO as GPIO
except ImportError:
    print("[ERROR] RPi.GPIO is only available on Raspberry Pi.")
    sys.exit(1)

# Hardware Configuration matching Components pin.txt & autobox_pi.py
SLOTS_CONFIG = {
    1: {
        "name": "Slot 1",
        "ir_gpio": 4,       
        "green_led": 5,     
        "red_led": 12,      
    },
    2: {
        "name": "Slot 2",
        "ir_gpio": 8,       
        "green_led": 6,     
        "red_led": 16,      
    },
    3: {
        "name": "Slot 3",
        "ir_gpio": 7,       
        "green_led": 13,    
        "red_led": 20,     
    },
}


def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    for slot, cfg in SLOTS_CONFIG.items():
        # Setup IR Sensor (Input with pull-up)
        GPIO.setup(cfg["ir_gpio"], GPIO.IN, pull_up_down=GPIO.PUD_UP)
        # Setup LEDs (Output, initial LOW)
        GPIO.setup(cfg["green_led"], GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(cfg["red_led"], GPIO.OUT, initial=GPIO.LOW)


def set_slot_led(slot_num, object_detected):
    """Turns Green ON if object detected; turns Red ON if empty."""
    cfg = SLOTS_CONFIG.get(slot_num)
    if not cfg:
        return
    if object_detected:
        GPIO.output(cfg["green_led"], GPIO.HIGH)
        GPIO.output(cfg["red_led"], GPIO.LOW)
    else:
        GPIO.output(cfg["green_led"], GPIO.LOW)
        GPIO.output(cfg["red_led"], GPIO.HIGH)


def all_leds_off():
    for cfg in SLOTS_CONFIG.values():
        GPIO.output(cfg["green_led"], GPIO.LOW)
        GPIO.output(cfg["red_led"], GPIO.LOW)


def test_single_slot(slot_num):
    cfg = SLOTS_CONFIG.get(slot_num)
    if not cfg:
        print(f"Invalid slot {slot_num}")
        return

    ir_pin = cfg["ir_gpio"]
    g_pin = cfg["green_led"]
    r_pin = cfg["red_led"]

    print("\n" + "=" * 55)
    print(f"TESTING {cfg['name'].upper()} IR SENSOR & LEDS")
    print("=" * 55)
    print(f"IR Sensor:  GPIO {ir_pin} (LOW/0 = Detected, HIGH/1 = Empty)")
    print(f"GREEN LED:  GPIO {g_pin} (Lights up when OBJECT DETECTED)")
    print(f"RED LED:    GPIO {r_pin} (Lights up when EMPTY)")
    print("\nPress Ctrl+C to return to menu.\n")

    last_state = None

    try:
        while True:
            val = GPIO.input(ir_pin)
            detected = (val == GPIO.LOW)

            set_slot_led(slot_num, detected)

            if detected != last_state:
                last_state = detected
                ts = time.strftime("%H:%M:%S")
                if detected:
                    print(f"[{ts}] OBJECT DETECTED -> GREEN LED ON (GPIO {g_pin}=HIGH), RED OFF")
                else:
                    print(f"[{ts}] EMPTY / NO OBJECT -> RED LED ON (GPIO {r_pin}=HIGH), GREEN OFF")

            time.sleep(0.05)
    except KeyboardInterrupt:
        all_leds_off()
        print(f"\nStopped testing {cfg['name']}. LEDs turned OFF.")


def test_all_slots_live():
    print("\n" + "=" * 60)
    print("LIVE IR SENSOR & LED MONITOR (SLOTS 1, 2, 3)")
    print("=" * 60)
    print("Green LED turns ON when object is present.")
    print("Red LED turns ON when slot is empty.")
    print("Press Ctrl+C to return to menu.\n")

    try:
        while True:
            readings = []
            for slot, cfg in SLOTS_CONFIG.items():
                val = GPIO.input(cfg["ir_gpio"])
                detected = (val == GPIO.LOW)
                set_slot_led(slot, detected)

                status = "DETECTED (GRN)" if detected else "EMPTY (RED)"
                readings.append(f"Slot {slot}: {status}")

            print("  |  ".join(readings), end="\r")
            time.sleep(0.08)
    except KeyboardInterrupt:
        all_leds_off()
        print("\nLive monitor stopped. LEDs turned OFF.")


def test_slot3_pin_check():
    print("\n" + "=" * 55)
    print("SLOT 3 PIN CHECK & LED TEST (GPIO 7 vs GPIO 8)")
    print("=" * 55)
    print("Slot 3 Green LED: GPIO 13 (Pin 33)")
    print("Slot 3 Red LED:   GPIO 20 (Pin 38)")
    print("Press Ctrl+C to return to menu.\n")

    GPIO.setup(7, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(8, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(13, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(20, GPIO.OUT, initial=GPIO.LOW)

    last_v7 = None
    last_v8 = None

    try:
        while True:
            v7 = GPIO.input(7)
            v8 = GPIO.input(8)

            detected_on_7 = (v7 == GPIO.LOW)

            # Control Slot 3 LEDs based on GPIO 7 detection
            if detected_on_7:
                GPIO.output(13, GPIO.HIGH)
                GPIO.output(20, GPIO.LOW)
            else:
                GPIO.output(13, GPIO.LOW)
                GPIO.output(20, GPIO.HIGH)

            if v7 != last_v7 or v8 != last_v8:
                last_v7 = v7
                last_v8 = v8
                ts = time.strftime("%H:%M:%S")

                status7 = "DETECTED" if v7 == GPIO.LOW else "EMPTY"
                status8 = "DETECTED" if v8 == GPIO.LOW else "EMPTY"

                active = ""
                if v7 == GPIO.LOW and v8 != GPIO.LOW:
                    active = "--> TRIGGERED ON GPIO 7 (Green LED GPIO 13 ON)"
                elif v8 == GPIO.LOW and v7 != GPIO.LOW:
                    active = "--> TRIGGERED ON GPIO 8"
                elif v7 == GPIO.LOW and v8 == GPIO.LOW:
                    active = "--> BOTH TRIGGERED"
                else:
                    active = "--> NO OBJECT (Red LED GPIO 20 ON)"

                print(f"[{ts}] GPIO 7: {status7:<10} | GPIO 8: {status8:<10} {active}")

            time.sleep(0.05)
    except KeyboardInterrupt:
        GPIO.output(13, GPIO.LOW)
        GPIO.output(20, GPIO.LOW)
        print("\nSlot 3 pin check stopped.")


def direct_led_hardware_test():
    """Directly forces LEDs ON to verify physical wiring independently of IR sensors."""
    print("\n" + "=" * 55)
    print("DIRECT LED HARDWARE TEST (Bypasses IR Sensors)")
    print("=" * 55)
    print("Use this to check if Slot 3 LED wiring/polarity is working!\n")
    print("1. Turn ON Slot 3 GREEN LED (GPIO 13 / Pin 33)")
    print("2. Turn ON Slot 3 RED LED   (GPIO 20 / Pin 38)")
    print("3. Blink Slot 3 GREEN LED 5 times")
    print("4. Blink Slot 3 RED LED 5 times")
    print("5. Test ALL LEDs in sequence (Slot 1 -> Slot 2 -> Slot 3)")
    print("0. Back to Main Menu")

    choice = input("\nEnter choice [0-5]: ").strip()

    if choice == "1":
        print("Turning ON Slot 3 GREEN (GPIO 13)... Press Enter to turn OFF.")
        GPIO.output(13, GPIO.HIGH)
        input()
        GPIO.output(13, GPIO.LOW)

    elif choice == "2":
        print("Turning ON Slot 3 RED (GPIO 20)... Press Enter to turn OFF.")
        GPIO.output(20, GPIO.HIGH)
        input()
        GPIO.output(20, GPIO.LOW)

    elif choice == "3":
        print("Blinking Slot 3 GREEN (GPIO 13) 5 times...")
        for _ in range(5):
            GPIO.output(13, GPIO.HIGH)
            time.sleep(0.4)
            GPIO.output(13, GPIO.LOW)
            time.sleep(0.3)
        print("Done.")

    elif choice == "4":
        print("Blinking Slot 3 RED (GPIO 20) 5 times...")
        for _ in range(5):
            GPIO.output(20, GPIO.HIGH)
            time.sleep(0.4)
            GPIO.output(20, GPIO.LOW)
            time.sleep(0.3)
        print("Done.")

    elif choice == "5":
        print("Testing all LEDs in sequence...")
        for slot, cfg in SLOTS_CONFIG.items():
            print(f" -> {cfg['name']} GREEN (GPIO {cfg['green_led']}) ON")
            GPIO.output(cfg["green_led"], GPIO.HIGH)
            time.sleep(0.8)
            GPIO.output(cfg["green_led"], GPIO.LOW)

            print(f" -> {cfg['name']} RED (GPIO {cfg['red_led']}) ON")
            GPIO.output(cfg["red_led"], GPIO.HIGH)
            time.sleep(0.8)
            GPIO.output(cfg["red_led"], GPIO.LOW)
        print("All LED sequence test completed.")


def main():
    setup()
    try:
        while True:
            print("\n" + "=" * 50)
            print("       IR SENSOR & LED DIAGNOSTIC TOOL")
            print("=" * 50)
            print("1. Test Slot 1 IR + LED (GPIO 4, GRN 5, RED 12)")
            print("2. Test Slot 2 IR + LED (GPIO 8, GRN 6, RED 16)")
            print("3. Test Slot 3 IR + LED (GPIO 7, GRN 13, RED 20)")
            print("4. Slot 3 Diagnostic (GPIO 7 vs 8 + Slot 3 LEDs)")
            print("5. Monitor ALL 3 Slots Live (IR + LEDs)")
            print("6. Direct LED Hardware Test (Force Slot 3 LED ON)")
            print("7. Exit")
            choice = input("Enter choice (1-7): ").strip()

            if choice == "1":
                test_single_slot(1)
            elif choice == "2":
                test_single_slot(2)
            elif choice == "3":
                test_single_slot(3)
            elif choice == "4":
                test_slot3_pin_check()
            elif choice == "5":
                test_all_slots_live()
            elif choice == "6":
                direct_led_hardware_test()
            elif choice == "7":
                break
            else:
                print("Invalid choice, select 1-7.")
    finally:
        all_leds_off()
        GPIO.cleanup()
        print("\nCleaned up GPIO. Done.")


if __name__ == "__main__":
    main()
