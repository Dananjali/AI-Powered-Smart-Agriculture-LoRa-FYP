#ifndef RECEIVER_CONFIG_H
#define RECEIVER_CONFIG_H

#include <Arduino.h>

// This is the final/base-station receiver ID used by the transmitter.
#define RECEIVER_NODE_ID         99

// SX1278 wiring - matches the transmitter wiring/settings.
#define LORA_SS                  5
#define LORA_RST                 14
#define LORA_DIO0                2

#define LORA_SCK                 18
#define LORA_MISO                19
#define LORA_MOSI                23

#define LORA_FREQUENCY           433E6
#define LORA_SYNC_WORD           0x12
#define LORA_TX_POWER            17
#define LORA_SPREADING_FACTOR    7
#define LORA_SIGNAL_BANDWIDTH    125E3
#define LORA_CODING_RATE         5

// Number of recent packet IDs remembered so LoRa retries are ACKed
// but are not logged twice.
#define DUPLICATE_CACHE_SIZE     60

#endif
