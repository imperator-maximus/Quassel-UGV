#!/usr/bin/env python3
"""
Test-Script für PWM-Konvertierung
Zeigt die Konvertierung von DroneCAN Raw-Werten zu PWM-Werten
"""

def raw_to_percent(raw_value, motor_side):
    """Konvertiert Raw-Werte zu kalibrierten Prozent-Werten (wie im Hauptscript)"""
    # Kalibrierungswerte aus dronecan_calibrated_monitor.py
    calibration = {
        'left': {
            'neutral': -114,
            'forward_max': 8191,
            'reverse_min': -8191
        },
        'right': {
            'neutral': 0,
            'forward_max': 8191,
            'reverse_min': -8191
        }
    }

    cal = calibration[motor_side]
    neutral = cal['neutral']

    if raw_value == neutral:
        return 0.0
    elif raw_value > neutral:
        # Vorwärts: neutral bis max → 0% bis +100%
        max_range = cal['forward_max'] - neutral
        if max_range == 0:
            return 0.0
        percent = ((raw_value - neutral) / max_range) * 100.0
    else:
        # Rückwärts: min bis neutral → -100% bis 0%
        min_range = neutral - cal['reverse_min']
        if min_range == 0:
            return 0.0
        percent = ((raw_value - neutral) / min_range) * 100.0

    return round(percent, 1)

def raw_to_pwm(raw_value, motor_side):
    """Konvertiert DroneCAN Raw-Werte zu Standard PWM-Werten (1000-2000 μs)"""
    # KORRIGIERT: Verwendet jetzt kalibrierte Prozent-Werte für konsistente Umrechnung
    # Raw → Kalibrierte % → PWM μs

    # Zuerst kalibrierte Prozent-Werte berechnen
    percent = raw_to_percent(raw_value, motor_side)

    # Dann Prozent zu PWM konvertieren
    # 0% = 1500μs (Neutral), -100% = 1000μs, +100% = 2000μs
    pwm_us = int(1500 + (percent / 100.0) * 500)

    # Begrenze auf gültigen PWM-Bereich
    pwm_us = max(1000, min(2000, pwm_us))

    return pwm_us

def test_pwm_conversion():
    """Testet PWM-Konvertierung mit verschiedenen Werten"""
    print("🧪 PWM-Konvertierung Test")
    print("=" * 50)
    
    # Test-Werte basierend auf deinen Kalibrierungsdaten
    test_values = [
        # Extreme Werte
        (-8192, "Maximum Rückwärts"),
        (-8000, "Typisch Rückwärts (Orange Cube)"),
        # Neutral-Werte aus deiner Kalibrierung
        (-114, "Links Neutral (kalibriert)"),
        (0, "Rechts Neutral (kalibriert)"),
        # Vorwärts-Werte
        (4000, "Mittlere Geschwindigkeit vorwärts"),
        (8000, "Typisch Vorwärts (Orange Cube)"),
        (8191, "Maximum Vorwärts"),
    ]

    print("LINKS MOTOR:")
    print("DroneCAN Raw → Prozent → PWM μs | Beschreibung")
    print("-" * 60)

    for raw_value, description in test_values:
        percent = raw_to_percent(raw_value, 'left')
        pwm_value = raw_to_pwm(raw_value, 'left')
        print(f"{raw_value:6d} → {percent:6.1f}% → {pwm_value:4d}μs | {description}")

    print("\nRECHTS MOTOR:")
    print("DroneCAN Raw → Prozent → PWM μs | Beschreibung")
    print("-" * 60)

    for raw_value, description in test_values:
        percent = raw_to_percent(raw_value, 'right')
        pwm_value = raw_to_pwm(raw_value, 'right')
        print(f"{raw_value:6d} → {percent:6.1f}% → {pwm_value:4d}μs | {description}")

    print("\n📊 PWM-Standard-Bereiche:")
    print("   1000μs = Minimum (Vollgas rückwärts)")
    print("   1500μs = Neutral (Stop)")
    print("   2000μs = Maximum (Vollgas vorwärts)")

    print("\n🔧 Deine Orange Cube Kalibrierung (KORRIGIERT):")
    print("   Links Neutral (-114) →", f"{raw_to_percent(-114, 'left'):6.1f}% →", raw_to_pwm(-114, 'left'), "μs")
    print("   Rechts Neutral (0)   →", f"{raw_to_percent(0, 'right'):6.1f}% →", raw_to_pwm(0, 'right'), "μs")

if __name__ == "__main__":
    test_pwm_conversion()
