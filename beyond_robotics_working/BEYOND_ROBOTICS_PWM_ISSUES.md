# Beyond Robotics STM32L431 PWM Issues & Solutions

## ⚠️ CRITICAL ISSUE: PA8/PA9 PWM Problems

**Problem**: `Servo.attach(PA8)` and `Servo.attach(PA9)` fail on Beyond Robotics STM32L431 board despite being valid PWM pins.

**Root Causes**:
1. **PA9 predefined as I2C_SCL** in `variant_BRMICRONODE.h`
2. **PA8 has hardware conflicts** (likely I2C or other peripherals)
3. **TIM1 is Advanced Timer** requiring Main Output Enable (MOE)
4. **Arduino STM32 Core** cannot resolve pin conflicts automatically

## ✅ WORKING SOLUTION: Direct HAL Programming

### Implementation:
```cpp
// Global TIM1 handle
TIM_HandleTypeDef htim1_global;

bool MotorController::initialize() {
    // Enable clocks
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_TIM1_CLK_ENABLE();
    
    // Configure PA8 as TIM1_CH1
    GPIO_InitTypeDef GPIO_InitStruct = {0};
    GPIO_InitStruct.Pin = GPIO_PIN_8;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF1_TIM1;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
    
    // Configure PA9 as TIM1_CH2
    GPIO_InitStruct.Pin = GPIO_PIN_9;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
    
    // Configure TIM1 for 50Hz PWM
    htim1_global.Instance = TIM1;
    htim1_global.Init.Prescaler = 79;  // 80MHz / 80 = 1MHz
    htim1_global.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim1_global.Init.Period = 19999;  // 50Hz (20ms)
    htim1_global.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim1_global.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    HAL_TIM_PWM_Init(&htim1_global);
    
    // Configure PWM channels
    TIM_OC_InitTypeDef sConfigOC = {0};
    sConfigOC.OCMode = TIM_OCMODE_PWM1;
    sConfigOC.Pulse = 1500;  // 1.5ms neutral
    sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
    sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
    HAL_TIM_PWM_ConfigChannel(&htim1_global, &sConfigOC, TIM_CHANNEL_1);
    HAL_TIM_PWM_ConfigChannel(&htim1_global, &sConfigOC, TIM_CHANNEL_2);
    
    // CRITICAL: Enable Main Output for Advanced Timer
    __HAL_TIM_MOE_ENABLE(&htim1_global);
    
    // Start PWM
    HAL_TIM_PWM_Start(&htim1_global, TIM_CHANNEL_1);  // PA8
    HAL_TIM_PWM_Start(&htim1_global, TIM_CHANNEL_2);  // PA9
    
    return true;
}

// Update PWM values
void updateMotorOutputs() {
    for (int i = 0; i < NUM_MOTORS; i++) {
        uint16_t pwm_value = motor_pwm_values_[i];
        
        if (i == 0) {
            // PA8 = TIM1_CH1
            __HAL_TIM_SET_COMPARE(&htim1_global, TIM_CHANNEL_1, pwm_value);
        } else if (i == 1) {
            // PA9 = TIM1_CH2
            __HAL_TIM_SET_COMPARE(&htim1_global, TIM_CHANNEL_2, pwm_value);
        }
    }
}
```

## 🎯 Key Points:

1. **Bypass Servo.attach()** completely
2. **Use direct HAL TIM1 programming**
3. **__HAL_TIM_MOE_ENABLE()** is essential for TIM1
4. **Configure pins as GPIO_AF1_TIM1** alternate function
5. **Use __HAL_TIM_SET_COMPARE()** to update PWM values

## 📊 Expected Results:

- **PA8**: ~0.25V for 1500μs PWM (TIM1_CH1)
- **PA9**: ~0.25V for 1500μs PWM (TIM1_CH2)
- **Both pins respond** to DroneCAN ESC commands
- **Motors work** with remote control

## 💡 Alternative Pins:

If PA8/PA9 issues persist, consider:
- **PA6** (TIM16_CH1) - Usually works with Servo.attach()
- **PA7** (TIM17_CH1) - Usually works with Servo.attach()

## 🔧 For Beyond Robotics:

**Suggestions for future library/board improvements:**
1. **Resolve I2C pin conflicts** in variant files
2. **Provide simplified PWM library** for PA8/PA9
3. **Document TIM1 Advanced Timer requirements**
4. **Include working example code** for motor control

---
**Status**: ✅ SOLVED - Direct HAL implementation working perfectly
**Date**: December 2024
**Tested**: Beyond Robotics STM32L431 with DroneCAN integration
