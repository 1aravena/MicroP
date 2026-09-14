// Modulo de sonido LM393: la salida digital DO se conecta a D8.
// En el modulo utilizado, HIGH significa evento acustico detectado.
const byte SOUND_PIN = 8;

void setup() {
  Serial.begin(115200);
  pinMode(SOUND_PIN, INPUT);
}

void loop() {
  int soundEvent = digitalRead(SOUND_PIN);
  Serial.print(F("Evento acustico: "));
  Serial.println(soundEvent == HIGH ? F("Detectado (1)") : F("Sin evento (0)"));
  delay(200);
}
