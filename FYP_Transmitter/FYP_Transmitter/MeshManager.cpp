#include "MeshManager.h"

#include "Config.h"
#include "LoRaManager.h"

#include <cstring>
#include <esp_attr.h>

/*
 * Packet queue.
 *
 * Each entry contains one original sensor reading.
 * A relay forwards packets individually rather than combining
 * all readings into one oversized LoRa transmission.
 */
static constexpr uint32_t MESH_STATE_MAGIC = 0x4D455348UL;

RTC_DATA_ATTR static uint32_t meshStateMagic = 0;
RTC_DATA_ATTR static NetworkPacket packetQueue[MAX_PACKET_QUEUE];
RTC_DATA_ATTR static uint8_t queueCount = 0;

/*
 * Used to assign a unique sequence number to packets
 * created by this node.
 */
RTC_DATA_ATTR static uint32_t localSequenceNumber = 0;

/*
 * Duplicate cache entry.
 *
 * A packet is uniquely identified using:
 *     original source node + sequence number
 */
struct DuplicateEntry
{
    uint8_t sourceNode;
    uint32_t sequenceNumber;
    bool valid;
};

RTC_DATA_ATTR static DuplicateEntry duplicateCache[DUPLICATE_CACHE_SIZE];
RTC_DATA_ATTR static uint8_t duplicateWriteIndex = 0;

/*
 * Returns true when the packet has already been received.
 */
static bool isDuplicatePacket(const NetworkPacket &packet)
{
    for (uint8_t index = 0;
         index < DUPLICATE_CACHE_SIZE;
         ++index)
    {
        if (!duplicateCache[index].valid)
        {
            continue;
        }

        if (duplicateCache[index].sourceNode ==
                packet.sourceNode &&
            duplicateCache[index].sequenceNumber ==
                packet.sequenceNumber)
        {
            return true;
        }
    }

    return false;
}

/*
 * Saves a packet identifier in the duplicate cache.
 *
 * The cache is circular. Old entries are overwritten
 * when it becomes full.
 */
static void rememberPacket(const NetworkPacket &packet)
{
    duplicateCache[duplicateWriteIndex].sourceNode =
        packet.sourceNode;

    duplicateCache[duplicateWriteIndex].sequenceNumber =
        packet.sequenceNumber;

    duplicateCache[duplicateWriteIndex].valid = true;

    duplicateWriteIndex++;

    if (duplicateWriteIndex >= DUPLICATE_CACHE_SIZE)
    {
        duplicateWriteIndex = 0;
    }
}

/*
 * Adds a packet to the transmission queue.
 */
static bool enqueuePacket(const NetworkPacket &packet)
{
    if (queueCount >= MAX_PACKET_QUEUE)
    {
        Serial.println(
            "Mesh queue full. Packet discarded."
        );

        return false;
    }

    packetQueue[queueCount] = packet;
    queueCount++;

    Serial.print("Packet queued. Queue size: ");
    Serial.println(queueCount);

    return true;
}

/*
 * Removes one packet from the queue and shifts
 * remaining entries toward the beginning.
 */
static void removePacketAt(uint8_t index)
{
    if (index >= queueCount)
    {
        return;
    }

    for (uint8_t position = index;
         position + 1 < queueCount;
         ++position)
    {
        packetQueue[position] =
            packetQueue[position + 1];
    }

    queueCount--;
}

/*
 * Processes one valid packet received from another node.
 */
static void processReceivedPacket(
    const NetworkPacket &receivedPacket
)
{
    /*
     * Send an ACK even if this is a duplicate.
     *
     * A duplicate often means the previous ACK was lost.
     * Sending another ACK prevents unnecessary retries.
     */
    if (!sendAcknowledgement(receivedPacket))
    {
        Serial.println(
            "Warning: failed to transmit ACK."
        );
    }

    if (isDuplicatePacket(receivedPacket))
    {
        Serial.print(
            "Duplicate ignored. Source: "
        );
        Serial.print(receivedPacket.sourceNode);
        Serial.print(", sequence: ");
        Serial.println(
            receivedPacket.sequenceNumber
        );

        return;
    }

    if (receivedPacket.hopCount >= MAX_HOP_COUNT)
    {
        Serial.println(
            "Packet rejected: hop limit reached."
        );

        return;
    }

    if (receivedPacket.sourceNode == NODE_ID)
    {
        Serial.println(
            "Packet rejected: returned to its source."
        );

        return;
    }

    rememberPacket(receivedPacket);

    NetworkPacket packetForForwarding =
        receivedPacket;

    preparePacketForForwarding(
        packetForForwarding,
        PARENT_NODE_ID
    );

    if (enqueuePacket(packetForForwarding))
    {
        Serial.print(
            "Accepted relayed packet from original Node "
        );
        Serial.println(
            receivedPacket.sourceNode
        );
    }
}

void initialiseMesh(bool restoreRetainedState)
{
    const bool retainedStateLooksValid =
        restoreRetainedState &&
        meshStateMagic == MESH_STATE_MAGIC &&
        queueCount <= MAX_PACKET_QUEUE &&
        duplicateWriteIndex < DUPLICATE_CACHE_SIZE;

    if (!retainedStateLooksValid)
    {
        queueCount = 0;
        localSequenceNumber = 0;
        duplicateWriteIndex = 0;

        memset(
            packetQueue,
            0,
            sizeof(packetQueue)
        );

        memset(
            duplicateCache,
            0,
            sizeof(duplicateCache)
        );

        meshStateMagic = MESH_STATE_MAGIC;

        Serial.println(
            "Mesh manager started with clean state."
        );
    }
    else
    {
        Serial.println(
            "Mesh state restored from RTC memory."
        );

        Serial.print("Restored queued packets: ");
        Serial.println(queueCount);

        Serial.print("Next local sequence: ");
        Serial.println(localSequenceNumber);
    }

    Serial.print("Node ID: ");
    Serial.println(NODE_ID);

    Serial.print("Parent node: ");
    Serial.println(PARENT_NODE_ID);

    Serial.print("Transmission slot: ");
    Serial.println(NODE_SLOT_INDEX);
}

void receivePackets(uint32_t cycleStartTime)
{
    const uint32_t slotStartTime =
        cycleStartTime +
        (static_cast<uint32_t>(NODE_SLOT_INDEX) *
         SLOT_DURATION_MS);

    Serial.print(
        "Listening until transmission slot at "
    );
    Serial.print(slotStartTime);
    Serial.println(" ms.");

    /*
     * Continue listening until this node's slot starts.
     */
    while (static_cast<int32_t>(
               slotStartTime - millis()
           ) > 0)
    {
        NetworkPacket receivedPacket{};

        if (receiveNetworkPacket(receivedPacket))
        {
            printNetworkPacket(receivedPacket);

            processReceivedPacket(
                receivedPacket
            );
        }

        /*
         * Short delay prevents the ESP32 from continuously
         * spinning at full speed while still checking often.
         */
        delay(2);
    }

    Serial.println(
        "Receive window complete."
    );
}

bool addOwnPacket(const SensorData &sensorData)
{
    NetworkPacket ownPacket =
        createSensorPacket(
            sensorData,
            localSequenceNumber
        );

    localSequenceNumber++;

    /*
     * Remember our own packet so that it will be rejected
     * if a routing error sends it back to this node.
     */
    rememberPacket(ownPacket);

    Serial.print(
        "Adding local reading. Sequence: "
    );
    Serial.println(
        ownPacket.sequenceNumber
    );

    return enqueuePacket(ownPacket);
}

void forwardPackets()
{
    if (queueCount == 0)
    {
        Serial.println(
            "No packets waiting to be forwarded."
        );

        return;
    }

    Serial.print("Forwarding ");
    Serial.print(queueCount);
    Serial.println(" queued packet(s).");

    uint8_t index = 0;

    /*
     * Do not increment index after a successful send because
     * removing the current packet shifts the next one into
     * the same position.
     */
    while (index < queueCount)
    {
        NetworkPacket &packet =
            packetQueue[index];

        /*
         * Ensure the immediate destination is this node's
         * currently configured parent.
         */
        packet.previousHop = NODE_ID;
        packet.destinationNode =
            PARENT_NODE_ID;

        packet.checksum =
            calculateNetworkPacketChecksum(
                packet
            );

        Serial.println();
        Serial.print(
            "Forwarding original source Node "
        );
        Serial.print(packet.sourceNode);
        Serial.print(" to Node ");
        Serial.println(
            packet.destinationNode
        );

        const bool delivered =
            sendNetworkPacketWithRetry(packet);

        if (delivered)
        {
            Serial.println(
                "Packet delivered and removed from queue."
            );

            removePacketAt(index);
        }
        else
        {
            Serial.println(
                "Packet retained for next cycle."
            );

            index++;
        }

        /*
         * Small separation reduces back-to-back packet
         * collisions and gives the receiver time to return
         * to receive mode.
         */
        delay(100);
    }
}

uint8_t getQueuedPacketCount()
{
    return queueCount;
}

void printMeshStatus()
{
    Serial.println();
    Serial.println(
        "========== Mesh Status =========="
    );

    Serial.print("Node ID: ");
    Serial.println(NODE_ID);

    Serial.print("Parent node: ");
    Serial.println(PARENT_NODE_ID);

    Serial.print("Slot index: ");
    Serial.println(NODE_SLOT_INDEX);

    Serial.print("Queued packets: ");
    Serial.println(queueCount);

    Serial.println(
        "================================="
    );
}