#ifndef SENSOR_MANAGER_H
#define SENSOR_MANAGER_H

#include "Packet.h"

void initialiseSensors();

/*
 * Powers the switched sensor rail, waits for the sensor to start,
 * reads Modbus + DHT11 data, then powers the switched rail OFF.
 */
SensorData readSensors();

#endif
