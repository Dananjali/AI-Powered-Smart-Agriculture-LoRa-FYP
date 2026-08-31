#include "SensorManager.h"
#include "Config.h"
#include "PowerManager.h"

#include <ModbusMaster.h>
#include <DHT.h>

ModbusMaster soilNode;
DHT dht(DHTPIN, DHTTYPE);

void initialiseSensors()
{
    Serial.println("Initialising sensor interfaces...");

    Serial2.begin(
        RS485_BAUD,
        SERIAL_8N1,
        RS485_RX,
        RS485_TX
    );

    soilNode.begin(
        MODBUS_SLAVE_ID,
        Serial2
    );

    dht.begin();

    /*
     * The power manager already forced GPIO25 LOW.
     * Repeat the OFF command here as a safety measure.
     */
    setSensorPower(false);

    Serial.println("Sensor interfaces ready.");
}

SensorData readSensors()
{
    SensorData sensorData{};

    sensorData.nodeID = NODE_ID;
    sensorData.statusFlags = 0;

    /*
     * millis() restarts after every deep-sleep wake. Treat this
     * as a local diagnostic timestamp, not absolute wall time.
     * The gateway should timestamp received data if real time is
     * required.
     */
    sensorData.timestamp = millis();

    /****************************************************
     *              SWITCH SENSOR POWER ON
     ****************************************************/

    setSensorPower(true);

    Serial.print(
        "Waiting for soil sensor startup: "
    );
    Serial.print(SENSOR_STARTUP_DELAY_MS);
    Serial.println(" ms.");

    delay(SENSOR_STARTUP_DELAY_MS);

    /****************************************************
     *                 MODBUS SOIL SENSOR
     ****************************************************/

    uint8_t result = 0xFF;
    bool soilReadSuccessful = false;

    for (uint8_t attempt = 1;
         attempt <= SENSOR_READ_RETRIES;
         ++attempt)
    {
        Serial.print("Modbus sensor attempt ");
        Serial.print(attempt);
        Serial.print("/");
        Serial.println(SENSOR_READ_RETRIES);

        result =
            soilNode.readHoldingRegisters(
                0x0000,
                7
            );

        if (result == soilNode.ku8MBSuccess)
        {
            soilReadSuccessful = true;
            break;
        }

        Serial.print("Modbus read failed. Code: ");
        Serial.println(result);

        if (attempt < SENSOR_READ_RETRIES)
        {
            delay(SENSOR_RETRY_DELAY_MS);
        }
    }

    if (soilReadSuccessful)
    {
        sensorData.soilMoisture =
            soilNode.getResponseBuffer(0) / 10.0f;

        sensorData.soilTemperature =
            static_cast<int16_t>(
                soilNode.getResponseBuffer(1)
            ) / 10.0f;

        sensorData.ec =
            soilNode.getResponseBuffer(2);

        sensorData.ph =
            soilNode.getResponseBuffer(3) / 10.0f;

        sensorData.nitrogen =
            soilNode.getResponseBuffer(4);

        sensorData.phosphorus =
            soilNode.getResponseBuffer(5);

        sensorData.potassium =
            soilNode.getResponseBuffer(6);

        sensorData.statusFlags |=
            SOIL_SENSOR_VALID;

        Serial.println("Modbus sensor read OK.");
    }
    else
    {
        sensorData.soilMoisture = NAN;
        sensorData.soilTemperature = NAN;
        sensorData.ec = 0;
        sensorData.ph = NAN;
        sensorData.nitrogen = 0;
        sensorData.phosphorus = 0;
        sensorData.potassium = 0;
    }

    /****************************************************
     *                       DHT11
     ****************************************************/

    const float humidity =
        dht.readHumidity();

    const float airTemperature =
        dht.readTemperature();

    if (!isnan(humidity) &&
        !isnan(airTemperature))
    {
        sensorData.humidity = humidity;
        sensorData.airTemperature =
            airTemperature;

        sensorData.statusFlags |=
            DHT_SENSOR_VALID;
    }
    else
    {
        Serial.println("DHT11 read failed.");

        sensorData.humidity = NAN;
        sensorData.airTemperature = NAN;
    }

    /****************************************************
     *              SWITCH SENSOR POWER OFF
     ****************************************************/

    setSensorPower(false);

    return sensorData;
}
