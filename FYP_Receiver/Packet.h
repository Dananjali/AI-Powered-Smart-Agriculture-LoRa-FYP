#ifndef PACKET_H
#define PACKET_H

#include <Arduino.h>

constexpr uint8_t PACKET_VERSION = 1;
constexpr uint16_t PACKET_MAGIC = 0xA55A;

enum class PacketType : uint8_t
{
    SENSOR_DATA = 1,
    ACKNOWLEDGEMENT = 2
};

enum SensorStatusFlags : uint8_t
{
    SOIL_SENSOR_VALID = 0x01,
    DHT_SENSOR_VALID  = 0x02
};

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

struct NetworkPacket
{
    uint16_t magic;
    uint8_t version;
    PacketType packetType;

    uint8_t sourceNode;
    uint8_t previousHop;
    uint8_t destinationNode;
    uint8_t finalDestination;
    uint8_t hopCount;

    uint32_t sequenceNumber;

    SensorData data;

    uint16_t checksum;
};

struct AckPacket
{
    uint16_t magic;
    uint8_t version;
    PacketType packetType;

    uint8_t senderNode;
    uint8_t destinationNode;

    uint8_t acknowledgedSource;
    uint32_t acknowledgedSequence;

    uint16_t checksum;
};

static_assert(sizeof(NetworkPacket) <= 255,
              "NetworkPacket is too large for one LoRa transmission.");

static_assert(sizeof(AckPacket) <= 255,
              "AckPacket is too large for one LoRa transmission.");

#endif
