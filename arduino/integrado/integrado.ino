#include <Wire.h>
#include <BH1750.h>
#include <stdlib.h>
#include <string.h>

// Una muestra conjunta cada segundo. El HC-SR04 se limita a 400 cm.
const unsigned long SAMPLE_INTERVAL_MS = 1000;
const unsigned long ULTRASONIC_TIMEOUT_US = 24000;
const float SOUND_SPEED_CM_PER_US = 0.0343;

struct SensorConfig {
  byte triggerPin;
  byte echoPin;
  byte pirPin;
  byte radarPin;
  byte soundPin;
  bool hcEnabled;
  bool pirEnabled;
  bool radarEnabled;
  bool luxEnabled;
  bool soundEnabled;
};

SensorConfig config = {4, 5, 6, 7, 8, true, true, true, true, true};
BH1750 lightMeter;

bool configured = false;
bool capturing = false;
bool bh1750Ready = false;
unsigned long captureStartedMs = 0;
unsigned long lastSampleMs = 0;

char inputBuffer[96];
byte inputLength = 0;
bool inputOverflow = false;

void setup() {
  Serial.begin(115200);
  Wire.begin();                         // En Arduino Uno: SDA=A4 y SCL=A5.
  bh1750Ready = lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);
  Serial.println(F("@READY"));
}

void loop() {
  readSerialCommands();

  unsigned long now = millis();
  if (capturing && now - lastSampleMs >= SAMPLE_INTERVAL_MS) {
    lastSampleMs += SAMPLE_INTERVAL_MS;
    emitSample(now - captureStartedMs);
  }
}

void readSerialCommands() {
  while (Serial.available() > 0) {
    char incoming = (char)Serial.read();

    if (incoming == '\r') continue;
    if (incoming == '\n') {
      if (inputOverflow) {
        Serial.println(F("@ERR,COMMAND,TOO_LONG"));
      } else if (inputLength > 0) {
        inputBuffer[inputLength] = '\0';
        handleCommand(inputBuffer);
      }
      inputLength = 0;
      inputOverflow = false;
      continue;
    }

    if (inputLength < sizeof(inputBuffer) - 1) {
      inputBuffer[inputLength++] = incoming;
    } else {
      inputOverflow = true;
    }
  }
}

void handleCommand(char *line) {
  char *tokens[12];
  byte tokenCount = 0;
  char *context = NULL;
  char *token = strtok_r(line, ",", &context);

  while (token != NULL && tokenCount < 12) {
    tokens[tokenCount++] = token;
    token = strtok_r(NULL, ",", &context);
  }

  if (tokenCount == 0) return;
  if (strcmp(tokens[0], "CONFIG") == 0) {
    handleConfig(tokens, tokenCount);
  } else if (strcmp(tokens[0], "START") == 0 && tokenCount == 1) {
    handleStart();
  } else if (strcmp(tokens[0], "STOP") == 0 && tokenCount == 1) {
    capturing = false;
    Serial.println(F("@OK,STOP"));
  } else if (strcmp(tokens[0], "ENABLE") == 0) {
    handleEnable(tokens, tokenCount);
  } else {
    Serial.println(F("@ERR,COMMAND,UNKNOWN"));
  }
}

bool parseByteValue(const char *text, byte &value) {
  char *endPointer;
  long parsed = strtol(text, &endPointer, 10);
  if (text == endPointer || *endPointer != '\0' || parsed < 0 || parsed > 255) return false;
  value = (byte)parsed;
  return true;
}

bool parseFlag(const char *text, bool &value) {
  if (strcmp(text, "0") == 0) {
    value = false;
    return true;
  }
  if (strcmp(text, "1") == 0) {
    value = true;
    return true;
  }
  return false;
}

void handleConfig(char *tokens[], byte tokenCount) {
  if (capturing) {
    Serial.println(F("@ERR,STATE,CAPTURE_ACTIVE"));
    return;
  }
  if (tokenCount != 11) {
    Serial.println(F("@ERR,CONFIG,FORMAT"));
    return;
  }

  SensorConfig candidate;
  bool validFormat =
    parseByteValue(tokens[1], candidate.triggerPin) &&
    parseByteValue(tokens[2], candidate.echoPin) &&
    parseByteValue(tokens[3], candidate.pirPin) &&
    parseByteValue(tokens[4], candidate.radarPin) &&
    parseByteValue(tokens[5], candidate.soundPin) &&
    parseFlag(tokens[6], candidate.hcEnabled) &&
    parseFlag(tokens[7], candidate.pirEnabled) &&
    parseFlag(tokens[8], candidate.radarEnabled) &&
    parseFlag(tokens[9], candidate.luxEnabled) &&
    parseFlag(tokens[10], candidate.soundEnabled);

  if (!validFormat) {
    Serial.println(F("@ERR,CONFIG,FORMAT"));
    return;
  }

  const char *validationError = validateConfig(candidate);
  if (validationError != NULL) {
    Serial.println(validationError);
    return;
  }
  if (candidate.luxEnabled && !ensureBh1750()) {
    Serial.println(F("@ERR,CONFIG,BH1750_NOT_FOUND"));
    return;
  }

  if (configured) releasePins(config);
  config = candidate;
  configurePins(config);
  configured = true;
  Serial.println(F("@OK,CONFIG"));
}

const char *validateConfig(const SensorConfig &candidate) {
  byte allPins[] = {
    candidate.triggerPin,
    candidate.echoPin,
    candidate.pirPin,
    candidate.radarPin,
    candidate.soundPin
  };
  for (byte i = 0; i < 5; i++) {
    if (allPins[i] < 2 || allPins[i] > 12) return "@ERR,CONFIG,PIN_RANGE";
  }

  byte usedPins[5];
  byte usedCount = 0;
  if (candidate.hcEnabled) {
    if (!addUniquePin(candidate.triggerPin, usedPins, usedCount)) return "@ERR,CONFIG,DUPLICATE_PIN";
    if (!addUniquePin(candidate.echoPin, usedPins, usedCount)) return "@ERR,CONFIG,DUPLICATE_PIN";
  }
  if (candidate.pirEnabled && !addUniquePin(candidate.pirPin, usedPins, usedCount)) return "@ERR,CONFIG,DUPLICATE_PIN";
  if (candidate.radarEnabled && !addUniquePin(candidate.radarPin, usedPins, usedCount)) return "@ERR,CONFIG,DUPLICATE_PIN";
  if (candidate.soundEnabled && !addUniquePin(candidate.soundPin, usedPins, usedCount)) return "@ERR,CONFIG,DUPLICATE_PIN";
  return NULL;
}

bool addUniquePin(byte pin, byte usedPins[], byte &usedCount) {
  for (byte i = 0; i < usedCount; i++) {
    if (usedPins[i] == pin) return false;
  }
  usedPins[usedCount++] = pin;
  return true;
}

void configurePins(const SensorConfig &activeConfig) {
  if (activeConfig.hcEnabled) {
    pinMode(activeConfig.triggerPin, OUTPUT);
    digitalWrite(activeConfig.triggerPin, LOW);
    pinMode(activeConfig.echoPin, INPUT);
  }
  if (activeConfig.pirEnabled) pinMode(activeConfig.pirPin, INPUT);
  if (activeConfig.radarEnabled) pinMode(activeConfig.radarPin, INPUT);
  if (activeConfig.soundEnabled) pinMode(activeConfig.soundPin, INPUT);
}

void releasePins(const SensorConfig &oldConfig) {
  pinMode(oldConfig.triggerPin, INPUT);
  pinMode(oldConfig.echoPin, INPUT);
  pinMode(oldConfig.pirPin, INPUT);
  pinMode(oldConfig.radarPin, INPUT);
  pinMode(oldConfig.soundPin, INPUT);
}

bool ensureBh1750() {
  if (bh1750Ready) return true;
  bh1750Ready = lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);
  return bh1750Ready;
}

void handleStart() {
  if (!configured) {
    Serial.println(F("@ERR,STATE,NOT_CONFIGURED"));
    return;
  }
  if (capturing) {
    Serial.println(F("@ERR,STATE,CAPTURE_ACTIVE"));
    return;
  }
  if (config.luxEnabled && !ensureBh1750()) {
    Serial.println(F("@ERR,CONFIG,BH1750_NOT_FOUND"));
    return;
  }

  captureStartedMs = millis();
  lastSampleMs = captureStartedMs;
  capturing = true;
  Serial.println(F("@OK,START"));
}

void handleEnable(char *tokens[], byte tokenCount) {
  if (tokenCount != 3 || !configured) {
    Serial.println(tokenCount != 3 ? F("@ERR,ENABLE,FORMAT") : F("@ERR,STATE,NOT_CONFIGURED"));
    return;
  }

  bool enabled;
  if (!parseFlag(tokens[2], enabled)) {
    Serial.println(F("@ERR,ENABLE,FORMAT"));
    return;
  }

  SensorConfig candidate = config;
  if (strcmp(tokens[1], "HC") == 0) candidate.hcEnabled = enabled;
  else if (strcmp(tokens[1], "PIR") == 0) candidate.pirEnabled = enabled;
  else if (strcmp(tokens[1], "RADAR") == 0) candidate.radarEnabled = enabled;
  else if (strcmp(tokens[1], "LUX") == 0) candidate.luxEnabled = enabled;
  else if (strcmp(tokens[1], "SOUND") == 0) candidate.soundEnabled = enabled;
  else {
    Serial.println(F("@ERR,ENABLE,FORMAT"));
    return;
  }

  const char *validationError = validateConfig(candidate);
  if (validationError != NULL) {
    Serial.println(validationError);
    return;
  }
  if (candidate.luxEnabled && !ensureBh1750()) {
    Serial.println(F("@ERR,CONFIG,BH1750_NOT_FOUND"));
    return;
  }

  releasePins(config);
  config = candidate;
  configurePins(config);
  Serial.print(F("@OK,ENABLE,"));
  Serial.print(tokens[1]);
  Serial.print(',');
  Serial.println(enabled ? '1' : '0');
}

float readDistanceCm() {
  digitalWrite(config.triggerPin, LOW);
  delayMicroseconds(2);
  digitalWrite(config.triggerPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(config.triggerPin, LOW);

  unsigned long echoDuration = pulseIn(config.echoPin, HIGH, ULTRASONIC_TIMEOUT_US);
  if (echoDuration == 0) return 0.0;
  return echoDuration * SOUND_SPEED_CM_PER_US / 2.0;
}

void emitSample(unsigned long elapsedMs) {
  float distanceCm = 0.0;
  float lux = 0.0;

  if (config.hcEnabled) distanceCm = readDistanceCm();
  if (config.luxEnabled) {
    lux = lightMeter.readLightLevel();
    if (lux < 0.0) {
      Serial.println(F("@ERR,READ,BH1750"));
      return;  // No se cuenta una fila incompleta como muestra valida.
    }
  }

  Serial.print(elapsedMs);
  Serial.print(',');
  if (config.hcEnabled) Serial.print(distanceCm, 2); else Serial.print(F("NA"));
  Serial.print(',');
  if (config.pirEnabled) Serial.print(digitalRead(config.pirPin)); else Serial.print(F("NA"));
  Serial.print(',');
  if (config.radarEnabled) Serial.print(digitalRead(config.radarPin)); else Serial.print(F("NA"));
  Serial.print(',');
  if (config.luxEnabled) Serial.print(lux, 2); else Serial.print(F("NA"));
  Serial.print(',');
  if (config.soundEnabled) Serial.println(digitalRead(config.soundPin)); else Serial.println(F("NA"));
}
