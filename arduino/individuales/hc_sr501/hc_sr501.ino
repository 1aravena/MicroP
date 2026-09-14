// HC-SR501: la salida digital OUT se conecta a D6.
const byte PIR_PIN = 6;

void setup() {
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT);
}

void loop() {
  int movement = digitalRead(PIR_PIN);
  Serial.print(F("Movimiento PIR: "));
  Serial.println(movement == HIGH ? F("Detectado (1)") : F("No detectado (0)"));
  delay(500);
}
