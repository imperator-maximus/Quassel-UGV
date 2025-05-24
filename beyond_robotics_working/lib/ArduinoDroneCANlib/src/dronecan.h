#ifndef ARDU_DRONECAN
#define ARDU_DRONECAN

#include <dronecan_msgs.h>
#include <Arduino.h>
#include <can.h>
#include <EEPROM.h>
#include <vector>
#include <IWatchdog.h>

#define MIN(a, b) ((a) < (b) ? (a) : (b))
#define C_TO_KELVIN(temp) (temp + 273.15f)
#define ARRAY_SIZE(x) (sizeof(x) / sizeof(x[0]))

#define PREFERRED_NODE_ID 69

class DroneCAN
{
protected:
    uint8_t memory_pool[1024];
    struct uavcan_protocol_NodeStatus node_status;
    CanardCANFrame CAN_TX_msg;
    CanardCANFrame CAN_rx_msg;
    CanardCANFrame rx_frame;
    uint32_t looptime;
    bool led_state = false;

    struct firmware_update
    {
        char path[256];
        uint8_t node_id;
        uint8_t transfer_id;
        uint32_t last_read_ms;
        int fd;
        uint32_t offset;
    } fwupdate;

    // Returns the Node ID from parameter, if not set, returns the preferred node ID
    uint8_t get_preferred_node_id();

    static constexpr uint16_t PARAM_EEPROM_BASE = 0x0000;  // EEPROM base address
    std::vector<size_t> sorted_indices;             // built on first use

public:
    struct parameter
    {
        const char *name;
        enum uavcan_protocol_param_Value_type_t type;
        float value;
        float min_value;
        float max_value;
    };

    std::vector<parameter> parameters; 

    void set_parameters(const std::vector<parameter>& param_list) {
        parameters = param_list;  // Vector automatically handles resizing
    }

    void init(CanardOnTransferReception onTransferReceived, CanardShouldAcceptTransfer shouldAcceptTransfer, const std::vector<parameter>& param_list, const char* name);
    int node_id = 0;

    CanardInstance canard;
    uint64_t uptime = 0;
    static uint64_t micros64();
    static void getUniqueID(uint8_t id[16]);
    void handle_GetNodeInfo(CanardRxTransfer *transfer);
    void handle_param_GetSet(CanardRxTransfer *transfer);
    void handle_param_ExecuteOpcode(CanardRxTransfer *transfer);
    void read_parameter_memory();
    int handle_DNA_Allocation(CanardRxTransfer *transfer);
    void request_DNA();
    void handle_begin_firmware_update(CanardRxTransfer *transfer);
    void send_firmware_read();
    void handle_file_read_response(CanardRxTransfer *transfer);
    void send_NodeStatus(void);
    void process1HzTasks(uint64_t timestamp_usec);
    void processTx();
    void processRx();
    void cycle();
    void debug(const char *msg, uint8_t level);
    float getParameter(const char* name);
    int setParameter(const char *name, float value);
    char node_name[80];
    int version_major=0;
    int version_minor=0;
    int hardware_version_major=0;
    int hardware_version_minor=0;

    struct dynamic_node_allocation
    {
        uint32_t send_next_node_id_allocation_request_at_ms;
        uint32_t node_id_allocation_unique_id_offset;
    } DNA;
};

void DroneCANonTransferReceived(DroneCAN &dronecan, CanardInstance *ins, CanardRxTransfer *transfer);
bool DroneCANshoudlAcceptTransfer(const CanardInstance *ins,
                                  uint64_t *out_data_type_signature,
                                  uint16_t data_type_id,
                                  CanardTransferType transfer_type,
                                  uint8_t source_node_id);

#define APP_BOOTLOADER_COMMS_MAGIC 0xc544ad9a

struct app_bootloader_comms
{
    uint32_t magic;
    uint32_t ip;
    uint32_t netmask;
    uint32_t gateway;
    uint32_t reserved;
    uint8_t server_node_id;
    uint8_t my_node_id;
    uint8_t path[201];
};
#endif // ARDU_DRONECAN