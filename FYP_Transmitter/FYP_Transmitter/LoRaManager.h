#ifndef LORA_MANAGER_H
#define LORA_MANAGER_H

#include <Arduino.h>
#include "Packet.h"

bool initialiseLoRa();

/*
 * Put the SX1278 in sleep mode and stop the ESP32 SPI bus
 * before ESP32 deep sleep.
 */
void sleepLoRa();

bool sendNetworkPacket(NetworkPacket &packet);
bool sendNetworkPacketWithRetry(NetworkPacket &packet);
bool receiveNetworkPacket(NetworkPacket &packet);
bool sendAcknowledgement(const NetworkPacket &receivedPacket);

bool waitForAcknowledgement(
    uint8_t originalSource,
    uint32_t sequenceNumber,
    uint32_t timeoutMs
);

NetworkPacket createSensorPacket(
    const SensorData &data,
    uint32_t sequenceNumber
);

void preparePacketForForwarding(
    NetworkPacket &packet,
    uint8_t nextHop
);

void printNetworkPacket(const NetworkPacket &packet);

uint16_t calculateNetworkPacketChecksum(
    const NetworkPacket &packet
);

uint16_t calculateAckPacketChecksum(
    const AckPacket &packet
);

#endif
