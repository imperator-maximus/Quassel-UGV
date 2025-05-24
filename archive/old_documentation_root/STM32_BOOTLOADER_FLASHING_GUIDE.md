# STM32 Bootloader Flashing Guide
## Beyond Robotics AP Bootloader Installation

### OVERVIEW
This guide walks through flashing the AP_Bootloader.bin to your Beyond Robotics Dev Board with STM32L431 Micro Node, as recommended by Beyond Robotics support.

---

## PREREQUISITES

### Hardware Setup
- ✅ Beyond Robotics Node Development Board with STM32L431 Micro Node
- ✅ ST-LINK V3 MINI (blue dongle) 
- ✅ **Use provided cable** between ST-LINK and dev board (per support response)
- ✅ SW1 switch in position "1" (STLINK enabled)

### Software Requirements
1. **STM32CubeProgrammer** - Download from ST website
2. **AP_Bootloader.bin** - From Beyond Robotics v1.2 release

---

## STEP 1: DOWNLOAD STM32CUBEPROGRAMMER

### Download Link
```
https://www.st.com/en/development-tools/stm32cubeprog.html
```

### Installation Notes
- Free registration with ST required
- Download latest version (2.16.0 or newer)
- Install with default settings
- Ensure ST-LINK drivers are included

---

## STEP 2: PREPARE BOOTLOADER FILE

### File Location
After running the download script, the bootloader will be at:
```
beyond_robotics_official/AP_Bootloader.bin
```

### File Verification
- **File name**: AP_Bootloader.bin
- **Target address**: 0x8000000
- **Purpose**: Enables firmware updates over CAN

---

## STEP 3: CONNECT HARDWARE

### Connection Checklist
1. ✅ ST-LINK V3 connected to PC via USB
2. ✅ **Use provided cable** between ST-LINK and STLINK header on dev board
3. ✅ SW1 switch in position "1" (STLINK enabled, USB disabled)
4. ✅ Dev board powered (LED should be visible)

### Verify Connection
- ST-LINK should appear in Windows Device Manager
- Should show as "ST-Link Debug" and "USB Serial Device (COM8)"

---

## STEP 4: FLASH BOOTLOADER

### Launch STM32CubeProgrammer
1. Open STM32CubeProgrammer application
2. Select "ST-LINK" connection type
3. Click "Connect" to establish connection with STM32L431

### Flash Process
1. **Select File**: Browse to `AP_Bootloader.bin`
2. **Start Address**: Enter `0x8000000`
3. **Verify Settings**:
   - File path: `beyond_robotics_official/AP_Bootloader.bin`
   - Start address: `0x8000000`
   - Connection: ST-LINK
4. **Flash**: Click "Start Programming"

### Expected Output
```
Connecting to target...
Connection established
Erasing memory...
Programming...
Verifying...
Programming completed successfully
```

---

## STEP 5: VERIFY BOOTLOADER

### Boot Verification
1. **Reset the board** (press reset button or power cycle)
2. **Check LED behavior** - should indicate bootloader is running
3. **CAN Bus Check** - node should appear in maintenance mode

### Maintenance Mode
- Node will show on CAN bus as in maintenance mode
- This indicates bootloader is working correctly
- Ready for firmware upload via PlatformIO

---

## STEP 6: NEXT STEPS

### After Successful Bootloader Flash
1. ✅ Bootloader installed and verified
2. ✅ Node boots in maintenance mode
3. ✅ Ready for Arduino-DroneCAN firmware upload

### Proceed to Firmware Upload
1. Open extracted Arduino-DroneCAN project in VSCode/PlatformIO
2. Press "Upload" in PlatformIO
3. Firmware will be uploaded over ST-LINK
4. Serial communication should work on COM8

---

## TROUBLESHOOTING

### Connection Issues
**Problem**: Cannot connect to STM32L431
**Solutions**:
- Verify ST-LINK drivers installed
- Check cable connections (use provided cable)
- Ensure SW1 in position "1"
- Try different USB port

### Programming Errors
**Problem**: Programming failed
**Solutions**:
- Verify start address is exactly `0x8000000`
- Check file path to AP_Bootloader.bin
- Ensure target is not write-protected
- Try erasing chip first

### Verification Issues
**Problem**: Node doesn't boot in maintenance mode
**Solutions**:
- Verify bootloader was programmed correctly
- Check CAN bus connections
- Reset board after programming
- Verify LED behavior indicates boot

---

## SUPPORT CONTACT

If you encounter issues during bootloader flashing:
- **Beyond Robotics Support**: admin@beyondrobotix.com
- **Documentation**: https://beyond-robotix.gitbook.io/docs/
- **GitHub Discussions**: https://github.com/BeyondRobotix/Arduino-DroneCAN/discussions

---

## SUCCESS CRITERIA

✅ **Bootloader Successfully Installed When**:
- STM32CubeProgrammer reports successful programming
- Board resets and boots properly
- Node appears in maintenance mode on CAN bus
- Ready for firmware upload via PlatformIO

After successful bootloader installation, proceed to upload the official Arduino-DroneCAN firmware!
