// Minor-unit integer -> display string. Pure integer division and modulo
// throughout (JS numbers are exact for integers this small), so no
// floating-point rounding is ever involved -- this mirrors core/units.py's
// formatting, not its parsing. Nothing here is sent back to the server;
// the server always receives the raw text the archer typed.

function formatMinor(value, decimals) {
  if (value === null || value === undefined) return "";
  const scale = 10 ** decimals;
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  const whole = Math.floor(abs / scale);
  const frac = String(abs % scale).padStart(decimals, "0");
  return `${sign}${whole}.${frac}`;
}

export function formatSpineMlb(mlb) {
  return formatMinor(mlb, 3);
}

export function formatSpineCp(cp) {
  return formatMinor(cp, 2);
}

export function formatWeightCg(cg) {
  return formatMinor(cg, 2);
}

export function formatStraightness(value) {
  if (!value) return "–";
  return value.charAt(0) + value.slice(1).toLowerCase();
}

// abConsistent/inSpec can be null (e.g. a manually built set has no
// param_set of its own to check against, or the member isn't fully
// measured) as well as true/false, so this is a three-way flag, not a
// plain boolean-to-text switch.
export function formatFlag(value, trueText, falseText) {
  if (value === null || value === undefined) return "–";
  return value ? trueText : falseText;
}

// Grams <-> grains live-preview math. Advisory only, same as entryrules.js's
// classify(): the value actually sent to the server is always the raw
// text the archer typed in whichever column they edited, parsed there
// with Decimal (core/units.py). A JS float here never round-trips into a
// stored value -- it only ever feeds another input's displayed text.
const GRAINS_PER_GRAM = 15.4324;

export function formatGrainsFromCg(cg) {
  if (cg === null || cg === undefined) return "";
  const grains = (cg / 100) * GRAINS_PER_GRAM;
  return grains.toFixed(2);
}

// A shaft carries one canonical weight (weightCg) plus the exact text and
// unit it was last entered in. A grid or table showing both a grams and
// a grains column gets the column matching weightUnit back verbatim
// (audit requirement); the other is a value computed from weightCg.
export function deriveWeightDisplay(shaft) {
  if (shaft.weightUnit === "g") {
    return {
      weightG: shaft.weightText || "",
      weightGr: shaft.weightCg != null ? formatGrainsFromCg(shaft.weightCg) : "",
    };
  }
  if (shaft.weightUnit === "gr") {
    return {
      weightG: shaft.weightCg != null ? formatWeightCg(shaft.weightCg) : "",
      weightGr: shaft.weightText || "",
    };
  }
  return { weightG: "", weightGr: "" };
}

// unit: 'g' converts grams-text -> grains-text; 'gr' converts the reverse.
export function convertWeightLive(rawText, unit) {
  const value = parseFloat(String(rawText).trim().replace(",", "."));
  if (!isFinite(value)) return "";
  const result = unit === "g" ? value * GRAINS_PER_GRAM : value / GRAINS_PER_GRAM;
  return result.toFixed(2);
}
