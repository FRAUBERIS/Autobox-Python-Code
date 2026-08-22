import time
import requests
import RPi.GPIO as GPIO
from picamera2 import Picamera2
from pyzbar.pyzbar import decode
from RPLCD.i2c import CharLCD

API_BASE_URL = "http://192.168.1.100:8000"
API_KEYS = f"{API_BASE_URL}/api/keys"
API_AUTHENTICATE = f"{API_BASE_URL}/api/authenticate-qr"

MAIN_LOCK_PIN = 23
SLOT_PINS = {1: 17}

LED_GREEN_PINS = {1: 5}
LED_RED_PINS = {1: 12}

IR_SENSOR_PINS = {1: 4}

BUZZER_PIN = 18
FAN_PIN = 14

ULTRASONIC_TRIG = 24
ULTRASONIC_ECHO = 25

LCD_I2C_ADDRESS = 0x27
LCD_I2C_PORT = 1

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

    GPIO.setup(FAN_PIN, GPIO.OUT)
    GPIO.output(FAN_PIN, GPIO.LOW)

    GPIO.setup(ULTRASONIC_TRIG, GPIO.OUT)
    GPIO.setup(ULTRASONIC_ECHO, GPIO.IN)
    GPIO.output(ULTRASONIC_TRIG, GPIO.LOW)

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
    print("\n[TEST 1/9] Testing Laravel API Connection...")
    try:
        start = time.time()
        res = requests.get(API_KEYS, timeout=5)
        ms = round((time.time() - start) * 1000, 1)
        if res.status_code == 200:
            keys = res.json().get("keys", [])
            print(f"  [PASS] Connected ({ms}ms). Found {len(keys)} key slot(s).")
            for k in keys:
                print(f"    Slot #{k.get('slot_number')}: {k.get('key_name')} [{k.get('status')}]")
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
    print("\n[TEST 2/9] Testing 16x2 LCD Display...")
    try:
        lcd = CharLCD('PCF8574', LCD_I2C_ADDRESS, port=LCD_I2C_PORT, cols=16, rows=2)
        lcd.clear()
        lcd_print("AUTOBOX 1-Slot", "LCD: OK")
        print(f"  [PASS] LCD OK at {hex(LCD_I2C_ADDRESS)}")
        results["16x2 LCD Display"] = "PASS"
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"  [FAIL] LCD error: {e}")
        results["16x2 LCD Display"] = "FAIL"
        lcd = None
        return False

def test_leds():
    print("\n[TEST 3/9] Testing Slot 1 Status LEDs (Green & Red)...")
    lcd_print("Testing LEDs...", "Slot 1 Green/Red")
    try:
        for slot, pin in LED_GREEN_PINS.items():
            print(f"  Slot #{slot} GREEN (GPIO {pin}) ON")
            GPIO.output(pin, GPIO.HIGH)
            time.sleep(0.5)
            GPIO.output(pin, GPIO.LOW)

        for slot, pin in LED_RED_PINS.items():
            print(f"  Slot #{slot} RED (GPIO {pin}) ON")
            GPIO.output(pin, GPIO.HIGH)
            time.sleep(0.5)
            GPIO.output(pin, GPIO.LOW)

        for pin in list(LED_GREEN_PINS.values()) + list(LED_RED_PINS.values()):
            GPIO.output(pin, GPIO.HIGH)
        time.sleep(0.5)
        for pin in list(LED_GREEN_PINS.values()) + list(LED_RED_PINS.values()):
            GPIO.output(pin, GPIO.LOW)

        print("  [PASS] Slot 1 LEDs OK")
        results["Status LEDs"] = "PASS"
        return True
    except Exception as e:
        print(f"  [FAIL] LED error: {e}")
        results["Status LEDs"] = "FAIL"
        return False

def test_buzzer():
    print("\n[TEST 4/9] Testing Active Buzzer...")
    lcd_print("Testing Buzzer", "Beep x2")
    try:
        for i in range(2):
            GPIO.output(BUZZER_PIN, GPIO.HIGH)
            time.sleep(0.1)
            GPIO.output(BUZZER_PIN, GPIO.LOW)
            time.sleep(0.1)
        print("  [PASS] Buzzer activated (2 beeps)")
        results["Active Buzzer"] = "PASS"
        return True
    except Exception as e:
        print(f"  [FAIL] Buzzer error: {e}")
        results["Active Buzzer"] = "FAIL"
        return False

def test_fan():
    print("\n[TEST 5/9] Testing Brushless Fan DC 5V (Spinning 3s)...")
    lcd_print("Testing Fan", "Spinning 3s...")
    try:
        GPIO.output(FAN_PIN, GPIO.HIGH)
        print("  Fan ON (GPIO 14 HIGH)")
        time.sleep(3)
        GPIO.output(FAN_PIN, GPIO.LOW)
        print("  Fan OFF")
        print("  [PASS] Fan switch pulse completed")
        results["Brushless Fan DC 5V"] = "PASS"
        return True
    except Exception as e:
        print(f"  [FAIL] Fan error: {e}")
        results["Brushless Fan DC 5V"] = "FAIL"
        return False

def test_solenoids():
    print("\n[TEST 6/9] Testing Solenoid Relays (Main Lock + Slot 1)...")
    lcd_print("Testing Locks", "Relays click...")
    try:
        print(f"  Main Door Lock (GPIO {MAIN_LOCK_PIN}) -> TRIGGER")
        GPIO.output(MAIN_LOCK_PIN, GPIO.HIGH)
        time.sleep(0.6)
        GPIO.output(MAIN_LOCK_PIN, GPIO.LOW)

        for slot, pin in SLOT_PINS.items():
            print(f"  Slot #{slot} Solenoid (GPIO {pin}) -> TRIGGER")
            GPIO.output(pin, GPIO.HIGH)
            time.sleep(0.6)
            GPIO.output(pin, GPIO.LOW)

        print("  [PASS] Main Door & Slot 1 Solenoid relays triggered")
        results["Solenoid Relays"] = "PASS"
        return True
    except Exception as e:
        print(f"  [FAIL] Solenoid error: {e}")
        results["Solenoid Relays"] = "FAIL"
        return False

def test_ir_sensors():
    print("\n[TEST 7/9] Testing Slot 1 IR Key Presence Sensor...")
    lcd_print("Testing IR", "Read Slot 1...")
    try:
        status_list = []
        for slot, pin in IR_SENSOR_PINS.items():
            val = GPIO.input(pin)
            state = "KEY PRESENT" if val == GPIO.LOW else "KEY MISSING"
            print(f"  Slot #{slot} IR Sensor (GPIO {pin}) -> Value: {val} ({state})")
            status_list.append(f"S{slot}:{state[:3]}")

        lcd_print("Slot 1 IR Sensor", " ".join(status_list))
        time.sleep(1.5)
        print("  [PASS] Slot 1 IR sensor pin read successfully")
        results["IR Sensors"] = "PASS"
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
    print("\n[TEST 8/9] Testing Ultrasonic Distance Sensor (5 live readings)...")
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
    print("\n[TEST 9/9] Testing Camera & QR Scanner (5 seconds)...")
    print("  Hold a QR badge in front of camera (optional)...")
    lcd_print("Camera Active", "Hold QR badge...")
    try:
        picam = Picamera2()
        config = picam.create_preview_configuration(main={"size": (640, 480)})
        picam.configure(config)
        picam.start()

        qr_data = None
        start = time.time()
        while time.time() - start < 5:
            frame = picam.capture_array()
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

        print("  [PASS] Camera operational")
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
    test_fan()
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
