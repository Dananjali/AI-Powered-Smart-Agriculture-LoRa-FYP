/*
  FYP Receiver / Base Station Node 99
  -----------------------------------
  Hardware:
    ESP32 + SX1278 LoRa module + USB connection to laptop

  Behaviour:
    1. Receives NetworkPacket from any field/relay node destined for Node 99.
    2. Verifies packet structure and CRC.
    3. Immediately sends the ACK expected by the transmitter.
    4. Suppresses duplicate logging caused by transmitter retries.
    5. Prints one machine-readable DATA line for the laptop logger.

  DATA output format:
  DATA,node_id,sequence,hop_count,status_flags,soil_moisture,
       soil_temperature,ec,ph,nitrogen,phosphorus,potassium,
       air_temperature,humidity,rssi,snr
*/

#include <Arduino.h>
#include <SPI.h>
#include <LoRa.h>
#include <cstring>

#include "Packet.h"
#include "ReceiverConfig.h"

struct SeenPacket
{
    uint8_t sourceNode;
    uint32_t sequenceNumber;
    bool valid;
};

static SeenPacket duplicateCache[DUPLICATE_CACHE_SIZE];
static uint8_t duplicateWriteIndex = 0;

static uint16_t calculateCRC16(const uint8_t *data, size_t length)
{
    uint16_t crc = 0xFFFF;

    for (size_t byteIndex = 0; byteIndex < length; ++byteIndex)
    {
        crc ^= static_cast<uint16_t>(data[byteIndex]) << 8;

        for (uint8_t bit = 0; bit < 8; ++bit)
        {
            if (crc & 0x8000)
                crc = static_cast<uint16_t>((crc << 1) ^ 0x1021);
            else
                crc <<= 1;
        }
    }

    return crc;
}

static uint16_t calculateNetworkPacketChecksum(const NetworkPacket &packet)
{
    NetworkPacket copy = packet;
    copy.checksum = 0;

    return calculateCRC16(
        reinterpret_cast<const uint8_t *>(&copy),
        sizeof(copy)
    );
}

static uint16_t calculateAckPacketChecksum(const AckPacket &packet)
{
    AckPacket copy = packet;
    copy.checksum = 0;

    return calculateCRC16(
        reinterpret_cast<const uint8_t *>(&copy),
        sizeof(copy)
    );
}

static bool isDuplicate(uint8_t sourceNode, uint32_t sequenceNumber)
{
    for (uint8_t i = 0; i < DUPLICATE_CACHE_SIZE; ++i)
    {
        if (duplicateCache[i].valid &&
            duplicateCache[i].sourceNode == sourceNode &&
            duplicateCache[i].sequenceNumber == sequenceNumber)
        {
            return true;
        }
    }

    return false;
}

static void rememberPacket(uint8_t sourceNode, uint32_t sequenceNumber)
{
    duplicateCache[duplicateWriteIndex].sourceNode = sourceNode;
    duplicateCache[duplicateWriteIndex].sequenceNumber = sequenceNumber;
    duplicateCache[duplicateWriteIndex].valid = true;

    duplicateWriteIndex++;
    if (duplicateWriteIndex >= DUPLICATE_CACHE_SIZE)
        duplicateWriteIndex = 0;
}

static bool initialiseLoRa()
{
    Serial.println("Initialising receiver LoRa...");

    SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_SS);

    LoRa.setSPI(SPI);
    LoRa.setPins(LORA_SS, LORA_RST, LORA_DIO0);

    if (!LoRa.begin(LORA_FREQUENCY))
    {
        Serial.println("ERROR: LoRa initialisation failed.");
        return false;
    }

    LoRa.setSyncWord(LORA_SYNC_WORD);
    LoRa.setTxPower(LORA_TX_POWER);
    LoRa.setSpreadingFactor(LORA_SPREADING_FACTOR);
    LoRa.setSignalBandwidth(LORA_SIGNAL_BANDWIDTH);
    LoRa.setCodingRate4(LORA_CODING_RATE);
    LoRa.enableCrc();
    LoRa.receive();

    Serial.println("Receiver LoRa ready.");
    return true;
}

static bool sendAcknowledgement(const NetworkPacket &receivedPacket)
{
    AckPacket acknowledgement{};

    acknowledgement.magic = PACKET_MAGIC;
    acknowledgement.version = PACKET_VERSION;
    acknowledgement.packetType = PacketType::ACKNOWLEDGEMENT;

    acknowledgement.senderNode = RECEIVER_NODE_ID;

    // ACK goes to the node that directly transmitted this packet.
    acknowledgement.destinationNode = receivedPacket.previousHop;

    // These are exactly what the transmitter matches while waiting.
    acknowledgement.acknowledgedSource = receivedPacket.sourceNode;
    acknowledgement.acknowledgedSequence = receivedPacket.sequenceNumber;

    acknowledgement.checksum =
        calculateAckPacketChecksum(acknowledgement);

    LoRa.idle();

    if (!LoRa.beginPacket())
    {
        LoRa.receive();
        return false;
    }

    size_t written = LoRa.write(
        reinterpret_cast<const uint8_t *>(&acknowledgement),
        sizeof(acknowledgement)
    );

    int result = LoRa.endPacket();

    LoRa.receive();

    return written == sizeof(acknowledgement) && result == 1;
}

static void printDataLine(
    const NetworkPacket &packet,
    int rssi,
    float snr
)
{
    // IMPORTANT:
    // The laptop adds the real wall-clock timestamp.
    // packet.data.timestamp is only ESP32 millis() from its wake cycle.
    Serial.print("DATA,");
    Serial.print(packet.data.nodeID);
    Serial.print(",");
    Serial.print(packet.sequenceNumber);
    Serial.print(",");
    Serial.print(packet.hopCount);
    Serial.print(",");
    Serial.print(packet.data.statusFlags);
    Serial.print(",");

    Serial.print(packet.data.soilMoisture, 2);
    Serial.print(",");
    Serial.print(packet.data.soilTemperature, 2);
    Serial.print(",");
    Serial.print(packet.data.ec);
    Serial.print(",");
    Serial.print(packet.data.ph, 2);
    Serial.print(",");
    Serial.print(packet.data.nitrogen);
    Serial.print(",");
    Serial.print(packet.data.phosphorus);
    Serial.print(",");
    Serial.print(packet.data.potassium);
    Serial.print(",");
    Serial.print(packet.data.airTemperature, 2);
    Serial.print(",");
    Serial.print(packet.data.humidity, 2);
    Serial.print(",");
    Serial.print(rssi);
    Serial.print(",");
    Serial.println(snr, 2);
}

static void handleIncomingPacket()
{
    int receivedSize = LoRa.parsePacket();

    if (receivedSize == 0)
        return;

    if (receivedSize != static_cast<int>(sizeof(NetworkPacket)))
    {
        while (LoRa.available())
            LoRa.read();

        Serial.print("IGNORED,size=");
        Serial.println(receivedSize);
        return;
    }

    NetworkPacket packet{};

    size_t bytesRead = LoRa.readBytes(
        reinterpret_cast<uint8_t *>(&packet),
        sizeof(packet)
    );

    if (bytesRead != sizeof(packet))
    {
        Serial.println("IGNORED,incomplete_packet");
        return;
    }

    const int rssi = LoRa.packetRssi();
    const float snr = LoRa.packetSnr();

    if (packet.magic != PACKET_MAGIC)
    {
        Serial.println("IGNORED,bad_magic");
        return;
    }

    if (packet.version != PACKET_VERSION)
    {
        Serial.println("IGNORED,bad_version");
        return;
    }

    if (packet.packetType != PacketType::SENSOR_DATA)
    {
        Serial.println("IGNORED,not_sensor_data");
        return;
    }

    uint16_t receivedChecksum = packet.checksum;
    uint16_t calculatedChecksum =
        calculateNetworkPacketChecksum(packet);

    if (receivedChecksum != calculatedChecksum)
    {
        Serial.println("IGNORED,bad_checksum");
        return;
    }

    // Receiver accepts packets whose immediate destination is 99.
    if (packet.destinationNode != RECEIVER_NODE_ID)
    {
        Serial.println("IGNORED,not_for_receiver_99");
        return;
    }

    // ACK first so the field node can stop retrying quickly.
    bool ackSent = sendAcknowledgement(packet);

    Serial.print("RX,node=");
    Serial.print(packet.sourceNode);
    Serial.print(",seq=");
    Serial.print(packet.sequenceNumber);
    Serial.print(",from_hop=");
    Serial.print(packet.previousHop);
    Serial.print(",rssi=");
    Serial.print(rssi);
    Serial.print(",snr=");
    Serial.print(snr, 2);
    Serial.print(",ack=");
    Serial.println(ackSent ? "OK" : "FAILED");

    // A retry may arrive if the first ACK was lost.
    // ACK it again, but do not create a duplicate dataset row.
    if (isDuplicate(packet.sourceNode, packet.sequenceNumber))
    {
        Serial.print("DUPLICATE,node=");
        Serial.print(packet.sourceNode);
        Serial.print(",seq=");
        Serial.println(packet.sequenceNumber);
        return;
    }

    rememberPacket(packet.sourceNode, packet.sequenceNumber);

    printDataLine(packet, rssi, snr);
}

void setup()
{
    Serial.begin(115200);
    delay(1000);

    memset(duplicateCache, 0, sizeof(duplicateCache));

    Serial.println();
    Serial.println("====================================");
    Serial.println(" FYP LoRa Base Station Receiver");
    Serial.println(" Node ID: 99");
    Serial.println("====================================");

    if (!initialiseLoRa())
    {
        while (true)
        {
            Serial.println("Receiver halted - check SX1278 wiring.");
            delay(3000);
        }
    }

    Serial.println("Waiting for field-node packets...");
}

void loop()
{
    handleIncomingPacket();
    delay(1);
}
