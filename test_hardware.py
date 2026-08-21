import time
import requests
import RPi.GPIO as GPIO
from picamera2 import Picamera2
from pyzbar.pyzbar import decode
from RPLCD.i2c import CharLCD

API_BASE_URL = "http://192.168.1.100:8000"
API_KEYS = f"{API_BASE_URL}/api/keys"
API_AUTHENTICATE = f"{API_BASE_URL}/api/authenticate-qr"

ULTRASONIC_TRIG = 24
ULTRASONIC_ECHO = 25

LED_GREEN_PINS = {1: 5, 2: 6, 3: 13}
LED_RED_PINS = {1: 12, 2: 16, 3: 20}

LCD_I2C_ADDRESS = 0x27
LCD_I2C_PORT = 1

lcd = None
results = {}

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    GPIO.setup(ULTRASONIC_TRIG, GPIO.OUT)
    GPIO.setup(ULTRASONIC_ECHO, GPIO.IN)
    GPIO.output(ULTRASONIC_TRIG, GPIO.LOW)

    for slot, pin in LED_GREEN_PINS.items():
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

    for slot, pin in LED_RED_PINS.items():
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

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

def test_laravel_connection():
    print("\n[TEST 1/5] Testing Laravel API Connection...")
    print(f"  Target URL: {API_KEYS}")
    try:
        start = time.time()
        response = requests.get(API_KEYS, timeout=5)
        latency = round((time.time() - start) * 1000, 1)

        if response.status_code == 200:
            data = response.json()
            keys = data.get("keys", [])
            print(f"  [PASS] Connected to Laravel ({latency}ms)")
            print(f"  Found {len(keys)} key slot(s) in database:")
            for k in keys:
                print(f"    Slot #{k.get('slot_number')}: {k.get('key_name')} [{k.get('status').upper()}]")
            results["Laravel Connection"] = "PASS"
            return True
        else:
            print(f"  [FAIL] HTTP {response.status_code}")
            results["Laravel Connection"] = f"FAIL (HTTP {response.status_code})"
            return False
    except Exception as e:
        print(f"  [FAIL] Cannot connect: {e}")
        results["Laravel Connection"] = "FAIL"
        return False

def test_lcd():
    global lcd
    print("\n[TEST 2/5] Testing 16x2 I2C LCD Display...")
    try:
        lcd = CharLCD('PCF8574', LCD_I2C_ADDRESS, port=LCD_I2C_PORT, cols=16, rows=2)
        lcd.clear()
        lcd_print("AUTOBOX Test", "16x2 LCD: OK")
        print(f"  [PASS] LCD initialized at {hex(LCD_I2C_ADDRESS)}")
        results["16x2 LCD Display"] = "PASS"
        time.sleep(2)
        return True
    except Exception as e:
        print(f"  [FAIL] LCD error: {e}")
        results["16x2 LCD Display"] = "FAIL"
        lcd = None
        return False

def test_leds():
    print("\n[TEST 3/5] Testing Slot LEDs...")
    lcd_print("Testing LEDs...", "Watch lights")
    try:
        for slot, pin in LED_GREEN_PINS.items():
            print(f"  Slot #{slot} GREEN (GPIO {pin}) -> ON")
            GPIO.output(pin, GPIO.HIGH)
            time.sleep(0.4)
            GPIO.output(pin, GPIO.LOW)

        for slot, pin in LED_RED_PINS.items():
            print(f"  Slot #{slot} RED (GPIO {pin}) -> ON")
            GPIO.output(pin, GPIO.HIGH)
            time.sleep(0.4)
            GPIO.output(pin, GPIO.LOW)

        for pin in list(LED_GREEN_PINS.values()) + list(LED_RED_PINS.values()):
            GPIO.output(pin, GPIO.HIGH)
        time.sleep(0.5)
        for pin in list(LED_GREEN_PINS.values()) + list(LED_RED_PINS.values()):
            GPIO.output(pin, GPIO.LOW)

        print("  [PASS] LED sequence complete")
        results["Status LEDs"] = "PASS"
        return True
    except Exception as e:
        print(f"  [FAIL] LED error: {e}")
        results["Status LEDs"] = "FAIL"
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
    distance = (duration * 34300) / 2
    return round(distance, 1)

def test_ultrasonic():
    print("\n[TEST 4/5] Testing Ultrasonic Distance Sensor...")
    lcd_print("Ultrasonic Test", "Measuring...")
    valid_readings = 0
    dist = None
    for i in range(1, 6):
        dist = get_single_distance()
        if dist is not None and 2 <= dist <= 400:
            print(f"  Reading {i}/5: {dist} cm")
            lcd_print("Ultrasonic", f"{dist} cm")
            valid_readings += 1
        else:
            print(f"  Reading {i}/5: Out of range / Timeout")
        time.sleep(0.4)

    if valid_readings >= 3:
        print("  [PASS] Ultrasonic working")
        results["Ultrasonic Sensor"] = f"PASS ({dist}cm)"
        return True
    else:
        print("  [FAIL] Ultrasonic failed")
        results["Ultrasonic Sensor"] = "FAIL"
        return False

def test_camera_and_qr():
    print("\n[TEST 5/5] Testing Camera & QR...")
    lcd_print("Camera Active", "Scanning...")
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
    print("=" * 50)
    print("     AUTOBOX HARDWARE & SERVER SELF-TEST")
    print("=" * 50)

    setup_gpio()

    test_laravel_connection()
    test_lcd()
    test_leds()
    test_ultrasonic()
    test_camera_and_qr()

    print("\n" + "=" * 50)
    print("                TEST RESULTS")
    print("=" * 50)
    for comp, stat in results.items():
        print(f"  {comp:<22} : {stat}")
    print("=" * 50)

    time.sleep(2)
    if lcd:
        lcd.clear()
    GPIO.cleanup()
    print("GPIO Cleaned up. Done.\n")

if __name__ == "__main__":
    main()
