FYP TRANSMITTER - POWER OPTIMISED VERSION

WHAT CHANGED
1. GPIO25 now controls the PCB sensor power stage:
   HIGH = SENSOR_9V ON
   LOW  = SENSOR_9V OFF

2. The soil/RS485 sensor is powered only while taking a reading.
   Default warm-up time is 2000 ms.

3. Failed Modbus reads are retried three times before the packet
   marks the soil sensor invalid.

4. The old long delay between cycles is replaced with ESP32 timer
   deep sleep. Default cycle interval is 30 minutes.
   For 20 minutes, edit Config.h:
       #define SAMPLE_INTERVAL_MINUTES 20UL

5. SX1278 is placed in LoRa sleep mode before ESP32 deep sleep.

6. GPIO25 is held LOW during ESP32 deep sleep so SENSOR_9V cannot
   accidentally turn on because the control pin floats.

7. Mesh queue, local sequence number, and duplicate cache are stored
   in RTC-retained memory. This is important because normal RAM is
   lost during deep sleep.

8. If LoRa fails to initialise, the ESP32 no longer stays awake in an
   infinite error loop. It sleeps for five minutes and retries.

FILES
- FYP_Transmitter.ino
- Config.h
- Packet.h
- PowerManager.h / PowerManager.cpp
- SensorManager.h / SensorManager.cpp
- LoRaManager.h / LoRaManager.cpp
- MeshManager.h / MeshManager.cpp

ARDUINO LIBRARIES
This keeps the same external libraries your original project used:
- LoRa (Sandeep Mistry)
- ModbusMaster
- DHT sensor library

BOARD
- ESP32 Dev Module

IMPORTANT MULTI-HOP NOTE
The existing slot-based mesh behaviour is preserved. Relay nodes need their
NODE_ID, PARENT_NODE_ID and NODE_SLOT_INDEX configured correctly in Config.h.

Deep sleep works best when the field nodes begin their cycles reasonably
synchronised. The code subtracts active time from the sleep time to reduce
slot drift, but this is not a true clock-synchronisation protocol. For a much
larger deployment, add gateway time synchronisation/beacons later.

IMPORTANT ACK NOTE
The existing packet/ACK format was intentionally kept unchanged. The gateway
must use the same Packet.h structure, radio frequency, sync word, spreading
factor, bandwidth and coding rate, and it must return the matching AckPacket.

TIMESTAMP NOTE
SensorData.timestamp is still millis(), to avoid changing your packet format.
Because millis() restarts after deep sleep, it is only a local diagnostic
timestamp. If real date/time is needed, timestamp readings at the gateway or
add RTC/network time in a later protocol revision.
