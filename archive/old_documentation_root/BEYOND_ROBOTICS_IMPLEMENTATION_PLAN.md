# Beyond Robotics Implementation Plan
## Based on Official Support Response

### PROBLEM ANALYSIS
The Beyond Robotics support team identified that our custom PlatformIO configuration may not have Serial2 configured correctly for the STM32L431 Micro Node. They provided a comprehensive solution using their official Arduino-DroneCAN repository.

### SOLUTION OVERVIEW
1. **Root Cause**: Custom configuration lacks proper Serial2 setup
2. **Official Solution**: Use pre-configured Arduino-DroneCAN v1.2 project
3. **Process**: Flash AP bootloader → Use official project → Customize for application
4. **Benefits**: Working serial communication + DroneCAN functionality

---

## IMPLEMENTATION STEPS

### Phase 1: Download Required Files
**Files to Download from GitHub Release v1.2:**
- `ArduinoDroneCAN.V1.2.zip` - Official project with proper configuration
- `AP_Bootloader.bin` - Bootloader for firmware updates over CAN
- STM32CubeProgrammer - For flashing bootloader

**Download URLs:**
- Release page: https://github.com/BeyondRobotix/Arduino-DroneCAN/releases/tag/v1.2
- STM32CubeProgrammer: https://www.st.com/en/development-tools/stm32cubeprog.html

### Phase 2: Flash AP Bootloader
```bash
# Using STM32CubeProgrammer
# Flash AP_Bootloader.bin to start address 0x8000000
# Node will boot in maintenance mode on CAN bus
```

**Hardware Setup:**
- SW1 in position "1" (STLINK enabled)
- ST-LINK V3 connected to STLINK header
- Use provided cable between ST-LINK and dev board

### Phase 3: Setup Official Project
1. Extract `ArduinoDroneCAN.V1.2.zip`
2. Open project in VSCode with PlatformIO
3. Press upload to flash firmware
4. Verify serial output on COM8
5. Confirm CAN message transmission

### Phase 4: Verify Functionality
**Expected Results:**
- Serial traffic on COM8 at 115200 baud
- Battery messages visible in CAN monitor
- Node appears on CAN bus properly

### Phase 5: Customize for Application
- Modify `src/main.cpp` for DroneCAN communication with Orange Cube
- Integrate with existing Orange Cube configuration
- Test end-to-end communication

---

## SUPPORT RESPONSE KEY POINTS

### Hardware Verification
✅ **Confirmed Correct:**
- SW1 in position "1" for STLINK
- Hardware connections verified

❓ **Question from Support:**
- Are you using the provided cable between ST-LINK and dev board?

### Software Issues Identified
❌ **Problem:** Custom PlatformIO configuration
- Serial2 not configured correctly
- Missing proper board setup

✅ **Solution:** Official repository
- Everything pre-configured for Arduino and DroneCAN
- Proper PlatformIO setup included
- Working library for DroneCAN integration

### Additional Features
- **AP Bootloader**: Enables firmware updates over CAN
- **Maintenance Mode**: Node shows on CAN bus during boot
- **Debugging Support**: Breakpoint debugging available if needed

---

## NEXT STEPS

1. **Download Files**: Get official v1.2 release and STM32CubeProgrammer
2. **Flash Bootloader**: Use STM32CubeProgrammer to flash AP_Bootloader.bin
3. **Test Official Project**: Upload and verify serial communication works
4. **Integrate with Orange Cube**: Customize for your DroneCAN application

### Questions for Support Follow-up
- Cable verification: Confirm using provided ST-LINK cable
- Debugging preference: Standard bootloader vs. breakpoint debugging
- Customization guidance: Best practices for modifying main.cpp

---

## EXPECTED OUTCOMES

After implementation:
- ✅ Serial communication working on COM8
- ✅ DroneCAN messages transmitting to Orange Cube
- ✅ Proper node identification on CAN bus
- ✅ Foundation for custom DroneCAN application development

This official solution should resolve both the serial communication issue and provide a robust foundation for DroneCAN implementation with the Orange Cube.
