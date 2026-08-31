#ifndef PACKET_H
#define PACKET_H

#include <Arduino.h>

/*
 * Increment this if the packet structure changes later.
 * Nodes using incompatible packet versions can reject each other.
 */
constexpr uint8_t PACKET_VERSION = 1;
constexpr uint16_t PACKET_MAGIC = 0xA55A;

/*
 * Packet types used by the field-node network.
 */
enum class PacketType : uint8_t
{
    SENSOR_DATA = 1,
    ACKNOWLEDGEMENT = 2
};

/*
 * Status flags allow the receiver to know whether a sensor
 * reading was valid.
 */
enum SensorStatusFlags : uint8_t
{
    SOIL_SENSOR_VALID = 0x01,
    DHT_SENSOR_VALID  = 0x02
};

/*
 * Data measured at one field node.
 */
struct SensorData
{
    uint8_t nodeID;
    uint8_t statusFlags;

    float soilMoisture;
    float soilTemperature;
    uint16_t ec;
    float ph;

    uint16_t nitrogen;
    uint16_t phosphorus;
    uint16_t potassium;

    float airTemperature;
    float humidity;

    uint32_t timestamp;
};

/*
 * One packet carries one node's reading.
 *
 * A relay does not replace sourceNode. It changes previousHop,
 * destinationNode and hopCount before forwarding.
 */
struct NetworkPacket
{
    uint16_t magic;
    uint8_t version;
    PacketType packetType;

    // Original node that measured the data.
    uint8_t sourceNode;

    // Node that most recently transmitted this packet.
    uint8_t previousHop;

    // Immediate node expected to receive this transmission.
    uint8_t destinationNode;

    // Final destination, normally the gateway.
    uint8_t finalDestination;

    // Increased whenever the packet is forwarded.
    uint8_t hopCount;

    // Unique per source node.
    uint32_t sequenceNumber;

    SensorData data;

    // Software checksum calculated before transmission.
    uint16_t checksum;
};

/*
 * ACK packet sent to confirm receipt of a NetworkPacket.
 */
struct AckPacket
{
    uint16_t magic;
    uint8_t version;
    PacketType packetType;

    uint8_t senderNode;
    uint8_t destinationNode;

    // Source and sequence number of the packet being acknowledged.
    uint8_t acknowledgedSource;
    uint32_t acknowledgedSequence;

    uint16_t checksum;
};

/*
 * Compile-time safety checks.
 */
static_assert(sizeof(NetworkPacket) <= 255,
              "NetworkPacket is too large for one LoRa transmission.");

static_assert(sizeof(AckPacket) <= 255,
              "AckPacket is too large for one LoRa transmission.");

#endif