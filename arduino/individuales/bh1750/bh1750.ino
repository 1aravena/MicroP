#include <Wire.h>
#include <BH1750.h>

// El BH1750 usa el bus I2C fijo del Uno: SDA=A4 y SCL=A5.
BH1750 lightMeter;

void setup() {
  Serial.begin(115200);
  Wire.begin();

  if (!lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE)) {
    Serial.println(F("Error: BH1750 no detectado."));
    while (true) delay(1000);
  }
}

void loop() {
  float lux = lightMeter.readLightLevel();
  Serial.print(F("Iluminacion: "));
  Serial.print(lux, 2);
  Serial.println(F(" lux"));
  delay(1000);
}
