/*
* This is an example app using the INA libary from https://github.com/RobTillaart/INA239
* You'll need to download the library
* this code is untested, and is just for illustration on how you could use the library. Hopefully I can test it with the INA soon : )
*/


#include <Arduino.h>
#include <dronecan.h>
#include <IWatchdog.h>
#include <app.h>
#include <vector>
#include "INA239.h"

INA239 INA(5, &SPI);


std::vector<DroneCAN::parameter> custom_parameters = {
    { "NODEID", UAVCAN_PROTOCOL_PARAM_VALUE_INTEGER_VALUE, 127,  0, 127 },
    { "PARM_1", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
    { "PARM_2", UAVCAN_PROTOCOL_PARAM_VALUE_REAL_VALUE,   0.0f, 0.0f, 100.0f },
};

DroneCAN dronecan;

uint32_t looptime = 0;

static void onTransferReceived(CanardInstance *ins, CanardRxTransfer *transfer)
{
    DroneCANonTransferReceived(dronecan, ins, transfer);
}

static bool shouldAcceptTransfer(const CanardInstance *ins,
                                 uint64_t *out_data_type_signature,
                                 uint16_t data_type_id,
                                 CanardTransferType transfer_type,
                                 uint8_t source_node_id)

{
    return false || DroneCANshoudlAcceptTransfer(ins, out_data_type_signature, data_type_id, transfer_type, source_node_id);
}

void setup()
{
    // to use debugging tools, remove app_setup and set FLASH start from 0x800A000 to 0x8000000 in ldscript.ld
    // this will over-write the bootloader. To use the bootloader again, reflash it and change above back.
    app_setup(); // needed for coming from a bootloader, needs to be first in setup
    Serial.begin(115200);
    dronecan.init(onTransferReceived, shouldAcceptTransfer, custom_parameters);
    IWatchdog.begin(2000000); // if the loop takes longer than 2 seconds, reset the system

    SPI.begin();

    if (!INA.begin() )
    {
        Serial.println("Could not connect. Fix and Reboot");
        while(1);
    }

    // set your shunt resistance here
    INA.setMaxCurrentShunt(10, 0.015);

    while (true)
    {
        const uint32_t now = millis();

        // send our battery message at 10Hz
        if (now - looptime > 100)
        {
            looptime = millis();

            // construct dronecan packet
            uavcan_equipment_power_BatteryInfo pkt{};
            pkt.voltage = INA.getBusVoltage();
            pkt.current = INA.getMilliAmpere()/1000;
            pkt.temperature = INA.getTemperature();

            // boilerplate to send a message
            uint8_t buffer[UAVCAN_EQUIPMENT_POWER_BATTERYINFO_MAX_SIZE];
            uint32_t len = uavcan_equipment_power_BatteryInfo_encode(&pkt, buffer);
            static uint8_t transfer_id;
            canardBroadcast(&dronecan.canard,
                            UAVCAN_EQUIPMENT_POWER_BATTERYINFO_SIGNATURE,
                            UAVCAN_EQUIPMENT_POWER_BATTERYINFO_ID,
                            &transfer_id,
                            CANARD_TRANSFER_PRIORITY_LOW,
                            buffer,
                            len);
        }

        dronecan.cycle();
        IWatchdog.reload();
    }
}

void loop()
{
    // Doesn't work coming from bootloader ? use while loop in setup
}
