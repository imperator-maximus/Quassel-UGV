/**
 * @file project_common.h
 * @brief Common includes and definitions for Beyond Robotics DroneCAN Motor Controller
 * @author Beyond Robotics DroneCAN Implementation
 * @version 1.0
 * @date 2024
 */

#ifndef PROJECT_COMMON_H
#define PROJECT_COMMON_H

// Standard Arduino includes
#include <Arduino.h>
#include <vector>
#include <Servo.h>
#include <IWatchdog.h>

// DroneCAN includes
#include <dronecan.h>
#include <app.h>

// Project version
#define PROJECT_VERSION_MAJOR 1
#define PROJECT_VERSION_MINOR 0
#define PROJECT_NAME "Beyond Robotics DroneCAN Motor Controller"

// Debug macros
#define DEBUG_PRINT(x) Serial.print(x)
#define DEBUG_PRINTLN(x) Serial.println(x)
#define DEBUG_PRINTF(fmt, ...) Serial.printf(fmt, ##__VA_ARGS__)

// Status icons for better readability
#define ICON_ROCKET "🚀"
#define ICON_LOCK "🔓"
#define ICON_WARNING "⚠️"
#define ICON_SEND "📤"
#define ICON_BATTERY "🔋"
#define ICON_MOTOR "⚙️"

#endif // PROJECT_COMMON_H
