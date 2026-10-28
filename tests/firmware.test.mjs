import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Compilacion nativa opcional con dobles de Arduino. No sustituye al core de la placa
// ni a las pruebas fisicas. Los archivos generados quedan fuera del repositorio.
const requestedCompiler = process.env.CXX || "g++";
const located = process.platform === "win32" ? spawnSync("where.exe", [requestedCompiler], { encoding: "utf8" }).stdout?.trim().split(/\r?\n/)[0] : requestedCompiler;
const compiler = located || requestedCompiler;
const environment = Object.fromEntries(Object.entries(process.env).filter(([key]) => key.toLowerCase() !== "path"));
environment.PATH = `${dirname(compiler)}${process.platform === "win32" ? ";" : ":"}${process.env.PATH || process.env.Path || ""}`;
const available = spawnSync(compiler, ["--version"], { encoding: "utf8", env: environment }).status === 0;
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const arduinoStub = String.raw`#pragma once
#include <string>
#include <sstream>
#include <iomanip>
#include <stdint.h>
using byte = unsigned char;
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define LED_BUILTIN 13
#define F(x) x
unsigned long fakeNow = 0, fakeEcho = 2300;
int pinLevels[64] = {};
unsigned long millis() { return fakeNow; }
void delayMicroseconds(int) {}
void pinMode(byte, int) {}
void digitalWrite(byte pin, int value) { pinLevels[pin] = value; }
int digitalRead(byte pin) { return pinLevels[pin]; }
unsigned long pulseIn(byte, int, unsigned long) { return fakeEcho; }
struct SerialFake {
  std::string output, input;
  void begin(long) {}
  int available() { return input.size(); }
  char read() { char c=input[0]; input.erase(0,1); return c; }
  template<class T> void print(T value) { std::ostringstream s; s << value; output += s.str(); }
  void print(unsigned char value) { print((unsigned int)value); }
  void print(float value, int digits) { std::ostringstream s; s << std::fixed << std::setprecision(digits) << value; output += s.str(); }
  template<class T> void println(T value) { print(value); output += '\n'; }
} Serial, Serial1;
`;
const softwareStub = '#pragma once\n#include "Arduino.h"\nstruct SoftwareSerial : SerialFake { SoftwareSerial(int,int) {} };\n';
const bhStub = String.raw`#pragma once
bool fakeLightFound = true;
float fakeLux = 120.5f;
struct BH1750 { enum Mode { CONTINUOUS_HIGH_RES_MODE }; bool begin(Mode) { return fakeLightFound; } float readLightLevel() { return fakeLux; } };
`;

for (const origin of ["uno", "nano"]) test(`firmware ${origin}: parser, configuracion atomica, adquisicion y recuperacion (dobles nativos)`, { skip: !available }, () => {
  const directory = mkdtempSync(join(tmpdir(), "microp-firmware-"));
  try {
    writeFileSync(join(directory, "Arduino.h"), arduinoStub);
    writeFileSync(join(directory, "SoftwareSerial.h"), softwareStub);
    writeFileSync(join(directory, "Wire.h"), "#pragma once\nstruct WireFake { void begin() {} } Wire;\n");
    writeFileSync(join(directory, "BH1750.h"), bhStub);
    const firmware = join(root, "arduino", origin, `${origin}.ino`).replaceAll("\\", "/");
    const valid = origin === "uno" ? "CONFIG,4,5,6,7,8,1,0,0,1,1" : "CONFIG,4,5,6,7,8,0,1,1,0,0";
    const invalidRole = origin === "uno" ? "ENABLE,PIR,1" : "ENABLE,LUX,1";
    const source = `#include <cassert>\n#include <cstring>\n#include "${firmware}"\n
void cmd(const char *text) { char buffer[256]; strcpy(buffer, text); Serial.output.clear(); handleCommand(buffer); }
int main() {
  setup(); assert(Serial.output == "@READY,2,${origin.toUpperCase()}\\n");
  cmd("INFO"); assert(Serial.output == "@OK,INFO,2,${origin.toUpperCase()}\\n");
  cmd("START"); assert(!capturing); assert(Serial.output.find("NOT_CONFIGURED") != std::string::npos);
  cmd("${valid}"); assert(configured); assert(Serial.output == "@OK,CONFIG\\n");
  const byte previous = config.triggerPin;
  cmd("CONFIG,4,,5,6,7,8,1,0,0,1,1"); assert(Serial.output.find("@ERR") == 0); assert(config.triggerPin == previous);
  cmd("${invalidRole}"); assert(Serial.output.find("@ERR") == 0);
  cmd("CONFIG,4,5,6,6,4,1,1,1,1,1"); assert(Serial.output.find("@ERR") == 0);
  cmd("START"); assert(capturing); assert(sequence == 0);
  fakeNow = 1000; Serial.output.clear(); loop(); assert(sequence == 1);
  assert(Serial.output.find("${origin.toUpperCase()},1,1000,") != std::string::npos);
  cmd("${valid}"); assert(Serial.output.find("CAPTURE_ACTIVE") != std::string::npos);
  ${origin === "uno" ? `fakeEcho = 0; fakeLux = -1; Serial.output.clear(); emitSample(2000);
  assert(Serial.output.find("@ERR,READ,HC_SR04") != std::string::npos);
  assert(Serial.output.find("@ERR,READ,BH1750") != std::string::npos);
  assert(Serial.output.find("UNO,2,2000,NA,NA,NA,NA,0") != std::string::npos);` : `pinLevels[6] = 1; Serial.output.clear(); emitSample(2000);
  assert(Serial.output.find("NANO,2,2000,NA,1,0,NA,NA") != std::string::npos);`}
  cmd("STOP"); assert(!capturing); cmd("START"); assert(sequence == 0);
  ${origin === "nano" ? `cmd("SIGNAL_CAPS"); assert(Serial.output == "@OK,SIGNAL_CAPS,1\\n");
  const char *id = "00000000-0000-0000-0000-000000000001";
  cmd("SIGNAL,00000000-0000-0000-0000-000000000001,ALLOW");
  assert(pinLevels[LED_BUILTIN] == HIGH); assert(capturing);
  fakeNow += 1000; loop(); assert(pinLevels[LED_BUILTIN] == LOW); assert(!signalActive);
  cmd("SIGNAL,00000000-0000-0000-0000-000000000001,ALLOW"); assert(!signalActive);
  cmd("SIGNAL,00000000-0000-0000-0000-000000000001,DENY"); assert(Serial.output.find("ID_REUSED") != std::string::npos);
  cmd("SIGNAL,invalid,DENY"); assert(Serial.output.find("@ERR") == 0);
  cmd("SIGNAL,00000000-0000-0000-0000-000000000002,DENY");
  assert(signalActive); fakeNow += 100; loop(); assert(pinLevels[LED_BUILTIN] == LOW);
  fakeNow += 500; loop(); assert(!signalActive);
  cmd("SIGNAL,00000000-0000-0000-0000-000000000003,FAULT"); assert(signalActive);
  cmd("STOP"); assert(pinLevels[LED_BUILTIN] == LOW); assert(!signalActive);
  cmd("SIGNAL,00000000-0000-0000-0000-000000000004,ALLOW"); assert(Serial.output.find("NOT_CAPTURING") != std::string::npos);` : ""}
  Serial.output.clear(); Serial.input = std::string(120, 'X') + "\\nINFO\\n"; readCommands();
  assert(Serial.output.find("TOO_LONG") != std::string::npos);
  assert(Serial.output.find("@OK,INFO,2,${origin.toUpperCase()}") != std::string::npos);
}
`;
    writeFileSync(join(directory, "check.cpp"), source);
    const executable = join(directory, process.platform === "win32" ? "check.exe" : "check");
    const build = spawnSync(compiler, ["-std=c++11", "-Wall", "-Wextra", `-I${directory}`, join(directory, "check.cpp"), "-o", executable], { encoding: "utf8", env: environment });
    assert.equal(build.status, 0, `${build.stdout}\n${build.stderr}`);
    const run = spawnSync(executable, [], { encoding: "utf8", env: environment });
    assert.equal(run.status, 0, `${run.stdout}\n${run.stderr}`);
  } finally {
    if (dirname(resolve(directory)) === resolve(tmpdir())) rmSync(directory, { recursive: true, force: true });
  }
});

for (const origin of ['uno', 'nano']) test(`firmware ${origin}: enlace maestro/esclavo correlacionado y aislamiento USB (dobles nativos)`, { skip: !available }, () => {
  const directory = mkdtempSync(join(tmpdir(), 'microp-gateway-'));
  try {
    writeFileSync(join(directory, 'Arduino.h'), arduinoStub);
    writeFileSync(join(directory, 'SoftwareSerial.h'), softwareStub);
    writeFileSync(join(directory, 'Wire.h'), '#pragma once\nstruct WireFake { void begin() {} } Wire;\n');
    writeFileSync(join(directory, 'BH1750.h'), bhStub);
    const firmware = join(root, 'arduino', origin, `${origin}.ino`).replaceAll('\\', '/');
    const body = origin === 'uno' ? String.raw`
      Serial.input="GATEWAY_INFO\n"; loop();
      assert(gatewayMode); assert(Serial.output.find("@OK,GATEWAY,1,UNO,NANO,9600")!=std::string::npos);
      Serial.output.clear(); Serial.input="@TO,UNO,1,INFO\n"; loop();
      assert(Serial.output=="@FROM,UNO,1,@OK,INFO,2,UNO\n");
      Serial.input="@TO,UNO,2,CONFIG,2,5,6,7,8,1,0,0,1,1\n"; loop(); assert(!configured);
      Serial.input="@TO,UNO,3,CONFIG,4,5,6,7,8,1,0,0,1,1\n"; loop(); assert(configured);
      Serial.input="@TO,UNO,4,START\n"; loop(); assert(capturing);
      Serial.output.clear(); Serial.input="@TO,NANO,8,INFO\n"; loop();
      assert(nanoPending); assert(nanoBus.output=="@CALL,8,INFO\n");
      fakeNow=500; loop(); assert(sequence==0); // No lectura bloqueante mientras recibe al esclavo.
      nanoBus.input="@REPLY,7,@OK,INFO,2,NANO\n"; loop(); assert(nanoPending);
      fakeNow=1000; nanoBus.input="@REPLY,8,@OK,INFO,2,NANO\n"; loop(); assert(!nanoPending); assert(sequence==1);
      assert(Serial.output.find("@FROM,NANO,8,@OK,INFO,2,NANO")!=std::string::npos);
      assert(Serial.output.find("@FROM,UNO,0,UNO,1,")!=std::string::npos);
      Serial.output.clear(); Serial.input="@TO,NANO,9,POLL\n"; loop(); fakeNow+=801; loop();
      assert(!nanoPending); assert(Serial.output.find("@FROM,NANO,9,@ERR,GATEWAY,NANO_TIMEOUT")!=std::string::npos);
      Serial.output.clear(); Serial.input="INFO\n"; loop(); assert(!gatewayMode);
      assert(Serial.output=="@OK,INFO,2,UNO\n");
    ` : String.raw`
      assert(Serial1.output=="@REPLY,0,@READY,2,NANO\n");
      Serial1.output.clear(); Serial1.input="@CALL,1,INFO\n@CALL,2,CONFIG,4,5,6,7,8,0,1,1,0,0\n@CALL,3,START\n"; loop();
      assert(capturing && nanoCaptureUart); assert(sequence==0);
      assert(Serial1.output.find("@REPLY,3,@OK,START")!=std::string::npos);
      Serial1.output.clear(); fakeNow=1000; loop(); assert(sequence==0); assert(Serial1.output.empty());
      Serial1.input="@CALL,4,POLL\n"; loop(); assert(sequence==1);
      assert(Serial1.output.find("@REPLY,0,NANO,1,1000,")!=std::string::npos);
      assert(Serial1.output.find("@REPLY,4,@OK,POLL")!=std::string::npos);
      Serial.input="STOP\n"; loop(); assert(capturing);
      assert(Serial.output.find("UART_CAPTURE_ACTIVE")!=std::string::npos);
      Serial1.output.clear(); Serial1.input="@CALL,5,SIGNAL_CAPS\n@CALL,6,SIGNAL,00000000-0000-0000-0000-000000000001,ALLOW\n"; loop();
      assert(signalActive); assert(Serial1.output.find("@REPLY,6,@OK,SIGNAL,")!=std::string::npos);
      fakeNow+=1001; loop(); assert(!signalActive); assert(pinLevels[LED_BUILTIN]==LOW);
      Serial1.input="@CALL,7,STOP\n"; loop(); assert(!capturing);
      Serial.input="CONFIG,4,5,6,7,8,0,1,1,0,0\nSTART\n"; loop(); assert(capturing && !nanoCaptureUart);
      Serial1.input="@CALL,8,STOP\n"; loop(); assert(capturing);
      assert(Serial1.output.find("USB_CAPTURE_ACTIVE")!=std::string::npos);
    `;
    writeFileSync(join(directory, 'gateway.cpp'), `#define ARDUINO_ARCH_MBED_NANO 1\n#include <cassert>\n#include <cstring>\n#include "${firmware}"\nint main(){ setup(); Serial.output.clear(); ${body} }\n`);
    const executable = join(directory, process.platform === 'win32' ? 'gateway.exe' : 'gateway');
    const build = spawnSync(compiler, ['-std=c++11', '-Wall', '-Wextra', `-I${directory}`, join(directory, 'gateway.cpp'), '-o', executable], { encoding: 'utf8', env: environment });
    assert.equal(build.status, 0, build.stderr);
    const run = spawnSync(executable, [], { encoding: 'utf8', env: environment });
    assert.equal(run.status, 0, run.stdout + run.stderr);
  } finally {
    if (dirname(resolve(directory)) === resolve(tmpdir())) rmSync(directory, { recursive: true, force: true });
  }
});
