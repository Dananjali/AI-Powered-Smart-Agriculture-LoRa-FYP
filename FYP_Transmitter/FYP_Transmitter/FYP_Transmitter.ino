#include "Config.h"
#include "Packet.h"

#include "PowerManager.h"
#include "SensorManager.h"
#include "LoRaManager.h"
#include "MeshManager.h"

/*
 * Captured near the beginning of boot so setup time is included
 * when calculating the remaining sleep time. This helps all nodes
 * stay closer to the configured network-cycle period.
 */
static uint32_t cycleStartTime = 0;

static void printLocalSensorData(
    const SensorData &ownSensorData
)
{
    Serial.println();
    Serial.println(
        "========== Local Sensor Data =========="
    );

    Serial.print("Node: ");
    Serial.println(ownSensorData.nodeID);

    Serial.print("Status flags: 0x");
    Serial.println(
        ownSensorData.statusFlags,
        HEX
    );

    Serial.print("Soil moisture: ");
    Serial.print(ownSensorData.soilMoisture);
    Serial.println(" %");

    Serial.print("Soil temperature: ");
    Serial.print(ownSensorData.soilTemperature);
    Serial.println(" C");

    Serial.print("EC: ");
    Serial.print(ownSensorData.ec);
    Serial.println(" us/cm");

    Serial.print("pH: ");
    Serial.println(ownSensorData.ph);

    Serial.print("Nitrogen: ");
    Serial.print(ownSensorData.nitrogen);
    Serial.println(" mg/kg");

    Serial.print("Phosphorus: ");
    Serial.print(ownSensorData.phosphorus);
    Serial.println(" mg/kg");

    Serial.print("Potassium: ");
    Serial.print(ownSensorData.potassium);
    Serial.println(" mg/kg");

    Serial.print("Air temperature: ");
    Serial.print(ownSensorData.airTemperature);
    Serial.println(" C");

    Serial.print("Humidity: ");
    Serial.print(ownSensorData.humidity);
    Serial.println(" %");

    Serial.println(
        "======================================="
    );
}

void setup()
{
    cycleStartTime = millis();

    Serial.begin(115200);
    delay(500);

    Serial.println();
    Serial.println(
        "===================================="
    );
    Serial.println(
        " Scalable Multi-Hop Field Node"
    );
    Serial.println(
        " Power-Optimised Firmware"
    );
    Serial.println(
        "===================================="
    );

    initialisePowerManagement();
    printWakeReason();

    /*
     * A timer/ext wake means RTC-retained mesh state can be
     * restored. A normal reset/power cycle starts clean.
     */
    const bool restoreMeshState =
        wokeFromDeepSleep();

    initialiseSensors();

    if (!initialiseLoRa())
    {
        Serial.println(
            "LoRa could not start."
        );
        Serial.println(
            "Sleeping for 5 minutes before retry."
        );

        setSensorPower(false);
        sleepLoRa();

        enterDeepSleep(
            LORA_FAILURE_RETRY_SLEEP_MS
        );
    }

    initialiseMesh(restoreMeshState);

    Serial.println("Field node ready.");
}

void loop()
{
    Serial.println();
    Serial.println(
        "===================================="
    );
    Serial.println(
        " Starting new network cycle"
    );
    Serial.println(
        "===================================="
    );

    /*
     * 1. Listen for packets from earlier-slot nodes.
     */
    receivePackets(cycleStartTime);

    /*
     * 2. Read this node's sensors.
     *
     * readSensors() now handles GPIO25:
     *   ON -> warm up -> read -> OFF
     */
    Serial.println("Reading local sensors...");

    SensorData ownSensorData =
        readSensors();

    printLocalSensorData(ownSensorData);

    /*
     * 3. Add this reading to the same queue used for relayed
     * packets. The queue and sequence counter are retained
     * across deep-sleep wakeups.
     */
    if (!addOwnPacket(ownSensorData))
    {
        Serial.println(
            "Could not queue local sensor data."
        );
    }

    /*
     * 4. Forward queued packets to the configured parent.
     */
    forwardPackets();

    printMeshStatus();

    /*
     * 5. Power down the external LoRa radio before the ESP32
     * enters deep sleep.
     */
    sleepLoRa();

    /*
     * 6. Replace the old long delay() with timer deep sleep.
     *
     * Subtract active time so a nominal 30-minute cycle remains
     * close to 30 minutes rather than 30 minutes + awake time.
     */
    const uint32_t elapsedTime =
        millis() - cycleStartTime;

    uint64_t sleepDurationMs =
        MINIMUM_RECOVERY_SLEEP_MS;

    if (elapsedTime < NETWORK_CYCLE_MS)
    {
        sleepDurationMs =
            static_cast<uint64_t>(
                NETWORK_CYCLE_MS - elapsedTime
            );
    }
    else
    {
        Serial.println(
            "Warning: network cycle exceeded configured duration."
        );
        Serial.println(
            "Using minimum recovery sleep."
        );
    }

    enterDeepSleep(sleepDurationMs);
}
