#pragma once
#include <SoftwareSerial.h>

// El Uno es el maestro del enlace D2(RX)/D3(TX). Solo consulta al Nano
// cuando Raspberry autoriza una transaccion; asi no se solapan recepciones
// SoftwareSerial con comandos entrantes a 115200 por el UART hardware.
SoftwareSerial nanoBus(2, 3);
bool gatewayMode = false;
unsigned long replyId = 0, nanoRequestId = 0, nanoRequestStarted = 0;
bool nanoPending = false;
char masterInput[144], nanoInput[176];
byte masterLength = 0, nanoLength = 0;
bool masterOverflow = false, nanoOverflow = false;

class MasterOutput {
  bool beginning = true;
  void prefix() {
    if (beginning && gatewayMode) {
      Serial.print(F("@FROM,UNO,")); Serial.print(replyId); Serial.print(',');
    }
    beginning = false;
  }
public:
  template<class T> void print(T value) { prefix(); Serial.print(value); }
  void print(float value, int digits) { prefix(); Serial.print(value, digits); }
  template<class T> void println(T value) { print(value); Serial.print('\n'); beginning = true; }
} out;

void handleCommand(char *line);

void gatewayError(const char *origin, unsigned long id, const char *reason) {
  Serial.print(F("@FROM,")); Serial.print(origin); Serial.print(','); Serial.print(id);
  Serial.print(F(",@ERR,GATEWAY,")); Serial.println(reason);
}

bool requestNumber(const char *text, unsigned long &value) {
  if (!*text) return false;
  value = 0;
  for (const char *p = text; *p; ++p) {
    if (*p < '0' || *p > '9' || value > (4294967295UL - (*p - '0')) / 10UL) return false;
    value = value * 10 + (*p - '0');
  }
  return value != 0;
}

void dispatchMaster(char *line) {
  if (strcmp(line, "GATEWAY_INFO") == 0) {
    Serial.println(F("@OK,GATEWAY,1,UNO,NANO,9600"));
    gatewayMode = true;
    return;
  }
  if (strncmp(line, "@TO,", 4) != 0) {
    // INFO sin envoltura conserva el diagnostico USB del Uno.
    if (strcmp(line, "INFO") == 0) gatewayMode = false;
    replyId = 0;
    handleCommand(line);
    return;
  }
  char *origin = line + 4;
  char *idText = strchr(origin, ',');
  if (!idText) return;
  *idText++ = '\0';
  char *command = strchr(idText, ',');
  if (!command) return;
  *command++ = '\0';
  unsigned long id;
  if (!requestNumber(idText, id) || !*command || strlen(command) > 95) return;
  gatewayMode = true;
  if (strcmp(origin, "UNO") == 0) {
    replyId = id;
    handleCommand(command);
    replyId = 0;
  } else if (strcmp(origin, "NANO") == 0) {
    if (nanoPending) { gatewayError("NANO", id, "BUSY"); return; }
    nanoPending = true; nanoRequestId = id; nanoRequestStarted = millis();
    nanoBus.print(F("@CALL,")); nanoBus.print(id); nanoBus.print(','); nanoBus.println(command);
  } else gatewayError("UNO", id, "ORIGIN");
}

void readMasterCommands() {
  while (Serial.available() > 0) {
    const char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (masterOverflow || (masterLength > 95 && strncmp(masterInput, "@TO,", 4) != 0)) Serial.println(F("@ERR,COMMAND,TOO_LONG"));
      else if (masterLength) { masterInput[masterLength] = '\0'; dispatchMaster(masterInput); }
      masterLength = 0; masterOverflow = false;
    } else if (!masterOverflow) {
      if (masterLength < sizeof(masterInput) - 1) masterInput[masterLength++] = c;
      else masterOverflow = true;
    }
  }
}

void forwardNano(char *line) {
  if (strncmp(line, "@REPLY,", 7) != 0) return;
  char *idText = line + 7;
  char *payload = strchr(idText, ',');
  if (!payload) return;
  *payload++ = '\0';
  unsigned long id = 0;
  if (strcmp(idText, "0") != 0 && !requestNumber(idText, id)) return;
  Serial.print(F("@FROM,NANO,")); Serial.print(id); Serial.print(','); Serial.println(payload);
  const bool terminal = strncmp(payload, "@OK,", 4) == 0 ||
    (strncmp(payload, "@ERR,", 5) == 0 && strncmp(payload, "@ERR,READ,", 10) != 0);
  if (nanoPending && id == nanoRequestId && terminal) nanoPending = false;
  if (nanoPending && strncmp(payload, "@READY", 6) == 0) {
    gatewayError("NANO", nanoRequestId, "NANO_RESET"); nanoPending = false;
  }
}

void readNano() {
  while (nanoBus.available() > 0) {
    const char c = nanoBus.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (nanoOverflow && nanoPending) {
        gatewayError("NANO", nanoRequestId, "FRAME_TOO_LONG"); nanoPending = false;
      } else if (nanoLength && !nanoOverflow) { nanoInput[nanoLength] = '\0'; forwardNano(nanoInput); }
      nanoLength = 0; nanoOverflow = false;
    } else if (!nanoOverflow) {
      if (nanoLength < sizeof(nanoInput) - 1) nanoInput[nanoLength++] = c;
      else nanoOverflow = true;
    }
  }
  if (nanoPending && millis() - nanoRequestStarted >= 800UL) {
    gatewayError("NANO", nanoRequestId, "NANO_TIMEOUT"); nanoPending = false;
  }
}
