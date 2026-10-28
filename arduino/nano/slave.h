#pragma once

#if defined(ARDUINO_ARCH_MBED) || defined(ARDUINO_ARCH_MBED_NANO) || defined(ARDUINO_NANO33BLE)
#define MICROP_NANO_UART 1
#endif

bool nanoReplyUart = false, nanoCaptureUart = false;
unsigned long nanoReplyId = 0;

// Serial es USB. Serial1 es el UART D0/RX y D1/TX del Nano 33 BLE.
// Se conserva el diagnostico USB, sin permitirle cambiar una captura UART.
class SlaveOutput {
  bool beginning = true;
  void prefix() {
#ifdef MICROP_NANO_UART
    if (beginning && nanoReplyUart) {
      Serial1.print(F("@REPLY,")); Serial1.print(nanoReplyId); Serial1.print(',');
    }
#endif
    beginning = false;
  }
public:
  template<class T> void print(T value) {
    prefix();
#ifdef MICROP_NANO_UART
    if (nanoReplyUart) { Serial1.print(value); return; }
#endif
    Serial.print(value);
  }
  template<class T> void println(T value) {
    print(value);
#ifdef MICROP_NANO_UART
    if (nanoReplyUart) Serial1.print('\n'); else
#endif
    Serial.print('\n');
    beginning = true;
  }
} out;

void handleCommand(char *line);
void emitSample(unsigned long elapsedMs);

void pollSlave() {
  if (!nanoReplyUart) { out.println(F("@ERR,COMMAND,UNKNOWN")); return; }
  const unsigned long now = millis();
  if (capturing && nanoCaptureUart && now - lastSampleMs >= SAMPLE_INTERVAL_MS) {
    lastSampleMs = now;
    const unsigned long savedId = nanoReplyId;
    nanoReplyId = 0;
    emitSample(now - captureStartedMs);
    nanoReplyId = savedId;
  }
  out.println(F("@OK,POLL"));
}

void dispatchUsbCommand(char *line) {
  nanoReplyUart = false; nanoReplyId = 0;
  if (capturing && nanoCaptureUart && strcmp(line, "INFO") != 0) {
    out.println(F("@ERR,STATE,UART_CAPTURE_ACTIVE")); return;
  }
  handleCommand(line);
}

void readSlaveUart() {
#ifdef MICROP_NANO_UART
  static char buffer[128];
  static byte length = 0;
  static bool overflow = false;
  while (Serial1.available() > 0) {
    const char c = Serial1.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (!overflow && length) {
        buffer[length] = '\0';
        if (strncmp(buffer, "@CALL,", 6) == 0) {
          char *text = buffer + 6, *command = strchr(text, ',');
          if (command) {
            *command++ = '\0';
            unsigned long id = 0;
            bool valid = *text != '\0';
            for (const char *p = text; *p; ++p) {
              if (*p < '0' || *p > '9' || id > (4294967295UL - (*p - '0')) / 10UL) { valid = false; break; }
              id = id * 10 + (*p - '0');
            }
            if (valid && id && *command && strlen(command) <= 95) {
              nanoReplyUart = true; nanoReplyId = id;
              if (capturing && !nanoCaptureUart && strcmp(command, "INFO") != 0)
                out.println(F("@ERR,STATE,USB_CAPTURE_ACTIVE"));
              else handleCommand(command);
              nanoReplyUart = false; nanoReplyId = 0;
            }
          }
        }
      }
      length = 0; overflow = false;
    } else if (!overflow) {
      if (length < sizeof(buffer) - 1) buffer[length++] = c;
      else overflow = true;
    }
  }
#endif
}
