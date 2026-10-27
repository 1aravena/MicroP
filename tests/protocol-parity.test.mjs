import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { defaultConfig, serializeConfig, parseIdentity, parseSampleLine } from "../js/protocol.js";
const fixtures = JSON.parse(readFileSync(new URL("./fixtures/protocol-v2.json", import.meta.url), "utf8"));
for (const [index, item] of fixtures.identities.entries()) test(`contrato compartido identidad ${index}`, () => {
  if (item.valid) assert.equal(parseIdentity(item.line, item.origin).version, 2);
  else assert.throws(() => parseIdentity(item.line, item.origin));
});
for (const [index, item] of fixtures.configs.entries()) test(`contrato compartido configuracion ${index}`, () => {
  const defaults = defaultConfig(item.origin);
  const config = { ...defaults, ...item.patch, enabled: { ...defaults.enabled, ...item.patch.enabled } };
  if (item.valid) assert.equal(serializeConfig(config), item.command);
  else assert.throws(() => serializeConfig(config));
});
for (const [index, item] of fixtures.samples.entries()) test(`contrato compartido muestra ${index}`, () => {
  const config = defaultConfig(item.origin);
  for (const key of item.disabled ?? []) config.enabled[key] = false;
  if (!item.valid) { assert.throws(() => parseSampleLine(item.line, config)); return; }
  const result = parseSampleLine(item.line, config);
  for (const [key, value] of Object.entries(item.expected)) assert.equal(result[key], value);
});
