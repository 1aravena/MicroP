#include <NewPing.h>

// HC-SR04: Trigger en D4, Echo en D5 y distancia maxima de 400 cm.
const byte TRIGGER_PIN = 4;
const byte ECHO_PIN = 5;
const unsigned int MAX_DISTANCE_CM = 400;

// NewPing genera el pulso Trigger, espera Echo y convierte el tiempo a cm.
NewPing sonar(TRIGGER_PIN, ECHO_PIN, MAX_DISTANCE_CM);

void setup() {
  Serial.begin(115200);
}

void loop() {
  unsigned int distanceCm = sonar.ping_cm();
  Serial.print(F("Distancia: "));
  Serial.print(distanceCm);
  Serial.println(F(" cm (0 significa sin eco)"));
  delay(1000);
}
