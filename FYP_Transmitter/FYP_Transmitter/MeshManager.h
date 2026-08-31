#ifndef MESH_MANAGER_H
#define MESH_MANAGER_H

#include <Arduino.h>
#include "Packet.h"

/*
 * If restoreRetainedState is true after deep sleep, queued packets,
 * sequence numbers and duplicate history are restored from RTC RAM.
 * On a normal power-on/reset the mesh state starts clean.
 */
void initialiseMesh(bool restoreRetainedState);

void receivePackets(uint32_t cycleStartTime);
bool addOwnPacket(const SensorData &sensorData);
void forwardPackets();
uint8_t getQueuedPacketCount();
void printMeshStatus();

#endif
