#ifndef POWER_MANAGER_H
#define POWER_MANAGER_H

#include <Arduino.h>

/*
 * Releases any deep-sleep GPIO hold and establishes a safe
 * SENSOR_9V OFF state.
 */
void initialisePowerManagement();

/*
 * Controls the PCB sensor-power switch on GPIO25.
 */
void setSensorPower(bool enabled);

/*
 * Returns true when this boot followed an ESP32 deep-sleep wake.
 */
bool wokeFromDeepSleep();

/*
 * Prints the ESP32 wake cause for troubleshooting.
 */
void printWakeReason();

/*
 * Places the ESP32 into timer deep sleep.
 *
 * This function does not return. Call sleepLoRa() before this
 * so the external SX1278 is also placed in sleep mode.
 */
void enterDeepSleep(uint64_t sleepDurationMs);

#endif
