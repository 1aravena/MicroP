#include <Arduino.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>


// Protocolo 2. El rol identifica este firmware, no el modelo fisico de placa.
const char ORIGIN[] = "NANO";
const unsigned long SAMPLE_INTERVAL_MS = 1000;
struct SensorConfig {
  byte triggerPin, echoPin, pirPin, radarPin, soundPin;
  bool hcEnabled, pirEnabled, radarEnabled, luxEnabled, soundEnabled;
};
bool validConfig(const SensorConfig &candidate);
SensorConfig config = {4, 5, 6, 7, 8, false, true, true, false, false};
bool configured = false;
bool capturing = false;
unsigned long captureStartedMs = 0, lastSampleMs = 0, sequence = 0;
char inputBuffer[96];
byte inputLength = 0;
bool inputOverflow = false;
bool signalActive = false;
unsigned long signalStartedMs = 0;
byte signalPattern = 0;
char lastSignalId[37] = "";
byte lastSignalPattern = 0;
#include "slave.h"

void clearSignal() {
  signalActive = false;
  digitalWrite(LED_BUILTIN, LOW);
}

void updateSignal() {
  if (!signalActive) return;
  const unsigned long elapsed = millis() - signalStartedMs;
  const unsigned long duration = signalPattern == 1 ? 1000UL : signalPattern == 2 ? 600UL : 1000UL;
  if (elapsed >= duration) { clearSignal(); return; }
  digitalWrite(LED_BUILTIN, signalPattern == 1 || (elapsed / 100UL) % 2 == 0 ? HIGH : LOW);
}

bool validSignalId(const char *text) {
  if (strlen(text) != 36) return false;
  for (byte i = 0; i < 36; ++i) {
    const char c = text[i];
    if (i == 8 || i == 13 || i == 18 || i == 23) { if (c != '-') return false; }
    else if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
  }
  return true;
}

void handleSignal(char **tokens, byte count) {
  if (count != 3 || !validSignalId(tokens[1])) { out.println(F("@ERR,SIGNAL,FORMAT")); return; }
  byte pattern = strcmp(tokens[2], "ALLOW") == 0 ? 1 : strcmp(tokens[2], "DENY") == 0 ? 2 : strcmp(tokens[2], "FAULT") == 0 ? 3 : strcmp(tokens[2], "OFF") == 0 ? 0 : 255;
  if (pattern == 255) { out.println(F("@ERR,SIGNAL,FORMAT")); return; }
  if (strcmp(lastSignalId, tokens[1]) == 0) {
    if (lastSignalPattern != pattern) { out.println(F("@ERR,SIGNAL,ID_REUSED")); return; }
  } else {
    if (pattern != 0 && !capturing) { out.println(F("@ERR,STATE,NOT_CAPTURING")); return; }
    strcpy(lastSignalId, tokens[1]); lastSignalPattern = pattern;
    clearSignal(); signalPattern = pattern;
    if (pattern) { signalActive = true; signalStartedMs = millis(); updateSignal(); }
  }
  out.print(F("@OK,SIGNAL,")); out.print(tokens[1]); out.print(','); out.println(tokens[2]);
}


bool addPin(byte pin, byte *used, byte &count) {
  if (pin < 2 || pin > 12) return false;
  for (byte i = 0; i < count; ++i) if (used[i] == pin) return false;
  used[count++] = pin;
  return true;
}

bool validConfig(const SensorConfig &candidate) {
  byte used[5], count = 0;
  if (candidate.hcEnabled || candidate.luxEnabled || candidate.soundEnabled) return false;
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
  } else if (strcmp(tokens[0], "POLL") == 0 && count == 1) pollSlave();
  else if (strcmp(tokens[0], "SIGNAL_CAPS") == 0 && count == 1) out.println(F("@OK,SIGNAL_CAPS,1"));
  else if (strcmp(tokens[0], "SIGNAL") == 0) handleSignal(tokens, count);
  else if (strcmp(tokens[0], "CONFIG") == 0) handleConfig(tokens, count);
  else if (strcmp(tokens[0], "ENABLE") == 0) handleEnable(tokens, count);
  else if (strcmp(tokens[0], "STOP") == 0 && count == 1) {
    capturing = false; clearSignal(); out.println(F("@OK,STOP"));
  } else if (strcmp(tokens[0], "START") == 0 && count == 1) {
    if (!configured) { out.println(F("@ERR,STATE,NOT_CONFIGURED")); return; }
    if (capturing) { out.println(F("@ERR,STATE,CAPTURE_ACTIVE")); return; }
    sequence = 0; captureStartedMs = lastSampleMs = millis(); capturing = true; nanoCaptureUart = nanoReplyUart;
    out.println(F("@OK,START"));
  } else out.println(F("@ERR,COMMAND,UNKNOWN"));
}

void readCommands() {
  while (Serial.available() > 0) {
    const char incoming = Serial.read();
    if (incoming == '\r') continue;
    if (incoming == '\n') {
      if (inputOverflow) out.println(F("@ERR,COMMAND,TOO_LONG"));
      else if (inputLength) { inputBuffer[inputLength] = '\0'; dispatchUsbCommand(inputBuffer); }
      inputLength = 0; inputOverflow = false;
    } else if (!inputOverflow) {
      if (inputLength < sizeof(inputBuffer) - 1) inputBuffer[inputLength++] = incoming;
      else inputOverflow = true;
    }
  }
}

void emitSample(unsigned long elapsedMs) {
  out.print(ORIGIN); out.print(','); out.print(++sequence); out.print(',');
  out.print(elapsedMs); out.print(F(",NA,"));
  if (config.pirEnabled) out.print(digitalRead(config.pirPin)); else out.print(F("NA"));
  out.print(',');
  if (config.radarEnabled) out.print(digitalRead(config.radarPin)); else out.print(F("NA"));
  out.println(F(",NA,NA"));
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  clearSignal();
  Serial.begin(115200);
#ifdef MICROP_NANO_UART
  Serial1.begin(9600);
  nanoReplyUart = true;
  out.println(F("@READY,2,NANO"));
  nanoReplyUart = false;
#endif
  // No configura sensores hasta recibir CONFIG; revisar el cableado primero.
  out.print(F("@READY,2,")); out.println(ORIGIN);
}

void loop() {
  readSlaveUart();
  readCommands();
  updateSignal();
  const unsigned long now = millis();
  if (!nanoCaptureUart && capturing && now - lastSampleMs >= SAMPLE_INTERVAL_MS) {
    lastSampleMs = now; // No genera rafagas de filas para compensar tiempo perdido.
    emitSample(now - captureStartedMs);
  }
}
