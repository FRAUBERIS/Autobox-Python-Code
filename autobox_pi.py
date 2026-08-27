import os
import time
import json
from datetime import datetime
import requests
import RPi.GPIO as GPIO
from picamera2 import Picamera2
from pyzbar.pyzbar import decode
from RPLCD.i2c import CharLCD
import smbus2

ENABLE_LCD = True
ENABLE_CAMERA = True
ENABLE_ULTRASONIC = True
ENABLE_LEDS = True
ENABLE_IR_SENSORS = True
ENABLE_SOLENOIDS = True
ENABLE_MOTOR = True

KEY_PRESENT_STATE = GPIO.LOW

API_BASE_URL = "http://192.168.11.130:8000"
API_AUTHENTICATE = f"{API_BASE_URL}/api/authenticate-qr"
API_KEY_STATUSES = f"{API_BASE_URL}/api/keys"
API_REPORT_MISSING = f"{API_BASE_URL}/api/key-missing"
API_OFFLINE_CACHE = f"{API_BASE_URL}/api/offline-cache"
API_SYNC_LOGS = f"{API_BASE_URL}/api/sync-offline-logs"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OFFLINE_CACHE_FILE = os.path.join(SCRIPT_DIR, "offline_cache.json")
PENDING_SYNC_FILE = os.path.join(SCRIPT_DIR, "pending_sync_logs.json")

CACHE_REFRESH_INTERVAL = 300
SYNC_RETRY_INTERVAL = 60

REQUEST_TIMEOUT = 10
STATUS_POLL_INTERVAL = 30
UNLOCK_DURATION = 3
ULTRASONIC_DISTANCE_CM = 20
MOTOR_RUN_TIME = 2.0
NO_HAND_WAIT_SECONDS = 5

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
    2: 7,
    3: 8,
}

ULTRASONIC_TRIG = 24
ULTRASONIC_ECHO = 25

MOTOR_IN1 = 19
MOTOR_IN2 = 26
MOTOR_ENA = 21

LCD_I2C_ADDRESS = 0x27
LCD_I2C_PORT = 1

lcd = None


def setup_lcd():
    global lcd
    if not ENABLE_LCD:
        return
    try:
        lcd = CharLCD('PCF8574', LCD_I2C_ADDRESS, port=LCD_I2C_PORT, cols=16, rows=2)
        lcd.clear()
        lcd_print("AUTOBOX Ready", "Scan QR Code")
    except Exception as e:
        print(f"[LCD ERROR] {e}")
        lcd = None


def lcd_print(line1="", line2=""):
    if not lcd or not ENABLE_LCD:
        return
    try:
        lcd.clear()
        lcd.cursor_pos = (0, 0)
        lcd.write_string(line1[:16])
        lcd.cursor_pos = (1, 0)
        lcd.write_string(line2[:16])
    except Exception as e:
        print(f"[LCD Write error] {e}")


def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    if ENABLE_SOLENOIDS:
        GPIO.setup(MAIN_LOCK_PIN, GPIO.OUT)
        GPIO.output(MAIN_LOCK_PIN, GPIO.LOW)
        for slot, pin in SLOT_PINS.items():
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)

    if ENABLE_LEDS:
        for slot, pin in LED_GREEN_PINS.items():
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)
        for slot, pin in LED_RED_PINS.items():
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)

    if ENABLE_IR_SENSORS:
        for slot, pin in IR_SENSOR_PINS.items():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    if ENABLE_ULTRASONIC:
        GPIO.setup(ULTRASONIC_TRIG, GPIO.OUT)
        GPIO.setup(ULTRASONIC_ECHO, GPIO.IN)
        GPIO.output(ULTRASONIC_TRIG, GPIO.LOW)

    if ENABLE_MOTOR:
        GPIO.setup(MOTOR_IN1, GPIO.OUT)
        GPIO.setup(MOTOR_IN2, GPIO.OUT)
        GPIO.setup(MOTOR_ENA, GPIO.OUT)
        GPIO.output(MOTOR_IN1, GPIO.LOW)
        GPIO.output(MOTOR_IN2, GPIO.LOW)
        GPIO.output(MOTOR_ENA, GPIO.LOW)


def slider_open():
    if not ENABLE_MOTOR:
        return
    GPIO.output(MOTOR_ENA, GPIO.HIGH)
    GPIO.output(MOTOR_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_IN2, GPIO.LOW)
    time.sleep(MOTOR_RUN_TIME)
    GPIO.output(MOTOR_IN1, GPIO.LOW)
    GPIO.output(MOTOR_IN2, GPIO.LOW)
    GPIO.output(MOTOR_ENA, GPIO.LOW)


def slider_close():
    if not ENABLE_MOTOR:
        return
    GPIO.output(MOTOR_ENA, GPIO.HIGH)
    GPIO.output(MOTOR_IN1, GPIO.LOW)
    GPIO.output(MOTOR_IN2, GPIO.HIGH)
    time.sleep(MOTOR_RUN_TIME)
    GPIO.output(MOTOR_IN1, GPIO.LOW)
    GPIO.output(MOTOR_IN2, GPIO.LOW)
    GPIO.output(MOTOR_ENA, GPIO.LOW)


def wait_no_hand_and_close():
    if not ENABLE_MOTOR:
        return
    no_hand_start = None
    while True:
        if person_detected():
            no_hand_start = None
            lcd_print("Hand Detected", "Waiting...")
            time.sleep(0.3)
        else:
            if no_hand_start is None:
                no_hand_start = time.time()
            elapsed = time.time() - no_hand_start
            remaining = max(0, int(NO_HAND_WAIT_SECONDS - elapsed))
            lcd_print("No Hand Detected", f"Closing in {remaining}s")
            if elapsed >= NO_HAND_WAIT_SECONDS:
                break
            time.sleep(0.2)
    lcd_print("Closing Door...", "Please clear")
    slider_close()


def unlock_main_door():
    if ENABLE_SOLENOIDS:
        GPIO.output(MAIN_LOCK_PIN, GPIO.HIGH)
        time.sleep(UNLOCK_DURATION)
        GPIO.output(MAIN_LOCK_PIN, GPIO.LOW)


def unlock_slot(slot_number):
    if ENABLE_SOLENOIDS:
        pin = SLOT_PINS.get(slot_number)
        if pin:
            GPIO.output(pin, GPIO.HIGH)

    if ENABLE_LEDS:
        if slot_number in LED_GREEN_PINS:
            GPIO.output(LED_GREEN_PINS[slot_number], GPIO.HIGH)
        if slot_number in LED_RED_PINS:
            GPIO.output(LED_RED_PINS[slot_number], GPIO.LOW)

    time.sleep(UNLOCK_DURATION)

    if ENABLE_SOLENOIDS:
        pin = SLOT_PINS.get(slot_number)
        if pin:
            GPIO.output(pin, GPIO.LOW)


def deny_access():
    if ENABLE_LEDS:
        for _ in range(3):
            for slot in LED_RED_PINS:
                GPIO.output(LED_RED_PINS[slot], GPIO.LOW)
            time.sleep(0.15)
            for slot in LED_RED_PINS:
                GPIO.output(LED_RED_PINS[slot], GPIO.HIGH)
            time.sleep(0.15)
        update_key_presence_and_leds()


def get_distance_cm():
    if not ENABLE_ULTRASONIC:
        return 999

    readings = []
    for _ in range(3):
        GPIO.output(ULTRASONIC_TRIG, GPIO.LOW)
        time.sleep(0.002)
        GPIO.output(ULTRASONIC_TRIG, GPIO.HIGH)
        time.sleep(0.00001)
        GPIO.output(ULTRASONIC_TRIG, GPIO.LOW)

        pulse_start = time.time()
        pulse_end = time.time()
        timeout = time.time() + 0.03

        while GPIO.input(ULTRASONIC_ECHO) == 0:
            pulse_start = time.time()
            if pulse_start > timeout:
                break

        timeout = time.time() + 0.03
        while GPIO.input(ULTRASONIC_ECHO) == 1:
            pulse_end = time.time()
            if pulse_end > timeout:
                break

        duration = pulse_end - pulse_start
        dist = round((duration * 34300) / 2, 1)

        if 2.0 <= dist <= 300.0:
            readings.append(dist)

    if len(readings) > 0:
        readings.sort()
        return readings[len(readings) // 2]
    return 999


def person_detected():
    distance = get_distance_cm()
    return distance <= ULTRASONIC_DISTANCE_CM


def is_key_present(slot_number):
    if not ENABLE_IR_SENSORS:
        return True
    pin = IR_SENSOR_PINS.get(slot_number)
    if pin is None:
        return True
    return GPIO.input(pin) == KEY_PRESENT_STATE


picam = None


def setup_camera():
    global picam
    if not ENABLE_CAMERA:
        return
    try:
        picam = Picamera2()
        config = picam.create_preview_configuration(main={"size": (640, 480)})
        picam.configure(config)
        picam.start()
        print("[CAMERA] Camera initialized - Continuous QR Scanning Active.")
    except Exception as e:
        print(f"[CAMERA ERROR] {e}")
        lcd_print("Camera Error", "Check cable")
        picam = None


def get_qr_frame():
    if not picam or not ENABLE_CAMERA:
        return None
    try:
        frame = picam.capture_array()
        decoded = decode(frame)
        for obj in decoded:
            qr_data = obj.data.decode("utf-8").strip()
            if qr_data:
                return qr_data
    except Exception:
        pass
    return None


def load_offline_cache():
    if not os.path.exists(OFFLINE_CACHE_FILE):
        return {"users": {}, "keys": {}, "timestamp": None}
    try:
        with open(OFFLINE_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[CACHE READ ERROR] {e}")
        return {"users": {}, "keys": {}, "timestamp": None}


def save_offline_cache(cache_data):
    try:
        with open(OFFLINE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
    except Exception as e:
        print(f"[CACHE WRITE ERROR] {e}")


def load_pending_logs():
    if not os.path.exists(PENDING_SYNC_FILE):
        return []
    try:
        with open(PENDING_SYNC_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[PENDING READ ERROR] {e}")
        return []


def append_pending_log(item):
    logs = load_pending_logs()
    logs.append(item)
    try:
        with open(PENDING_SYNC_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2)
        print(f"[OFFLINE QUEUE] Saved event to pending sync queue (Total queued: {len(logs)})")
    except Exception as e:
        print(f"[PENDING WRITE ERROR] {e}")


def clear_pending_logs():
    try:
        with open(PENDING_SYNC_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    except Exception as e:
        print(f"[PENDING CLEAR ERROR] {e}")


def refresh_offline_cache():
    """Fetch latest active users, schedules, and keys from Laravel and cache locally."""
    try:
        response = requests.get(API_OFFLINE_CACHE, timeout=REQUEST_TIMEOUT)
        data = response.json()
        if data.get("success"):
            save_offline_cache(data)
            user_count = len(data.get("users", {}))
            key_count = len(data.get("keys", {}))
            print(f"[CACHE] Offline cache updated successfully: {user_count} user(s), {key_count} key slot(s).")
            return True
    except Exception as e:
        print(f"[CACHE] Server unavailable for cache refresh: {e}")
    return False


def sync_pending_logs():
    """Upload queued offline transactions and access logs to Laravel once online."""
    pending = load_pending_logs()
    if not pending:
        return True

    print(f"[SYNC] Attempting to upload {len(pending)} queued offline event(s) to Laravel...")
    try:
        response = requests.post(API_SYNC_LOGS, json={"logs": pending}, timeout=REQUEST_TIMEOUT)
        data = response.json()
        if data.get("success"):
            synced = data.get("synced_count", len(pending))
            print(f"[SYNC SUCCESS] Successfully synced {synced} offline event(s) to Laravel!")
            clear_pending_logs()
            refresh_offline_cache()
            return True
        else:
            print(f"[SYNC WARNING] Server responded but could not complete sync: {data.get('message')}")
    except Exception as e:
        print(f"[SYNC WAITING] Server unreachable for sync: {e}")
    return False


def authenticate_qr_offline(qr_token, slot_number=None):
    """Authenticate QR token against local offline cache when network is down."""
    cache = load_offline_cache()
    users = cache.get("users", {})
    keys = cache.get("keys", {})

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not users:
        print("[OFFLINE AUTH] No cached users found in offline_cache.json")
        return {
            "success": False,
            "status": "DENIED",
            "message": "No Offline Cache",
            "offline": True,
        }

    user = users.get(qr_token)
    if not user or not user.get("is_active"):
        reason = "Invalid or inactive QR code (Offline)"
        print(f"[OFFLINE AUTH] Denied: {reason}")
        append_pending_log({
            "type": "access_log",
            "user_id": user.get("id") if user else None,
            "qr_token": qr_token,
            "action": "scan",
            "result": "denied",
            "reason": reason,
            "timestamp": now_str,
        })
        return {
            "success": False,
            "status": "DENIED",
            "message": "Invalid QR Code",
            "offline": True,
        }

    # Check if user currently has an unreturned borrowed key (ACTION: RETURN)
    borrowed_key = None
    for s_num, k in keys.items():
        if k.get("borrowed_by_user_id") == user["id"] and k.get("status") == "borrowed":
            borrowed_key = k
            break

    if borrowed_key:
        slot = int(borrowed_key.get("slot_number"))
        borrowed_key["status"] = "available"
        borrowed_key["borrowed_by_user_id"] = None
        save_offline_cache(cache)

        append_pending_log({
            "type": "transaction",
            "user_id": user["id"],
            "key_id": borrowed_key.get("id"),
            "slot_number": slot,
            "action": "return",
            "notes": "Returned via Offline QR Scan",
            "timestamp": now_str,
        })
        append_pending_log({
            "type": "access_log",
            "user_id": user["id"],
            "qr_token": qr_token,
            "action": "return",
            "result": "granted",
            "reason": f"Offline return: Key returned to Slot #{slot}",
            "timestamp": now_str,
        })

        return {
            "success": True,
            "status": "GRANTED",
            "action": "RETURN",
            "slot_number": slot,
            "key_name": borrowed_key.get("key_name", f"Slot #{slot}"),
            "user_name": user.get("name", "User"),
            "message": f"Access Granted: Return Key to Slot #{slot}",
            "offline": True,
        }

    # ACTION: BORROW KEY
    target_key = None
    if user.get("role") == "admin":
        if slot_number is not None:
            target_key = keys.get(str(slot_number)) or keys.get(int(slot_number))
        else:
            for s_num, k in keys.items():
                if k.get("status") == "available":
                    target_key = k
                    break
    else:
        # Regular user: Check active schedule
        now_dt = datetime.now()
        today = now_dt.strftime("%A").lower()
        current_time = now_dt.strftime("%H:%M:%S")

        matched_schedule = None
        for sched in user.get("schedules", []):
            if sched.get("day_of_week") == today:
                if sched.get("start_time") <= current_time <= sched.get("end_time"):
                    matched_schedule = sched
                    break

        if not matched_schedule:
            reason = f"Outside schedule ({today})"
            print(f"[OFFLINE AUTH] Denied: {reason}")
            append_pending_log({
                "type": "access_log",
                "user_id": user["id"],
                "qr_token": qr_token,
                "action": "borrow",
                "result": "denied",
                "reason": f"Access Denied: Outside schedule ({today}) (Offline)",
                "timestamp": now_str,
            })
            return {
                "success": False,
                "status": "DENIED",
                "message": "Outside Schedule",
                "offline": True,
            }

        s_slot = matched_schedule.get("slot_number")
        if s_slot:
            target_key = keys.get(str(s_slot)) or keys.get(int(s_slot))

    if not target_key:
        return {
            "success": False,
            "status": "DENIED",
            "message": "No Key Available",
            "offline": True,
        }

    if target_key.get("status") == "borrowed":
        reason = f"Slot #{target_key.get('slot_number')} already borrowed"
        print(f"[OFFLINE AUTH] Denied: {reason}")
        append_pending_log({
            "type": "access_log",
            "user_id": user["id"],
            "qr_token": qr_token,
            "action": "borrow",
            "result": "denied",
            "reason": f"{reason} (Offline)",
            "timestamp": now_str,
        })
        return {
            "success": False,
            "status": "DENIED",
            "message": "Already Borrowed",
            "offline": True,
        }

    # Grant borrow access!
    slot = int(target_key.get("slot_number"))
    target_key["status"] = "borrowed"
    target_key["borrowed_by_user_id"] = user["id"]
    save_offline_cache(cache)

    append_pending_log({
        "type": "transaction",
        "user_id": user["id"],
        "key_id": target_key.get("id"),
        "slot_number": slot,
        "action": "borrow",
        "notes": "Borrowed via Offline QR Scan",
        "timestamp": now_str,
    })
    append_pending_log({
        "type": "access_log",
        "user_id": user["id"],
        "qr_token": qr_token,
        "action": "borrow",
        "result": "granted",
        "reason": f"Offline borrow: Key Slot #{slot} unlocked",
        "timestamp": now_str,
    })

    return {
        "success": True,
        "status": "GRANTED",
        "action": "BORROW",
        "slot_number": slot,
        "key_name": target_key.get("key_name", f"Slot #{slot}"),
        "user_name": user.get("name", "User"),
        "message": f"Access Granted: Unlock Slot #{slot}",
        "offline": True,
    }


def authenticate_qr(qr_token, slot_number=None):
    payload = {"qr_token": qr_token}
    if slot_number is not None:
        payload["slot_number"] = slot_number
    try:
        response = requests.post(API_AUTHENTICATE, json=payload, timeout=REQUEST_TIMEOUT)
        result = response.json()
        # Attempt syncing any pending logs since connection is verified
        sync_pending_logs()
        return result
    except Exception as e:
        print(f"[API ERROR / OFFLINE] {e}")
        print("[AUTOBOX] Network unreachable. Activating Smart Offline Fallback...")
        return authenticate_qr_offline(qr_token, slot_number)


def get_key_statuses():
    global known_key_statuses
    try:
        response = requests.get(API_KEY_STATUSES, timeout=REQUEST_TIMEOUT)
        data = response.json()
        if data.get("success"):
            keys = data.get("keys", [])
            for k in keys:
                slot = k.get("slot_number")
                if slot:
                    known_key_statuses[slot] = k
            return keys
    except Exception as e:
        print(f"[API ERROR] {e}")
    return []


reported_missing_slots = set()
known_key_statuses = {}


def report_missing_key(slot_number):
    try:
        response = requests.post(API_REPORT_MISSING, json={"slot_number": slot_number}, timeout=REQUEST_TIMEOUT)
        data = response.json()
        return data.get("success", False)
    except Exception as e:
        print(f"[API ERROR] {e}")
        return False


def process_scan(qr_token):
    lcd_print("Verifying...", "Please wait")
    result = authenticate_qr(qr_token)

    if result is None:
        lcd_print("Server Error", "Check Network")
        deny_access()
        return

    if result.get("success") and result.get("status") == "GRANTED":
        slot = result.get("slot_number")
        action = result.get("action")
        user_name = result.get("user_name", "")
        key_name = result.get("key_name", "")

        prefix = "OFFLINE" if result.get("offline") else "GRANTED"
        lcd_print(f"{prefix}: {action}", user_name[:16])
        time.sleep(1)
        lcd_print(f"Slot #{slot}", key_name[:16])

        if slot:
            if ENABLE_SOLENOIDS:
                print(f"[AUTOBOX] Unlocking Main Door and Slot #{slot}...")
                GPIO.output(MAIN_LOCK_PIN, GPIO.HIGH)
                slot_pin = SLOT_PINS.get(slot)
                if slot_pin:
                    GPIO.output(slot_pin, GPIO.HIGH)

            print("[AUTOBOX] Opening motorized slider door...")
            slider_open()

            # Main lock stays energized (unlocked) here on purpose.
            # It only relocks below, after wait_no_hand_and_close() has
            # actually closed the slider — so the door can't relock while
            # a hand is present or before the slider finishes its cycle.

            print("[AUTOBOX] Waiting for user hand removal (5s safety timer)...")
            wait_no_hand_and_close()

            if ENABLE_SOLENOIDS:
                GPIO.output(MAIN_LOCK_PIN, GPIO.LOW)
                slot_pin = SLOT_PINS.get(slot)
                if slot_pin:
                    print(f"[AUTOBOX] Relocking Slot #{slot}...")
                    GPIO.output(slot_pin, GPIO.LOW)

            # Refresh key statuses from server first so we know the key was legitimately borrowed
            get_key_statuses()
            update_key_presence_and_leds()
        else:
            lcd_print("No Slot Found", "Contact Admin")
            deny_access()
    else:
        message = result.get("message", "Access Denied")
        print(f"[AUTOBOX] Access Denied: {message}")
        lcd_print("ACCESS DENIED", message[:16])
        deny_access()

    time.sleep(1.5)
    lcd_print("AUTOBOX Ready", "Scan QR Code")


def update_key_presence_and_leds():
    global reported_missing_slots, known_key_statuses
    if not ENABLE_IR_SENSORS:
        return

    for slot, pin in IR_SENSOR_PINS.items():
        present = is_key_present(slot)
        if present:
            if ENABLE_LEDS and slot in LED_GREEN_PINS:
                GPIO.output(LED_GREEN_PINS[slot], GPIO.HIGH)
            if ENABLE_LEDS and slot in LED_RED_PINS:
                GPIO.output(LED_RED_PINS[slot], GPIO.LOW)

            if slot in reported_missing_slots:
                reported_missing_slots.discard(slot)
        else:
            if ENABLE_LEDS and slot in LED_GREEN_PINS:
                GPIO.output(LED_GREEN_PINS[slot], GPIO.LOW)
            if ENABLE_LEDS and slot in LED_RED_PINS:
                GPIO.output(LED_RED_PINS[slot], GPIO.HIGH)

            key_info = known_key_statuses.get(slot)
            if key_info and key_info.get("status") == "available" and slot not in reported_missing_slots:
                print(f"[AUTOBOX ALERT] Key Slot #{slot} is physically MISSING! Reporting to Laravel...")
                if report_missing_key(slot):
                    reported_missing_slots.add(slot)
                    known_key_statuses[slot]["status"] = "missing"
                    print(f"[AUTOBOX ALERT] Slot #{slot} successfully flagged as MISSING in Laravel database.")


def main():
    setup_gpio()
    setup_lcd()
    setup_camera()

    # Initial offline sync & cache refresh
    sync_pending_logs()
    refresh_offline_cache()

    keys = get_key_statuses()
    if keys:
        lcd_print("Server Connected", f"{len(keys)} Slots Active")
    else:
        cache = load_offline_cache()
        cached_keys = cache.get("keys", {})
        if cached_keys:
            lcd_print("Offline Cache OK", f"{len(cached_keys)} Slots Cached")
        else:
            lcd_print("Server Offline", "Retry on scan")
    time.sleep(2)
    lcd_print("AUTOBOX Ready", "Scan QR Code")

    last_poll = time.time()
    last_ir_check = time.time()
    last_cache_refresh = time.time()
    last_sync_check = time.time()

    update_key_presence_and_leds()

    try:
        while True:
            now = time.time()
            if ENABLE_IR_SENSORS and (now - last_ir_check >= 3):
                update_key_presence_and_leds()
                last_ir_check = now

            qr_token = get_qr_frame()
            if qr_token:
                print(f"[AUTOBOX] QR Code Read: {qr_token}")
                process_scan(qr_token)
                update_key_presence_and_leds()
                time.sleep(1.5)

            if now - last_poll >= STATUS_POLL_INTERVAL:
                get_key_statuses()
                last_poll = now

            if now - last_sync_check >= SYNC_RETRY_INTERVAL:
                sync_pending_logs()
                last_sync_check = now

            if now - last_cache_refresh >= CACHE_REFRESH_INTERVAL:
                refresh_offline_cache()
                last_cache_refresh = now

            time.sleep(0.05)

    except KeyboardInterrupt:
        lcd_print("Shutting Down", "Goodbye!")

    finally:
        if picam:
            try:
                picam.stop()
                picam.close()
            except Exception:
                pass
        if lcd:
            lcd.clear()
        if ENABLE_MOTOR:
            GPIO.output(MOTOR_IN1, GPIO.LOW)
            GPIO.output(MOTOR_IN2, GPIO.LOW)
            GPIO.output(MOTOR_ENA, GPIO.LOW)
        GPIO.cleanup()


if __name__ == "__main__":
    main()
