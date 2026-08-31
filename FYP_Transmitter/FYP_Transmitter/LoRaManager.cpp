#include "LoRaManager.h"
#include "Config.h"

#include <SPI.h>
#include <LoRa.h>
#include <cstring>

static bool loRaInitialised = false;

/*
 * Calculate a CRC-16/CCITT-style checksum over a byte array.
 */
static uint16_t calculateCRC16(
    const uint8_t *data,
    size_t length
)
{
    uint16_t crc = 0xFFFF;

    for (size_t byteIndex = 0; byteIndex < length; ++byteIndex)
    {
        crc ^= static_cast<uint16_t>(data[byteIndex]) << 8;

        for (uint8_t bit = 0; bit < 8; ++bit)
        {
            if ((crc & 0x8000) != 0)
            {
                crc = static_cast<uint16_t>(
                    (crc << 1) ^ 0x1021
                );
            }
            else
            {
                crc <<= 1;
            }
        }
    }

    return crc;
}

uint16_t calculateNetworkPacketChecksum(
    const NetworkPacket &packet
)
{
    NetworkPacket copy = packet;
    copy.checksum = 0;

    return calculateCRC16(
        reinterpret_cast<const uint8_t *>(&copy),
        sizeof(copy)
    );
}

uint16_t calculateAckPacketChecksum(
    const AckPacket &packet
)
{
    AckPacket copy = packet;
    copy.checksum = 0;

    return calculateCRC16(
        reinterpret_cast<const uint8_t *>(&copy),
        sizeof(copy)
    );
}

bool initialiseLoRa()
{
    Serial.println("Initialising LoRa...");

    /*
     * Start the ESP32 VSPI bus using your chosen pins:
     * SCK=18, MISO=19, MOSI=23, SS=5.
     */
    SPI.begin(
        LORA_SCK,
        LORA_MISO,
        LORA_MOSI,
        LORA_SS
    );

    LoRa.setSPI(SPI);
    LoRa.setPins(
        LORA_SS,
        LORA_RST,
        LORA_DIO0
    );

    if (!LoRa.begin(LORA_FREQUENCY))
    {
        loRaInitialised = false;

        Serial.println(
            "LoRa initialisation failed."
        );
        return false;
    }

    LoRa.setSyncWord(LORA_SYNC_WORD);
    LoRa.setTxPower(LORA_TX_POWER);
    LoRa.setSpreadingFactor(
        LORA_SPREADING_FACTOR
    );
    LoRa.setSignalBandwidth(
        LORA_SIGNAL_BANDWIDTH
    );
    LoRa.setCodingRate4(
        LORA_CODING_RATE
    );

    LoRa.enableCrc();
    LoRa.receive();

    loRaInitialised = true;

    Serial.println("LoRa ready.");
    return true;
}

void sleepLoRa()
{
    if (loRaInitialised)
    {
        Serial.println("Putting SX1278 into sleep mode.");
        LoRa.idle();
        LoRa.sleep();
        loRaInitialised = false;
    }

    SPI.end();
}

NetworkPacket createSensorPacket(
    const SensorData &data,
    uint32_t sequenceNumber
)
{
    NetworkPacket packet{};

    packet.magic = PACKET_MAGIC;
    packet.version = PACKET_VERSION;
    packet.packetType = PacketType::SENSOR_DATA;

    packet.sourceNode = NODE_ID;
    packet.previousHop = NODE_ID;
    packet.destinationNode = PARENT_NODE_ID;
    packet.finalDestination = GATEWAY_ID;
    packet.hopCount = 0;
    packet.sequenceNumber = sequenceNumber;

    packet.data = data;
    packet.checksum =
        calculateNetworkPacketChecksum(packet);

    return packet;
}

void preparePacketForForwarding(
    NetworkPacket &packet,
    uint8_t nextHop
)
{
    packet.previousHop = NODE_ID;
    packet.destinationNode = nextHop;

    if (packet.hopCount < UINT8_MAX)
    {
        packet.hopCount++;
    }

    packet.checksum =
        calculateNetworkPacketChecksum(packet);
}

bool sendNetworkPacket(NetworkPacket &packet)
{
    packet.checksum =
        calculateNetworkPacketChecksum(packet);

    LoRa.idle();

    if (!LoRa.beginPacket())
    {
        Serial.println(
            "Could not begin LoRa packet."
        );

        LoRa.receive();
        return false;
    }

    const size_t bytesWritten = LoRa.write(
        reinterpret_cast<const uint8_t *>(&packet),
        sizeof(packet)
    );

    const int result = LoRa.endPacket();

    LoRa.receive();

    if (bytesWritten != sizeof(packet))
    {
        Serial.println(
            "Incomplete LoRa packet write."
        );
        return false;
    }

    if (result != 1)
    {
        Serial.println(
            "LoRa transmission failed."
        );
        return false;
    }

    Serial.print("Sent packet from source ");
    Serial.print(packet.sourceNode);
    Serial.print(" to next hop ");
    Serial.print(packet.destinationNode);
    Serial.print(", sequence ");
    Serial.println(packet.sequenceNumber);

    return true;
}

bool receiveNetworkPacket(NetworkPacket &packet)
{
    const int receivedSize = LoRa.parsePacket();

    if (receivedSize == 0)
    {
        return false;
    }

    /*
     * Ignore ACKs here. The ACK-waiting function handles them.
     */
    if (receivedSize != static_cast<int>(
            sizeof(NetworkPacket)
        ))
    {
        while (LoRa.available())
        {
            LoRa.read();
        }

        return false;
    }

    const size_t bytesRead = LoRa.readBytes(
        reinterpret_cast<uint8_t *>(&packet),
        sizeof(packet)
    );

    if (bytesRead != sizeof(packet))
    {
        Serial.println(
            "Incomplete network packet received."
        );
        return false;
    }

    if (packet.magic != PACKET_MAGIC)
    {
        Serial.println(
            "Rejected packet: invalid magic value."
        );
        return false;
    }

    if (packet.version != PACKET_VERSION)
    {
        Serial.println(
            "Rejected packet: incompatible version."
        );
        return false;
    }

    if (packet.packetType != PacketType::SENSOR_DATA)
    {
        return false;
    }

    const uint16_t receivedChecksum =
        packet.checksum;

    const uint16_t calculatedChecksum =
        calculateNetworkPacketChecksum(packet);

    if (receivedChecksum != calculatedChecksum)
    {
        Serial.println(
            "Rejected packet: checksum mismatch."
        );
        return false;
    }

    /*
     * This node only processes packets addressed to it.
     * Other packets may still be heard because LoRa is broadcast.
     */
    if (packet.destinationNode != NODE_ID)
    {
        return false;
    }

    Serial.print("Received packet originating from Node ");
    Serial.print(packet.sourceNode);
    Serial.print(" through Node ");
    Serial.print(packet.previousHop);
    Serial.print(", sequence ");
    Serial.println(packet.sequenceNumber);

    return true;
}

bool sendAcknowledgement(
    const NetworkPacket &receivedPacket
)
{
    AckPacket acknowledgement{};

    acknowledgement.magic = PACKET_MAGIC;
    acknowledgement.version = PACKET_VERSION;
    acknowledgement.packetType =
        PacketType::ACKNOWLEDGEMENT;

    acknowledgement.senderNode = NODE_ID;

    /*
     * Return the ACK to the node that directly transmitted
     * the packet, not necessarily its original source.
     */
    acknowledgement.destinationNode =
        receivedPacket.previousHop;

    acknowledgement.acknowledgedSource =
        receivedPacket.sourceNode;

    acknowledgement.acknowledgedSequence =
        receivedPacket.sequenceNumber;

    acknowledgement.checksum =
        calculateAckPacketChecksum(acknowledgement);

    LoRa.idle();

    if (!LoRa.beginPacket())
    {
        LoRa.receive();
        return false;
    }

    const size_t bytesWritten = LoRa.write(
        reinterpret_cast<const uint8_t *>(
            &acknowledgement
        ),
        sizeof(acknowledgement)
    );

    const int result = LoRa.endPacket();

    LoRa.receive();

    return bytesWritten == sizeof(acknowledgement)
        && result == 1;
}

bool waitForAcknowledgement(
    uint8_t originalSource,
    uint32_t sequenceNumber,
    uint32_t timeoutMs
)
{
    const uint32_t startTime = millis();

    LoRa.receive();

    while (millis() - startTime < timeoutMs)
    {
        const int receivedSize = LoRa.parsePacket();

        if (receivedSize == 0)
        {
            delay(1);
            continue;
        }

        if (receivedSize !=
            static_cast<int>(sizeof(AckPacket)))
        {
            while (LoRa.available())
            {
                LoRa.read();
            }

            continue;
        }

        AckPacket acknowledgement{};

        const size_t bytesRead = LoRa.readBytes(
            reinterpret_cast<uint8_t *>(
                &acknowledgement
            ),
            sizeof(acknowledgement)
        );

        if (bytesRead != sizeof(acknowledgement))
        {
            continue;
        }

        if (acknowledgement.magic != PACKET_MAGIC ||
            acknowledgement.version != PACKET_VERSION ||
            acknowledgement.packetType !=
                PacketType::ACKNOWLEDGEMENT)
        {
            continue;
        }

        const uint16_t receivedChecksum =
            acknowledgement.checksum;

        const uint16_t calculatedChecksum =
            calculateAckPacketChecksum(
                acknowledgement
            );

        if (receivedChecksum != calculatedChecksum)
        {
            continue;
        }

        if (acknowledgement.destinationNode != NODE_ID)
        {
            continue;
        }

        if (acknowledgement.acknowledgedSource !=
                originalSource ||
            acknowledgement.acknowledgedSequence !=
                sequenceNumber)
        {
            continue;
        }

        Serial.print("ACK received from Node ");
        Serial.print(
            acknowledgement.senderNode
        );
        Serial.print(" | RSSI: ");
        Serial.println(LoRa.packetRssi());

        return true;
    }

    return false;
}

bool sendNetworkPacketWithRetry(
    NetworkPacket &packet
)
{
    for (uint8_t attempt = 1;
         attempt <= MAX_SEND_RETRIES;
         ++attempt)
    {
        Serial.print("Transmission attempt ");
        Serial.print(attempt);
        Serial.print("/");
        Serial.println(MAX_SEND_RETRIES);

        if (!sendNetworkPacket(packet))
        {
            delay(RETRY_DELAY_MS);
            continue;
        }

        if (waitForAcknowledgement(
                packet.sourceNode,
                packet.sequenceNumber,
                ACK_TIMEOUT_MS
            ))
        {
            return true;
        }

        Serial.println(
            "ACK timeout. Retrying..."
        );

        delay(RETRY_DELAY_MS);
    }

    Serial.println(
        "Packet failed after all retries."
    );

    return false;
}

void printNetworkPacket(
    const NetworkPacket &packet
)
{
    Serial.println();
    Serial.println(
        "========== LoRa Network Packet =========="
    );

    Serial.print("Original source: ");
    Serial.println(packet.sourceNode);

    Serial.print("Previous hop: ");
    Serial.println(packet.previousHop);

    Serial.print("Next hop: ");
    Serial.println(packet.destinationNode);

    Serial.print("Final destination: ");
    Serial.println(packet.finalDestination);

    Serial.print("Sequence: ");
    Serial.println(packet.sequenceNumber);

    Serial.print("Hop count: ");
    Serial.println(packet.hopCount);

    Serial.print("Soil moisture: ");
    Serial.println(packet.data.soilMoisture);

    Serial.print("Soil temperature: ");
    Serial.println(packet.data.soilTemperature);

    Serial.print("EC: ");
    Serial.println(packet.data.ec);

    Serial.print("pH: ");
    Serial.println(packet.data.ph);

    Serial.print("N: ");
    Serial.println(packet.data.nitrogen);

    Serial.print("P: ");
    Serial.println(packet.data.phosphorus);

    Serial.print("K: ");
    Serial.println(packet.data.potassium);

    Serial.print("Air temperature: ");
    Serial.println(packet.data.airTemperature);

    Serial.print("Humidity: ");
    Serial.println(packet.data.humidity);

    Serial.print("RSSI of last reception: ");
    Serial.println(LoRa.packetRssi());

    Serial.println(
        "========================================="
    );
}