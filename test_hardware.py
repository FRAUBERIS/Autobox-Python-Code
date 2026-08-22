import time
import numpy as np
import requests
import RPi.GPIO as GPIO
from picamera2 import Picamera2
from pyzbar.pyzbar import decode
from RPLCD.i2c import CharLCD

API_BASE_URL = "http://192.168.11.130:8000"
API_KEYS = f"{API_BASE_URL}/api/keys"
API_AUTHENTICATE = f"{API_BASE_URL}/api/authenticate-qr"

MAIN_LOCK_PIN = 23
SLOT_PINS = {1: 17}

LED_GREEN_PINS = {1: 5}
LED_RED_PINS = {1: 12}

IR_SENSOR_PINS = {1: 4}

BUZZER_PIN = 18

ULTRASONIC_TRIG = 24
ULTRASONIC_ECHO = 25

LCD_I2C_ADDRESS = 0x27
LCD_I2C_PORT = 1

HAVE_RELAY_FEEDBACK = False
RELAY_FEEDBACK_PINS = {}

CAMERA_BLACK_THRESHOLD = 8

lcd = None
results = {}


def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    GPIO.setup(MAIN_LOCK_PIN, GPIO.OUT)
    GPIO.output(MAIN_LOCK_PIN, GPIO.LOW)

    for slot, pin in SLOT_PINS.items():
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

    for slot, pin in LED_GREEN_PINS.items():
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

    for slot, pin in LED_RED_PINS.items():
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

    for slot, pin in IR_SENSOR_PINS.items():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    GPIO.setup(BUZZER_PIN, GPIO.OUT)
    GPIO.output(BUZZER_PIN, GPIO.LOW)

    GPIO.setup(ULTRASONIC_TRIG, GPIO.OUT)
    GPIO.setup(ULTRASONIC_ECHO, GPIO.IN)
    GPIO.output(ULTRASONIC_TRIG, GPIO.LOW)

    if HAVE_RELAY_FEEDBACK:
        for name, pin in RELAY_FEEDBACK_PINS.items():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)


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


def test_laravel():
    print("\n[TEST 1/8] Testing Laravel API Connection...")
    try:
        start = time.time()
        res = requests.get(API_KEYS, timeout=5)
        ms = round((time.time() - start) * 1000, 1)
        if res.status_code == 200:
            keys = res.json().get("keys", [])
            print(f"  [PASS] Connected ({ms}ms). Found {len(keys)} key slot(s).")
            for k in keys:
                print(f"    Slot {k.get('slot_number')}: {k.get('key_name')} [{k.get('status')}]")
            results["Laravel Connection"] = "PASS"
            return True
        else:
            print(f"  [FAIL] HTTP {res.status_code}")
            results["Laravel Connection"] = f"FAIL ({res.status_code})"
            return False
    except Exception as e:
        print(f"  [FAIL] Connection error: {e}")
        results["Laravel Connection"] = "FAIL"
        return False


def test_lcd():
    global lcd
    print("\n[TEST 2/8] Testing 16x2 LCD Display...")
    try:
        lcd = CharLCD('PCF8574', LCD_I2C_ADDRESS, port=LCD_I2C_PORT, cols=16, rows=2)
        lcd.clear()
        lcd_print("AUTOBOX 1-Slot", "LCD: OK")
        print(f"  [PASS] LCD ACKed and accepted data at {hex(LCD_I2C_ADDRESS)}")
        results["16x2 LCD Display"] = "PASS"
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"  [FAIL] LCD error: {e}")
        results["16x2 LCD Display"] = "FAIL"
        lcd = None
        return False


def test_leds():
    print("\n[TEST 3/8] Testing Slot 1 Status LEDs (Green & Red)...")
    lcd_print("Testing LEDs...", "Slot 1 Green/Red")
    try:
        for slot, pin in LED_GREEN_PINS.items():
            print(f"  Slot {slot} GREEN (GPIO {pin}) ON")
            GPIO.output(pin, GPIO.HIGH)
            time.sleep(0.5)
            GPIO.output(pin, GPIO.LOW)

        for slot, pin in LED_RED_PINS.items():
            print(f"  Slot {slot} RED (GPIO {pin}) ON")
            GPIO.output(pin, GPIO.HIGH)
            time.sleep(0.5)
            GPIO.output(pin, GPIO.LOW)

        for pin in list(LED_GREEN_PINS.values()) + list(LED_RED_PINS.values()):
            GPIO.output(pin, GPIO.HIGH)
        time.sleep(0.5)
        for pin in list(LED_GREEN_PINS.values()) + list(LED_RED_PINS.values()):
            GPIO.output(pin, GPIO.LOW)

        print("  [ACTUATED] Pins toggled, confirm visually that LEDs lit")
        results["Status LEDs"] = "ACTUATED (verify manually)"
        return True
    except Exception as e:
        print(f"  [FAIL] LED error: {e}")
        results["Status LEDs"] = "FAIL"
        return False


def test_buzzer():
    print("\n[TEST 4/8] Testing Active Buzzer (1 Beep)...")
    lcd_print("Testing Buzzer", "Beep x1")
    try:
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        time.sleep(0.15)
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        print("  [ACTUATED] Pin toggled x1, confirm audibly that it beeped")
        results["Active Buzzer"] = "ACTUATED (verify manually)"
        return True
    except Exception as e:
        print(f"  [FAIL] Buzzer error: {e}")
        results["Active Buzzer"] = "FAIL"
        return False


def _check_relay_feedback(pin_key):
    pin = RELAY_FEEDBACK_PINS.get(pin_key)
    if pin is None:
        return None
    return GPIO.input(pin) == GPIO.LOW


def test_solenoids():
    print("\n[TEST 5/8] Testing Solenoid Relays (Main Lock + Slot 1)...")
    lcd_print("Testing Locks", "Relays click...")
    try:
        print(f"  Main Door Lock (GPIO {MAIN_LOCK_PIN}) -> TRIGGER")
        GPIO.output(MAIN_LOCK_PIN, GPIO.HIGH)
        time.sleep(0.6)
        main_fb = _check_relay_feedback("main_lock")
        GPIO.output(MAIN_LOCK_PIN, GPIO.LOW)

        slot_fb = {}
        for slot, pin in SLOT_PINS.items():
            print(f"  Slot {slot} Solenoid (GPIO {pin}) -> TRIGGER")
            GPIO.output(pin, GPIO.HIGH)
            time.sleep(0.6)
            slot_fb[slot] = _check_relay_feedback(f"slot_{slot}")
            GPIO.output(pin, GPIO.LOW)

    except Exception as e:
        print(f"  [FAIL] Solenoid error: {e}")
        results["Solenoid Relays"] = "FAIL"
        return False

    if HAVE_RELAY_FEEDBACK and main_fb is not None and all(v is not None for v in slot_fb.values()):
        all_ok = main_fb and all(slot_fb.values())
        if all_ok:
            print("  [PASS] Relay feedback confirmed on Main Lock and Slot 1")
            results["Solenoid Relays"] = "PASS"
            return True
        else:
            failed = (["Main Lock"] if not main_fb else []) + [f"Slot {s}" for s, ok in slot_fb.items() if not ok]
            print(f"  [FAIL] No feedback signal from: {', '.join(failed)}")
            results["Solenoid Relays"] = f"FAIL ({', '.join(failed)})"
            return False
    else:
        print("  [ACTUATED] Relays triggered, confirm manually you heard/felt both click")
        results["Solenoid Relays"] = "ACTUATED (verify manually)"
        return True


def test_ir_sensors():
    print("\n[TEST 6/8] Testing Slot 1 IR Key Presence Sensor...")
    lcd_print("Testing IR", "Read Slot 1...")
    try:
        status_list = []
        for slot, pin in IR_SENSOR_PINS.items():
            val = GPIO.input(pin)
            state = "KEY PRESENT" if val == GPIO.LOW else "KEY MISSING"
            print(f"  Slot {slot} IR Sensor (GPIO {pin}) -> Value: {val} ({state})")
            status_list.append(f"S{slot}:{state[:3]}")

        lcd_print("Slot 1 IR Sensor", " ".join(status_list))
        time.sleep(1.5)
        print("  [READ] Raw value captured, verify by moving a key in/out")
        results["IR Sensors"] = f"READ ({status_list[0]}, verify manually)"
        return True
    except Exception as e:
        print(f"  [FAIL] IR error: {e}")
        results["IR Sensors"] = "FAIL"
        return False


def get_single_distance():
    GPIO.output(ULTRASONIC_TRIG, GPIO.HIGH)
    time.sleep(0.00001)
    GPIO.output(ULTRASONIC_TRIG, GPIO.LOW)

    pulse_start = time.time()
    pulse_end = time.time()
    timeout = time.time() + 0.04

    while GPIO.input(ULTRASONIC_ECHO) == 0:
        pulse_start = time.time()
        if pulse_start > timeout:
            return None

    timeout = time.time() + 0.04
    while GPIO.input(ULTRASONIC_ECHO) == 1:
        pulse_end = time.time()
        if pulse_end > timeout:
            return None

    duration = pulse_end - pulse_start
    return round((duration * 34300) / 2, 1)


def test_ultrasonic():
    print("\n[TEST 7/8] Testing Ultrasonic Distance Sensor (5 live readings)...")
    lcd_print("Ultrasonic", "Measuring...")
    valid = 0
    dist = None
    for i in range(1, 6):
        dist = get_single_distance()
        if dist is not None and 2 <= dist <= 400:
            print(f"  Reading {i}/5: {dist} cm")
            lcd_print("Ultrasonic", f"{dist} cm")
            valid += 1
        else:
            print(f"  Reading {i}/5: Timeout / Out of range")
        time.sleep(0.3)

    if valid >= 3:
        print(f"  [PASS] Ultrasonic working ({dist} cm)")
        results["Ultrasonic Sensor"] = f"PASS ({dist}cm)"
        return True
    else:
        print("  [FAIL] Ultrasonic failed")
        results["Ultrasonic Sensor"] = "FAIL"
        return False


def test_camera():
    print("\n[TEST 8/8] Testing Camera & QR Scanner (5 seconds)...")
    print("  Hold a QR badge in front of camera (optional)...")
    lcd_print("Camera Active", "Hold QR badge...")
    try:
        picam = Picamera2()
        config = picam.create_preview_configuration(main={"size": (640, 480)})
        picam.configure(config)
        picam.start()

        qr_data = None
        last_frame = None
        start = time.time()
        while time.time() - start < 5:
            frame = picam.capture_array()
            last_frame = frame
            decoded = decode(frame)
            for obj in decoded:
                qr_data = obj.data.decode("utf-8").strip()
                print(f"  QR Detected: {qr_data}")
                break
            if qr_data:
                break
            time.sleep(0.1)

        picam.stop()
        picam.close()

        brightness = float(np.mean(last_frame)) if last_frame is not None else 0.0
        print(f"  Mean frame brightness: {brightness:.1f} (threshold {CAMERA_BLACK_THRESHOLD})")

        if brightness < CAMERA_BLACK_THRESHOLD:
            print("  [FAIL] Frame is effectively black")
            results["Camera & QR"] = "FAIL (black frame)"
            return False

        if qr_data:
            try:
                res = requests.post(API_AUTHENTICATE, json={"qr_token": qr_data}, timeout=5)
                print(f"  Laravel Response: {res.json()}")
                lcd_print("QR Verified", res.json().get("status", "OK"))
            except Exception as ex:
                print(f"  Auth API error: {ex}")
            results["Camera & QR"] = "PASS (QR Scanned)"
        else:
            results["Camera & QR"] = "PASS (Camera OK)"

        print("  [PASS] Camera operational, frame not black")
        return True
    except Exception as e:
        print(f"  [FAIL] Camera error: {e}")
        results["Camera & QR"] = "FAIL"
        return False


def main():
    print("=" * 55)
    print("      AUTOBOX 1-SLOT HARDWARE SELF-TEST")
    print("=" * 55)

    setup_gpio()

    test_laravel()
    test_lcd()
    test_leds()
    test_buzzer()
    test_solenoids()
    test_ir_sensors()
    test_ultrasonic()
    test_camera()

    print("\n" + "=" * 55)
    print("                  FINAL TEST SUMMARY")
    print("=" * 55)
    for comp, stat in results.items():
        print(f"  {comp:<24} : {stat}")
    print("=" * 55)

    time.sleep(2)
    if lcd:
        lcd.clear()
    GPIO.cleanup()
    print("GPIO Cleaned up. Done.\n")


if __name__ == "__main__":
    main()
