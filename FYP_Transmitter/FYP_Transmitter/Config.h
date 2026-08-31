#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>
#include <DHT.h>

/****************************************************
 *                  NODE SETTINGS
 ****************************************************/

#define NODE_ID                 1
#define GATEWAY_ID              99
#define PARENT_NODE_ID          GATEWAY_ID

/*
 * Future multi-hop example:
 *
 * Node 1:
 *   NODE_ID = 1
 *   PARENT_NODE_ID = 2
 *   NODE_SLOT_INDEX = 0
 *
 * Node 2:
 *   NODE_ID = 2
 *   PARENT_NODE_ID = 3
 *   NODE_SLOT_INDEX = 1
 *
 * Node 3:
 *   NODE_ID = 3
 *   PARENT_NODE_ID = GATEWAY_ID
 *   NODE_SLOT_INDEX = 2
 */

/****************************************************
 *               LORA CONFIGURATION
 ****************************************************/

#define LORA_SS                 5
#define LORA_RST                14
#define LORA_DIO0               2

#define LORA_SCK                18
#define LORA_MISO               19
#define LORA_MOSI               23

#define LORA_FREQUENCY          433E6

#define LORA_SYNC_WORD          0x12
#define LORA_TX_POWER           17
#define LORA_SPREADING_FACTOR   7
#define LORA_SIGNAL_BANDWIDTH   125E3
#define LORA_CODING_RATE        5

/****************************************************
 *           SWITCHED SENSOR POWER RAIL
 ****************************************************/

/*
 * PCB-confirmed control:
 *
 * GPIO25 HIGH -> NPN ON -> P-MOSFET ON -> SENSOR_9V ON
 * GPIO25 LOW  -> NPN OFF -> P-MOSFET OFF -> SENSOR_9V OFF
 */
#define SENSOR_POWER_PIN        25

/*
 * Allow the powered soil/RS485 sensor to boot before the
 * first Modbus request. Increase this if the sensor is slow.
 */
#define SENSOR_STARTUP_DELAY_MS 2000UL

/*
 * A failed Modbus request is retried while the sensor rail
 * remains powered.
 */
#define SENSOR_READ_RETRIES     3
#define SENSOR_RETRY_DELAY_MS   250UL

/****************************************************
 *             SOIL SENSOR / RS485
 ****************************************************/

#define RS485_RX                16
#define RS485_TX                17
#define RS485_BAUD              4800
#define MODBUS_SLAVE_ID         1


// 7-in-1 soil sensor factory default:
// 4800 baud, 8N1, Modbus address 1.

/****************************************************
 *                    DHT11
 ****************************************************/

#define DHTPIN                  4
#define DHTTYPE                 DHT11

/****************************************************
 *            NETWORK AND RETRY SETTINGS
 ****************************************************/

#define ACK_TIMEOUT_MS          1500UL
#define MAX_SEND_RETRIES        3
#define RETRY_DELAY_MS          300UL

#define MAX_PACKET_QUEUE        20
#define DUPLICATE_CACHE_SIZE    30

/****************************************************
 *        SAMPLING / DEEP-SLEEP SETTINGS
 ****************************************************/

/*
 * Agriculture field default: one cycle every 30 minutes.
 *
 * To sample every 20 minutes instead, change 30UL to 20UL.
 */
#define SAMPLE_INTERVAL_MS 30000UL

/*
 * If LoRa fails to initialise, do not remain awake forever.
 * Sleep for five minutes and try again after reboot/wakeup.
 */
#define LORA_FAILURE_RETRY_SLEEP_MS \
    (5UL * 60UL * 1000UL)

/*
 * If a cycle somehow takes longer than the configured sample
 * interval, use a short recovery sleep instead of immediately
 * looping at full power.
 */
#define MINIMUM_RECOVERY_SLEEP_MS 60000UL

/****************************************************
 *            MULTI-HOP SLOT SCHEDULING
 ****************************************************/

#define NODE_SLOT_INDEX         0
#define SLOT_DURATION_MS        5000UL

/*
 * One collection cycle. Deep sleep replaces the old long delay,
 * but the awake time is subtracted before sleeping so the overall
 * cycle stays close to this interval.
 */
#define NETWORK_CYCLE_MS        SAMPLE_INTERVAL_MS

#define MAX_HOP_COUNT           15

#endif
