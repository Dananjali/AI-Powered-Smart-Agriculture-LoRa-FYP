#include "PowerManager.h"
#include "Config.h"

#include <esp_sleep.h>
#include <driver/gpio.h>

void initialisePowerManagement()
{
    /*
     * GPIO holds survive deep sleep. Release them before normal
     * GPIO use, then immediately force the sensor rail OFF.
     */
    gpio_deep_sleep_hold_dis();

    /*
     * Configure the desired LOW state before releasing the
     * per-pin hold. This avoids a brief unwanted level change
     * when the hold is removed after wakeup.
     */
    pinMode(SENSOR_POWER_PIN, OUTPUT);
    digitalWrite(SENSOR_POWER_PIN, LOW);

    gpio_hold_dis(
        static_cast<gpio_num_t>(SENSOR_POWER_PIN)
    );

    digitalWrite(SENSOR_POWER_PIN, LOW);

    Serial.println(
        "Power manager ready. SENSOR_9V forced OFF."
    );
}

void setSensorPower(bool enabled)
{
    digitalWrite(
        SENSOR_POWER_PIN,
        enabled ? HIGH : LOW
    );

    Serial.print("Sensor power: ");
    Serial.println(enabled ? "ON" : "OFF");
}

bool wokeFromDeepSleep()
{
    return esp_sleep_get_wakeup_cause() !=
        ESP_SLEEP_WAKEUP_UNDEFINED;
}

void printWakeReason()
{
    const esp_sleep_wakeup_cause_t cause =
        esp_sleep_get_wakeup_cause();

    Serial.print("Wake reason: ");

    switch (cause)
    {
        case ESP_SLEEP_WAKEUP_TIMER:
            Serial.println("deep-sleep timer");
            break;

        case ESP_SLEEP_WAKEUP_EXT0:
            Serial.println("external EXT0");
            break;

        case ESP_SLEEP_WAKEUP_EXT1:
            Serial.println("external EXT1");
            break;

        case ESP_SLEEP_WAKEUP_TOUCHPAD:
            Serial.println("touchpad");
            break;

        case ESP_SLEEP_WAKEUP_ULP:
            Serial.println("ULP");
            break;

        case ESP_SLEEP_WAKEUP_UNDEFINED:
        default:
            Serial.println(
                "power-on/reset (not deep-sleep wake)"
            );
            break;
    }
}

void enterDeepSleep(uint64_t sleepDurationMs)
{
    /*
     * Sensor power must remain OFF throughout deep sleep.
     */
    digitalWrite(SENSOR_POWER_PIN, LOW);

    /*
     * Hold GPIO25 LOW during deep sleep. This prevents the
     * NPN/P-MOSFET control node from floating and accidentally
     * enabling the 9 V sensor rail.
     */
    gpio_hold_en(
        static_cast<gpio_num_t>(SENSOR_POWER_PIN)
    );
    gpio_deep_sleep_hold_en();

    esp_sleep_enable_timer_wakeup(
        sleepDurationMs * 1000ULL
    );

    Serial.print("Entering deep sleep for ");
    Serial.print(
        static_cast<unsigned long>(
            sleepDurationMs / 1000ULL
        )
    );
    Serial.println(" seconds.");

    Serial.flush();

    esp_deep_sleep_start();
}
