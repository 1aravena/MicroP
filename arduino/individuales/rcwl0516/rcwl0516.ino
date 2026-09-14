// RCWL-0516: la salida digital OUT se conecta a D7.
const byte RADAR_PIN = 7;

void setup() {
  Serial.begin(115200);
  pinMode(RADAR_PIN, INPUT);
}

void loop() {
  int movement = digitalRead(RADAR_PIN);
  Serial.print(F("Movimiento por microondas: "));
  Serial.println(movement == HIGH ? F("Detectado (1)") : F("No detectado (0)"));
  delay(500);
}
