#!/usr/bin/env python3
"""
Monitor PWM Values BEFORE CAN Transmission
Shows the exact PWM values that Orange Cube calculates and sends over CAN
These are the same values your Beyond Robotics Board should receive!

UPDATED: Now supports both COM and WiFi connections via connection_config.py
"""

import time
from pymavlink import mavutil
from connection_config import get_connection

def monitor_pwm_values():
    print("=" * 70)
    print("    🎯 PWM Values Monitor (BEFORE CAN)")
    print("=" * 70)
    print("Zeigt die PWM-Werte die der Orange Cube berechnet und über CAN sendet")
    print("Das sind EXAKT die Werte die dein Beyond Robotics Board bekommen sollte!")
    print("=" * 70)

    # Connect to Orange Cube (COM or WiFi)
    try:
        connection = get_connection()
    except Exception as e:
        print(f"❌ Verbindung fehlgeschlagen: {e}")
        return

    print("\n🎮 PWM Monitor gestartet - Bewege die RC-Sticks!")
    print("Drücke Ctrl+C zum Beenden\n")

    try:
        while True:
            # Request servo output values
            connection.mav.request_data_stream_send(
                connection.target_system,
                connection.target_component,
                mavutil.mavlink.MAV_DATA_STREAM_RC_CHANNELS,
                1,  # 1 Hz
                1   # Enable
            )

            # Wait for servo output message
            msg = connection.recv_match(type='SERVO_OUTPUT_RAW', blocking=True, timeout=2)
            if msg:
                # Get current time
                current_time = time.strftime("%H:%M:%S")

                print(f"⏰ {current_time}")
                print(f"📊 PWM Werte (vor CAN-Übertragung):")
                print(f"   Servo1 (ESC1):   {msg.servo1_raw} μs")
                print(f"   Servo2 (ESC2):   {msg.servo2_raw} μs")
                print(f"   Servo3 (ESC3):   {msg.servo3_raw} μs")
                print(f"   Servo4:          {msg.servo4_raw} μs")

                # Convert to DroneCAN ESC values (1000-2000 μs → 0-8191)
                def pwm_to_esc(pwm_us):
                    if pwm_us == 0:
                        return 0
                    # Standard conversion: 1000μs=0, 1500μs=4095, 2000μs=8191
                    esc_value = int((pwm_us - 1000) * 8.191)
                    return max(0, min(8191, esc_value))

                esc1 = pwm_to_esc(msg.servo1_raw)
                esc2 = pwm_to_esc(msg.servo2_raw)

                print(f"🎯 DroneCAN ESC Werte (was Beyond Robotics bekommt):")
                print(f"   ESC1 (Links):  {esc1}")
                print(f"   ESC2 (Rechts): {esc2}")

                # Show movement interpretation based on your RC values
                if esc1 > 4200 and esc2 > 4200:
                    movement = "🔼 VORNE (beide hoch)"
                elif esc1 < 3900 and esc2 < 3900:
                    movement = "🔽 ZURÜCK (beide niedrig)"
                elif esc1 < 3900 and esc2 > 4200:
                    movement = "◀️ LINKS (ESC1 niedrig, ESC2 hoch)"
                elif esc1 > 4200 and esc2 < 3900:
                    movement = "▶️ RECHTS (ESC1 hoch, ESC2 niedrig)"
                else:
                    movement = "⏸️ NEUTRAL"

                print(f"🚗 Bewegung: {movement}")
                print("-" * 50)

            time.sleep(0.5)  # Update every 500ms

    except KeyboardInterrupt:
        print("\n⚠️ PWM Monitor beendet")
    except Exception as e:
        print(f"\n❌ Fehler: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    monitor_pwm_values()
