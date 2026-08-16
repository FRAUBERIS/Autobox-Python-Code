import time
import requests
import RPi.GPIO as GPIO
from picamera2 import Picamera2
from pyzbar.pyzbar import decode
from RPLCD.i2c import CharLCD
import smbus2

API_BASE_URL = "http://192.168.1.100/autobox/public"
API_AUTHENTICATE = f"{API_BASE_URL}/api/authenticate-qr"
API_KEY_STATUSES = f"{API_BASE_URL}/api/keys"
API_REPORT_MISSING = f"{API_BASE_URL}/api/key-missing"
API_SLIDER_EVENT = f"{API_BASE_URL}/api/slider-event"

REQUEST_TIMEOUT = 10
STATUS_POLL_INTERVAL = 30
UNLOCK_DURATION = 5
ULTRASONIC_DISTANCE_CM = 50

MAIN_LOCK_PIN = 23

SLOT_PINS = {
    1: 17,
    2: 27,
    3: 22,
}

LED_GREEN_PINS = {
    1: 5,
    2: 6,
    3: 13,
}

LED_RED_PINS = {
    1: 12,
    2: 16,
    3: 20,
}

IR_SENSOR_PINS = {
    1: 4,
    2: 8,
    3: 7,
}

BUZZER_PIN = 18
ULTRASONIC_TRIG = 24
ULTRASONIC_ECHO = 25

# 6V Yellow DC TT Gear Motor & Driver Configuration
SLIDER_MOTOR_IN1 = 19       # Motor Driver IN1 (GPIO 19 / Pin 35)
SLIDER_MOTOR_IN2 = 26       # Motor Driver IN2 (GPIO 26 / Pin 37)
SLIDER_MOTOR_ENA = 21       # Motor Driver ENA PWM speed control (GPIO 21 / Pin 40, set None if jumpered to 5V)
SLIDER_MOTOR_DURATION = 2.0 # Seconds for TT Gear motor to roll slider open/closed
SLIDER_MOTOR_SPEED = 80     # PWM speed percentage (0 to 100)

LCD_I2C_ADDRESS = 0x27
LCD_I2C_PORT = 1

lcd = None
pwm_ena = None
slider_state = "CLOSED"  # State can be: "CLOSED", "OPEN", "OPENING", "CLOSING"


def setup_lcd():
    global lcd
    try:
        lcd = CharLCD('PCF8574', LCD_I2C_ADDRESS, port=LCD_I2C_PORT, cols=16, rows=2)
        lcd.clear()
        lcd_print("AUTOBOX Ready", "Scan QR Code")
    except Exception as e:
        print(f"[LCD] Failed to init: {e}")
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
    except Exception as e:
        print(f"[LCD] Write error: {e}")


def setup_gpio():
    global pwm_ena
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
        GPIO.output(pin, GPIO.HIGH)

    for slot, pin in IR_SENSOR_PINS.items():
        GPIO.setup(pin, GPIO.IN)

    GPIO.setup(BUZZER_PIN, GPIO.OUT)
    GPIO.output(BUZZER_PIN, GPIO.LOW)

    GPIO.setup(ULTRASONIC_TRIG, GPIO.OUT)
    GPIO.setup(ULTRASONIC_ECHO, GPIO.IN)
    GPIO.output(ULTRASONIC_TRIG, GPIO.LOW)

    # 6V TT Gear Motor driver pins setup
    GPIO.setup(SLIDER_MOTOR_IN1, GPIO.OUT)
    GPIO.setup(SLIDER_MOTOR_IN2, GPIO.OUT)

    if SLIDER_MOTOR_ENA is not None:
        GPIO.setup(SLIDER_MOTOR_ENA, GPIO.OUT)
        pwm_ena = GPIO.PWM(SLIDER_MOTOR_ENA, 1000)  # 1kHz PWM frequency
        pwm_ena.start(0)

    stop_slider()

    print("[GPIO] All pins initialized (including 6V TT Gear Motor).")


def stop_slider():
    GPIO.output(SLIDER_MOTOR_IN1, GPIO.LOW)
    GPIO.output(SLIDER_MOTOR_IN2, GPIO.LOW)
    if pwm_ena:
        pwm_ena.ChangeDutyCycle(0)


def open_slider():
    global slider_state
    if slider_state == "OPEN":
        return
    print("[SLIDER] Hand detected -> Rolling 6V TT Gear Motor OPEN...")
    lcd_print("Hand Detected", "Opening Slider...")
    slider_state = "OPENING"
    
    if pwm_ena:
        pwm_ena.ChangeDutyCycle(SLIDER_MOTOR_SPEED)
    
    GPIO.output(SLIDER_MOTOR_IN1, GPIO.HIGH)
    GPIO.output(SLIDER_MOTOR_IN2, GPIO.LOW)
    time.sleep(SLIDER_MOTOR_DURATION)
    stop_slider()
    slider_state = "OPEN"
    print("[SLIDER] Slider fully OPEN.")
    report_slider_event("opened", "Hand detected by Ultrasonic sensor")


def close_slider():
    global slider_state
    if slider_state == "CLOSED":
        return
    print("[SLIDER] No hand detected -> Rolling 6V TT Gear Motor CLOSE...")
    lcd_print("No Hand Detected", "Closing Slider...")
    slider_state = "CLOSING"
    
    if pwm_ena:
        pwm_ena.ChangeDutyCycle(SLIDER_MOTOR_SPEED)
        
    GPIO.output(SLIDER_MOTOR_IN1, GPIO.LOW)
    GPIO.output(SLIDER_MOTOR_IN2, GPIO.HIGH)
    time.sleep(SLIDER_MOTOR_DURATION)
    stop_slider()
    slider_state = "CLOSED"
    print("[SLIDER] Slider fully CLOSED.")
    report_slider_event("closed", "No hand detected by Ultrasonic sensor")
    lcd_print("AUTOBOX Ready", "Scan QR Code")


def report_slider_event(state, reason=""):
    try:
        payload = {"state": state, "reason": reason}
        requests.post(API_SLIDER_EVENT, json=payload, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        print(f"[SLIDER API] Failed to send slider event: {e}")


def unlock_main_door():
    print("[MAIN LOCK] Box door UNLOCKED")
    GPIO.output(MAIN_LOCK_PIN, GPIO.HIGH)
    time.sleep(UNLOCK_DURATION)
    GPIO.output(MAIN_LOCK_PIN, GPIO.LOW)
    print("[MAIN LOCK] Box door LOCKED")


def unlock_slot(slot_number):
    pin = SLOT_PINS.get(slot_number)
    if pin is None:
        print(f"[ERROR] Slot {slot_number} not in SLOT_PINS.")
        return
    print(f"[UNLOCK] Slot #{slot_number} UNLOCKED for {UNLOCK_DURATION}s")
    GPIO.output(pin, GPIO.HIGH)
    if slot_number in LED_GREEN_PINS:
        GPIO.output(LED_GREEN_PINS[slot_number], GPIO.HIGH)
    if slot_number in LED_RED_PINS:
        GPIO.output(LED_RED_PINS[slot_number], GPIO.LOW)
    beep(1)
    time.sleep(UNLOCK_DURATION)
    GPIO.output(pin, GPIO.LOW)
    if slot_number in LED_GREEN_PINS:
        GPIO.output(LED_GREEN_PINS[slot_number], GPIO.LOW)
    if slot_number in LED_RED_PINS:
        GPIO.output(LED_RED_PINS[slot_number], GPIO.HIGH)
    print(f"[LOCK] Slot #{slot_number} LOCKED")


def deny_access():
    beep(3)
    if all(p in LED_RED_PINS for p in [1, 2, 3]):
        for slot in LED_RED_PINS:
            GPIO.output(LED_RED_PINS[slot], GPIO.HIGH)


def beep(times=1, duration=0.1):
    for _ in range(times):
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        time.sleep(duration)
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        time.sleep(0.1)


def get_distance_cm():
    GPIO.output(ULTRASONIC_TRIG, GPIO.HIGH)
    time.sleep(0.00001)
    GPIO.output(ULTRASONIC_TRIG, GPIO.LOW)
    pulse_start = time.time()
    pulse_end = time.time()
    timeout = time.time() + 0.04
    while GPIO.input(ULTRASONIC_ECHO) == 0:
        pulse_start = time.time()
        if pulse_start > timeout:
            return 999
    timeout = time.time() + 0.04
    while GPIO.input(ULTRASONIC_ECHO) == 1:
        pulse_end = time.time()
        if pulse_end > timeout:
            return 999
    duration = pulse_end - pulse_start
    distance = (duration * 34300) / 2
    return round(distance, 2)


def person_detected():
    distance = get_distance_cm()
    print(f"[ULTRASONIC] Distance: {distance} cm")
    return distance <= ULTRASONIC_DISTANCE_CM


def is_key_present(slot_number):
    pin = IR_SENSOR_PINS.get(slot_number)
    if pin is None:
        return True
    return GPIO.input(pin) == GPIO.LOW


def check_all_ir_sensors():
    missing_slots = []
    for slot, pin in IR_SENSOR_PINS.items():
        if not is_key_present(slot):
            missing_slots.append(slot)
    return missing_slots


def scan_qr_from_camera():
    picam = Picamera2()
    config = picam.create_preview_configuration(main={"size": (640, 480)})
    picam.configure(config)
    picam.start()
    print("[CAMERA] Scanning for QR code...")
    lcd_print("Scanning QR...", "Hold steady")
    qr_data = None
    start_time = time.time()
    while time.time() - start_time < 10:
        frame = picam.capture_array()
        decoded = decode(frame)
        for obj in decoded:
            qr_data = obj.data.decode("utf-8").strip()
            print(f"[CAMERA] QR Detected: {qr_data}")
            break
        if qr_data:
            break
        time.sleep(0.1)
    picam.stop()
    picam.close()
    return qr_data


def authenticate_qr(qr_token, slot_number=None):
    payload = {"qr_token": qr_token}
    if slot_number is not None:
        payload["slot_number"] = slot_number
    try:
        print(f"[API] POST {API_AUTHENTICATE} | Payload: {payload}")
        response = requests.post(API_AUTHENTICATE, json=payload, timeout=REQUEST_TIMEOUT)
        data = response.json()
        print(f"[API] Response ({response.status_code}): {data}")
        return data
    except requests.exceptions.ConnectionError:
        print("[ERROR] Cannot connect to server.")
        return None
    except requests.exceptions.Timeout:
        print("[ERROR] API request timed out.")
        return None
    except Exception as e:
        print(f"[ERROR] {e}")
        return None


def get_key_statuses():
    try:
        response = requests.get(API_KEY_STATUSES, timeout=REQUEST_TIMEOUT)
        data = response.json()
        if data.get("success"):
            return data.get("keys", [])
    except Exception as e:
        print(f"[ERROR] Failed to get key statuses: {e}")
    return []


def report_missing_key(slot_number):
    try:
        response = requests.post(API_REPORT_MISSING, json={"slot_number": slot_number}, timeout=REQUEST_TIMEOUT)
        data = response.json()
        print(f"[API] Report Missing Slot #{slot_number}: {data}")
        return data.get("success", False)
    except Exception as e:
        print(f"[ERROR] Failed to report missing key: {e}")
        return False


def process_scan(qr_token):
    lcd_print("Verifying...", "Please wait")
    result = authenticate_qr(qr_token)

    if result is None:
        lcd_print("Server Error", "Check Network")
        print("[ERROR] No response from server.")
        deny_access()
        return

    if result.get("success") and result.get("status") == "GRANTED":
        slot = result.get("slot_number")
        action = result.get("action")
        user_name = result.get("user_name", "")
        key_name = result.get("key_name", "")
        print(f"ACCESS GRANTED | User: {user_name} | Action: {action} | Slot: #{slot}")

        lcd_print(f"GRANTED: {action}", user_name[:16])
        time.sleep(1)
        lcd_print(f"Slot #{slot}", key_name[:16])

        if slot:
            unlock_main_door()
            unlock_slot(slot)
        else:
            lcd_print("No Slot Found", "Contact Admin")
            deny_access()
    else:
        message = result.get("message", "Access Denied")
        print(f"ACCESS DENIED: {message}")
        lcd_print("ACCESS DENIED", message[:16])
        deny_access()

    time.sleep(2)
    lcd_print("AUTOBOX Ready", "Scan QR Code")


def run_ir_check():
    missing_slots = check_all_ir_sensors()
    for slot in missing_slots:
        print(f"[IR] Slot #{slot} key is MISSING — reporting to server.")
        lcd_print(f"Slot #{slot} Missing", "Reporting...")
        report_missing_key(slot)
        if slot in LED_RED_PINS:
            GPIO.output(LED_RED_PINS[slot], GPIO.HIGH)
        if slot in LED_GREEN_PINS:
            GPIO.output(LED_GREEN_PINS[slot], GPIO.LOW)
    if missing_slots:
        time.sleep(1)
        lcd_print("AUTOBOX Ready", "Scan QR Code")


def main():
    print("=" * 50)
    print("  AUTOBOX - Raspberry Pi Controller")
    print("=" * 50)

    setup_gpio()
    setup_lcd()

    print("[INFO] Testing server connection...")
    keys = get_key_statuses()
    if keys:
        print(f"[INFO] Connected. {len(keys)} slot(s) online.")
        lcd_print("Server Connected", f"{len(keys)} Slots Active")
    else:
        print("[WARN] Server unreachable. Running in offline mode.")
        lcd_print("Server Offline", "Retry on scan")
    time.sleep(2)
    lcd_print("AUTOBOX Ready", "Scan QR Code")

    last_poll = time.time()
    last_ir_check = time.time()

    try:
        while True:
            if time.time() - last_ir_check >= 5:
                run_ir_check()
                last_ir_check = time.time()

            hand_present = person_detected()

            if hand_present:
                if slider_state != "OPEN":
                    open_slider()

                print("[ULTRASONIC] Hand detected. Scanning for QR code...")
                lcd_print("Hand Detected", "Scanning QR...")
                qr_token = scan_qr_from_camera()
                if qr_token:
                    process_scan(qr_token)
                else:
                    print("[CAMERA] No QR detected within scan window.")
            else:
                if slider_state != "CLOSED":
                    close_slider()

            if time.time() - last_poll >= STATUS_POLL_INTERVAL:
                print("[POLL] Fetching key statuses...")
                keys = get_key_statuses()
                for k in keys:
                    print(f"  Slot #{k['slot_number']} - {k['key_name']}: {k['status'].upper()}")
                last_poll = time.time()

            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\n[INFO] Shutting down...")
        lcd_print("Shutting Down", "Goodbye!")

    finally:
        stop_slider()
        if lcd:
            lcd.clear()
        GPIO.cleanup()
        print("[GPIO] Cleaned up.")


if __name__ == "__main__":
    main()
