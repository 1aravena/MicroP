import assert from "node:assert/strict";
import test from "node:test";
import {
  buildSeriesSegments,
  calculateSensorStats,
  downsampleSegment,
  formatElapsedTime,
} from "../js/charts.js";

test("separa el historial cuando un sensor entrega NA", () => {
  const rows = [
    { timeMs: 1000, distanceCm: 12 },
    { timeMs: 2000, distanceCm: 14 },
    { timeMs: 3000, distanceCm: null },
    { timeMs: 4000, distanceCm: 10 },
  ];
  assert.deepEqual(buildSeriesSegments(rows, "hc").map((segment) => segment.map((point) => point.index)), [[0, 1], [3]]);
  assert.deepEqual(calculateSensorStats(rows, "hc"), { count: 3, min: 10, max: 14 });
  assert.deepEqual(calculateSensorStats([{ timeMs: 1000, lux: null }], "lux"), { count: 0, min: null, max: null });
});

test("cuenta episodios binarios sin duplicar muestras consecutivas en 1", () => {
  const rows = [0, 1, 1, 0, 1, null, 1, 1, 0].map((pir, index) => ({ timeMs: index * 1000, pir }));
  assert.deepEqual(calculateSensorStats(rows, "pir"), { count: 8, episodes: 3 });
});

test("reduce muestras extensas conservando extremos y eventos breves", () => {
  const points = Array.from({ length: 100 }, (_, index) => ({
    index,
    timeMs: index * 1000,
    value: index === 35 ? 900 : index === 60 ? 0 : 20,
  }));
  const reduced = downsampleSegment(points, 0, 99000, 4);
  assert.ok(reduced.length <= 16);
  assert.equal(reduced[0].index, 0);
  assert.equal(reduced.at(-1).index, 99);
  assert.ok(reduced.some((point) => point.index === 35));
  assert.ok(reduced.some((point) => point.index === 60));

  const states = points.map((point) => ({ ...point, value: point.index === 52 ? 1 : 0 }));
  assert.ok(downsampleSegment(states, 0, 99000, 4).some((point) => point.index === 52));
});

test("formatea el tiempo de la captura incluso después de una hora", () => {
  assert.equal(formatElapsedTime(123000), "02:03");
  assert.equal(formatElapsedTime(3723000), "01:02:03");
});

test("intercalar Nano no corta ni rellena las lecturas de Uno", () => {
  const rows = [
    { origin: "UNO", timeMs: 1000, distanceCm: 12 },
    { origin: "NANO", timeMs: 1100, distanceCm: null, pir: 1 },
    { origin: "UNO", timeMs: 2000, distanceCm: 14 },
    { origin: "NANO", timeMs: 2100, distanceCm: null, pir: 0 },
  ];
  assert.deepEqual(calculateSensorStats(rows, "hc"), { count: 2, min: 12, max: 14 });
  assert.equal(buildSeriesSegments(rows, "hc").length, 1);
  assert.equal(buildSeriesSegments(rows, "hc")[0].length, 2);
  assert.deepEqual(calculateSensorStats(rows, "pir"), { count: 2, episodes: 1 });
});

test("un intervalo sin recepcion deja un corte visible en el grafico", () => {
  const rows = [{ timeMs: 1000, distanceCm: 10 }, { timeMs: 6000, distanceCm: 20 }];
  assert.equal(buildSeriesSegments(rows, "hc").length, 2);
});
