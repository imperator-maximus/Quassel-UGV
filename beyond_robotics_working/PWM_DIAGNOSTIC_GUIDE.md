# PWM Diagnostic Guide - Beyond Robotics Motor Controller

## Problem Description

**Issue**: Motor PWM output not working despite successful DroneCAN communication
- DroneCAN communication OK (RC values visible via STLink)
- Motors don't move
- Multimeter shows constant 0.62V on PA8/PA9 (should change with RC inputs)
- Expected PWM voltages not observed

## Expected vs Actual Behavior

### Expected PWM Voltages (3.3V logic, ~20kHz)
- **1000μs**: ~0.17V (5% duty cycle)
- **1500μs**: ~0.25V (7.5% duty cycle)  
- **2000μs**: ~0.33V (10% duty cycle)

### Actual Behavior
- **Constant 0.62V** on PA8/PA9 (indicates PWM failure)

## Diagnostic Test Setup

### 1. Hardware Requirements
- Beyond Robotics Dev Board (STM32L431)
- Multimeter (DC voltage measurement)
- STLink programmer
- USB cable for serial monitoring

### 2. Pin Configuration
```cpp
// Primary pins (TIM1)
#define TEST_PIN_1_PRIMARY   PA8   // TIM1_CH1
#define TEST_PIN_2_PRIMARY   PA9   // TIM1_CH2

// Alternative pins (TIM16/TIM17)
#define TEST_PIN_1_ALT       PA6   // TIM16_CH1
#define TEST_PIN_2_ALT       PA7   // TIM17_CH1
```

### 3. Running the Diagnostic Test

#### Step 1: Backup Current Configuration
```bash
# Backup current files
cp platformio.ini platformio_original.ini
cp src/main.cpp src/main_original.cpp
```

#### Step 2: Setup Diagnostic Test
```bash
# Copy diagnostic configuration
cp platformio_diagnostic.ini platformio.ini
cp pwm_diagnostic_test.cpp src/main.cpp
```

#### Step 3: Build and Upload
```bash
# Build and upload diagnostic test
pio run -t upload

# Monitor serial output
pio device monitor -b 115200
```

## Test Phases

### Phase 1: Primary Pins (PA8/PA9)
1. **Servo.attach() Test**
   - Tests if `servo.attach(PA8)` and `servo.attach(PA9)` succeed
   - Should return `true` for working pins

2. **PWM Output Test**
   - Sets PWM to 1000μs, 1500μs, 2000μs
   - Measure voltage with multimeter during each step
   - Voltages should change according to expected values

### Phase 2: Alternative Pins (PA6/PA7)
1. **Fallback Test**
   - Tests PA6 (TIM16_CH1) and PA7 (TIM17_CH1)
   - Alternative if PA8/PA9 have timer conflicts

2. **Validation**
   - Same PWM tests as Phase 1
   - Confirms if alternative pins work

## Expected Serial Output

```
=== PWM DIAGNOSTIC TEST ===
Beyond Robotics STM32L431 Motor Controller
Testing Servo.attach() and PWM output

🔍 SYSTEM INFORMATION:
Board: STM32L431 Beyond Robotics Dev Board
Framework: Arduino
PWM Library: Servo.h

📍 PIN MAPPING:
📍 Motor 1 Primary (Pin 8): PA8 - TIM1_CH1
📍 Motor 2 Primary (Pin 9): PA9 - TIM1_CH2
📍 Motor 1 Alternative (Pin 6): PA6 - TIM16_CH1
📍 Motor 2 Alternative (Pin 7): PA7 - TIM17_CH1

🚀 STARTING PWM DIAGNOSTIC TEST...

=== PHASE 1: TESTING PRIMARY PINS (PA8/PA9) ===

🔧 Testing Servo.attach() for Servo1 on pin 8... ✅ SUCCESS
📏 Measure voltage on pin 8 with multimeter
   Expected voltages (3.3V logic):
   1000μs: ~0.17V (5% duty cycle)
   1500μs: ~0.25V (7.5% duty cycle)
   2000μs: ~0.33V (10% duty cycle)

🔧 Testing Servo.attach() for Servo2 on pin 9... ✅ SUCCESS
📏 Measure voltage on pin 9 with multimeter
   Expected voltages (3.3V logic):
   1000μs: ~0.17V (5% duty cycle)
   1500μs: ~0.25V (7.5% duty cycle)
   2000μs: ~0.33V (10% duty cycle)

🔧 Testing PWM_MIN (1000μs)...
📡 Setting Servo1 to 1000μs
📡 Setting Servo2 to 1000μs
📏 Measure voltages now!

🔧 Testing PWM_NEUTRAL (1500μs)...
📡 Setting Servo1 to 1500μs
📡 Setting Servo2 to 1500μs
📏 Measure voltages now!

🔧 Testing PWM_MAX (2000μs)...
📡 Setting Servo1 to 2000μs
📡 Setting Servo2 to 2000μs
📏 Measure voltages now!
```

## Troubleshooting Results

### Case 1: Servo.attach() Returns False
**Cause**: Pin not available for PWM or timer conflict
**Solution**: 
- Check timer assignments in `variants/BRMicroNode/PeripheralPins.c`
- Try alternative pins (PA6/PA7)
- Verify pin definitions in variant files

### Case 2: Servo.attach() Succeeds but Constant Voltage
**Cause**: Timer configuration issue or hardware problem
**Solution**:
- Check timer initialization in STM32 core
- Verify 3.3V power supply
- Test with oscilloscope for actual PWM signal

### Case 3: Changing Voltages (Success!)
**Result**: PWM working correctly
**Next Steps**: 
- Update motor controller to use working pins
- Test with actual ESCs/motors

## Pin Mapping Investigation

### Check Timer Assignments
```cpp
// From variants/BRMicroNode/PeripheralPins.c
{PA_8, TIM1, STM_PIN_DATA_EXT(STM_MODE_AF_PP, GPIO_PULLUP, GPIO_AF1_TIM1, 1, 0)}, // TIM1_CH1
{PA_9, TIM1, STM_PIN_DATA_EXT(STM_MODE_AF_PP, GPIO_PULLUP, GPIO_AF1_TIM1, 2, 0)}, // TIM1_CH2
```

### Potential Timer Conflicts
- TIM1 might be used by other peripherals
- Check `TIMER_SERVO` definition in variant files
- Verify no conflicts with system timers

## Next Steps After Diagnosis

### If PA8/PA9 Work
1. Update `config/config.h` to confirm pin assignments
2. Test with actual motor controller code
3. Verify ESC connections and power

### If PA8/PA9 Fail
1. Update pin definitions to use PA6/PA7
2. Modify `MOTOR_PINS` array in config
3. Test alternative timer configurations

### If All Pins Fail
1. Check STM32 Arduino core version
2. Verify board variant files
3. Consider using direct HAL timer configuration

## Hardware Verification Checklist

- [ ] 3.3V power supply stable
- [ ] Ground connections secure  
- [ ] No short circuits on PWM pins
- [ ] Multimeter calibrated for DC voltage
- [ ] STLink connection stable
- [ ] Serial monitor working at 115200 baud

## Code Modifications for Working Solution

Once working pins are identified, update the main motor controller:

```cpp
// In config/config.h - update to working pins
#define MOTOR_PIN_1 PA6  // If PA8 failed, use PA6
#define MOTOR_PIN_2 PA7  // If PA9 failed, use PA7

// Motor pin array
static const uint8_t MOTOR_PINS[NUM_MOTORS] = {
    MOTOR_PIN_1, MOTOR_PIN_2  // Updated to working pins
};
```

This diagnostic test will definitively identify whether the issue is with:
1. **Servo.attach() failure** (pin/timer conflicts)
2. **PWM generation failure** (timer configuration)
3. **Hardware issues** (power, connections)
4. **Pin mapping problems** (variant file issues)
