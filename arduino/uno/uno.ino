#include <Arduino.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <Wire.h>
#include <BH1750.h>

// Protocolo 2. El rol identifica este firmware, no el modelo fisico de placa.
const char ORIGIN[] = "UNO";
const unsigned long SAMPLE_INTERVAL_MS = 1000;
struct SensorConfig {
  byte triggerPin, echoPin, pirPin, radarPin, soundPin;
  bool hcEnabled, pirEnabled, radarEnabled, luxEnabled, soundEnabled;
};
bool validConfig(const SensorConfig &candidate);
SensorConfig config = {4, 5, 6, 7, 8, true, false, false, true, true};
bool configured = false;
bool capturing = false;
unsigned long captureStartedMs = 0, lastSampleMs = 0, sequence = 0;
char inputBuffer[96];
byte inputLength = 0;
bool inputOverflow = false;
BH1750 lightMeter;
#include "gateway.h"

bool addPin(byte pin, byte *used, byte &count) {
  if (pin < 2 || pin > 12 || (gatewayMode && (pin == 2 || pin == 3))) return false;
  for (byte i = 0; i < count; ++i) if (used[i] == pin) return false;
  used[count++] = pin;
  return true;
}

bool validConfig(const SensorConfig &candidate) {
  byte used[5], count = 0;
  if (candidate.pirEnabled || candidate.radarEnabled) return false;
  if (candidate.hcEnabled && (!addPin(candidate.triggerPin, used, count) || !addPin(candidate.echoPin, used, count))) return false;
  if (candidate.pirEnabled && !addPin(candidate.pirPin, used, count)) return false;
  if (candidate.radarEnabled && !addPin(candidate.radarPin, used, count)) return false;
  if (candidate.soundEnabled && !addPin(candidate.soundPin, used, count)) return false;
  return true;
}

void releasePins() {
  // Solo libera los pines que realmente pertenecen al rol y estaban activos.
  if (config.hcEnabled) {
    digitalWrite(config.triggerPin, LOW);
    pinMode(config.triggerPin, INPUT);
    pinMode(config.echoPin, INPUT);
  }
  if (config.pirEnabled) pinMode(config.pirPin, INPUT);
  if (config.radarEnabled) pinMode(config.radarPin, INPUT);
  if (config.soundEnabled) pinMode(config.soundPin, INPUT);
}

void configurePins() {
  if (config.hcEnabled) {
    pinMode(config.triggerPin, OUTPUT);
    digitalWrite(config.triggerPin, LOW);
    pinMode(config.echoPin, INPUT);
  }
  if (config.pirEnabled) pinMode(config.pirPin, INPUT);
  if (config.radarEnabled) pinMode(config.radarPin, INPUT);
  if (config.soundEnabled) pinMode(config.soundPin, INPUT);
}

bool parseByteValue(const char *text, byte &value) {
  if (!*text) return false;
  unsigned int result = 0;
  for (const char *cursor = text; *cursor; ++cursor) {
    if (*cursor < '0' || *cursor > '9') return false;
    result = result * 10 + (*cursor - '0');
    if (result > 255) return false;
  }
  value = (byte)result;
  return true;
}

void handleConfig(char **tokens, byte count) {
  if (capturing) { out.println(F("@ERR,STATE,CAPTURE_ACTIVE")); return; }
  if (count != 11) { out.println(F("@ERR,CONFIG,FORMAT")); return; }
  byte values[10];
  for (byte i = 0; i < 10; ++i) {
    if (!parseByteValue(tokens[i + 1], values[i]) || (i >= 5 && values[i] > 1)) {
      out.println(F("@ERR,CONFIG,FORMAT")); return;
    }
  }
  SensorConfig candidate = {values[0], values[1], values[2], values[3], values[4],
    (bool)values[5], (bool)values[6], (bool)values[7], (bool)values[8], (bool)values[9]};
  if (!validConfig(candidate)) { out.println(F("@ERR,CONFIG,PINS_OR_ROLE")); return; }
  if (candidate.luxEnabled) {
    Wire.begin();
    if (!lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE)) {
      out.println(F("@ERR,CONFIG,BH1750_NOT_FOUND")); return;
    }
  }
  if (configured) releasePins();
  config = candidate;
  configurePins();
  configured = true;
  out.println(F("@OK,CONFIG"));
}

void handleEnable(char **tokens, byte count) {
  if (count != 3) { out.println(F("@ERR,ENABLE,FORMAT")); return; }
  if (!configured) { out.println(F("@ERR,STATE,NOT_CONFIGURED")); return; }
  byte flag;
  if (!parseByteValue(tokens[2], flag) || flag > 1) { out.println(F("@ERR,ENABLE,FORMAT")); return; }
  SensorConfig candidate = config;
  if (strcmp(tokens[1], "HC") == 0) candidate.hcEnabled = flag;
  else if (strcmp(tokens[1], "PIR") == 0) candidate.pirEnabled = flag;
  else if (strcmp(tokens[1], "RADAR") == 0) candidate.radarEnabled = flag;
  else if (strcmp(tokens[1], "LUX") == 0) candidate.luxEnabled = flag;
  else if (strcmp(tokens[1], "SOUND") == 0) candidate.soundEnabled = flag;
  else { out.println(F("@ERR,ENABLE,SENSOR")); return; }
  if (!validConfig(candidate)) { out.println(F("@ERR,CONFIG,PINS_OR_ROLE")); return; }
  if (candidate.luxEnabled) {
    Wire.begin();
    if (!lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE)) {
      out.println(F("@ERR,CONFIG,BH1750_NOT_FOUND")); return;
    }
  }
  releasePins();
  config = candidate;
  configurePins();
  out.print(F("@OK,ENABLE,")); out.print(tokens[1]); out.print(','); out.println(flag);
}

void handleCommand(char *line) {
  char *tokens[12];
  byte count = 1;
  tokens[0] = line;
  // Conserva los campos vacios para rechazarlos; no utiliza strtok().
  for (char *cursor = line; *cursor; ++cursor) {
    if (*cursor == ',') {
      if (count >= 12) { out.println(F("@ERR,COMMAND,FORMAT")); return; }
      *cursor = '\0'; tokens[count++] = cursor + 1;
    }
  }
  if (strcmp(tokens[0], "INFO") == 0 && count == 1) {
    out.print(F("@OK,INFO,2,")); out.println(ORIGIN);
  } else if (strcmp(tokens[0], "CONFIG") == 0) handleConfig(tokens, count);
  else if (strcmp(tokens[0], "ENABLE") == 0) handleEnable(tokens, count);
  else if (strcmp(tokens[0], "STOP") == 0 && count == 1) {
    capturing = false; out.println(F("@OK,STOP"));
  } else if (strcmp(tokens[0], "START") == 0 && count == 1) {
    if (!configured) { out.println(F("@ERR,STATE,NOT_CONFIGURED")); return; }
    if (capturing) { out.println(F("@ERR,STATE,CAPTURE_ACTIVE")); return; }
    sequence = 0; captureStartedMs = lastSampleMs = millis(); capturing = true;
    out.println(F("@OK,START"));
  } else out.println(F("@ERR,COMMAND,UNKNOWN"));
}

void readCommands() { readMasterCommands(); }

void emitSample(unsigned long elapsedMs) {
  float distance = -1.0f, lux = -1.0f;
  if (config.hcEnabled) {
    digitalWrite(config.triggerPin, LOW); delayMicroseconds(2);
    digitalWrite(config.triggerPin, HIGH); delayMicroseconds(10);
    digitalWrite(config.triggerPin, LOW);
    const unsigned long echo = pulseIn(config.echoPin, HIGH, 24000UL);
    if (echo) distance = echo * 0.0343f / 2.0f;
    if (!echo || distance < 2.0f || distance > 400.0f) {
      distance = -1.0f; out.println(F("@ERR,READ,HC_SR04_NO_VALID_ECHO"));
    }
  }
  if (config.luxEnabled) {
    lux = lightMeter.readLightLevel();
    if (!isfinite(lux) || lux < 0) { lux = -1.0f; out.println(F("@ERR,READ,BH1750")); }
  }
  out.print(ORIGIN); out.print(','); out.print(++sequence); out.print(',');
  out.print(elapsedMs); out.print(',');
  if (config.hcEnabled && distance >= 0) out.print(distance, 2); else out.print(F("NA"));
  out.print(F(",NA,NA,"));
  if (config.luxEnabled && lux >= 0) out.print(lux, 2); else out.print(F("NA"));
  out.print(',');
  // Nivel electrico DO instantaneo. Verificar polaridad; no son dB ni conteos.
  if (config.soundEnabled) out.println(digitalRead(config.soundPin)); else out.println(F("NA"));
}

void setup() {
  Serial.begin(115200);
  nanoBus.begin(9600);
  // No configura sensores hasta recibir CONFIG; revisar el cableado primero.
  out.print(F("@READY,2,")); out.println(ORIGIN);
}

void loop() {
  readNano();
  readCommands();
  const unsigned long now = millis();
  if (!nanoPending && capturing && now - lastSampleMs >= SAMPLE_INTERVAL_MS) {
    lastSampleMs = now; // No genera rafagas de filas para compensar tiempo perdido.
    emitSample(now - captureStartedMs);
  }
}
