// Client mirror of GET /api/config/entry-rules, for an instant inline hint
// while a PATCH is in flight. This is advisory only -- the value sent to
// the server is always the raw text the archer typed, and the server's
// Decimal-based check in core/validate.py is the actual authority. A
// float slipping in here to compute a hint is fine, because it is never
// stored and never sent; classify() only ever returns a label.

import { api } from "./api.js";

let rulesPromise = null;

export function loadEntryRules() {
  if (!rulesPromise) rulesPromise = api.get("api/config/entry-rules");
  return rulesPromise;
}

const DECIMAL_RE = /^[+-]?(?:\d+\.\d+|\.\d+|\d+)$/;

function normalize(raw) {
  return (raw || "").trim().replace(",", ".");
}

export function shapeIssue(raw, maxDp) {
  const text = normalize(raw);
  if (text === "") return "EMPTY";
  if (!DECIMAL_RE.test(text)) return "NOT_A_NUMBER";
  const dotIndex = text.indexOf(".");
  if (dotIndex >= 0 && text.length - dotIndex - 1 > maxDp) return "TOO_MANY_DP";
  return null;
}

// kind: 'spine' | 'weight'. Returns {level: 'ok'|'warn'|'error', code, message}.
export function classify(raw, rules, kind) {
  const maxDp = kind === "spine" ? rules.spineMaxDp : rules.weightMaxDp;
  const shapeErr = shapeIssue(raw, maxDp);
  if (shapeErr) {
    return { level: "error", code: shapeErr, message: "not a valid number" };
  }

  const value = parseFloat(normalize(raw));
  const minor = Math.round(value * 100);
  const hardMin = kind === "spine" ? rules.spineHardMinCp : rules.weightHardMinCg;
  const hardMax = kind === "spine" ? rules.spineHardMaxCp : rules.weightHardMaxCg;
  if (minor < hardMin || minor > hardMax) {
    return { level: "error", code: "OUT_OF_RANGE", message: "outside the plausible range" };
  }

  const step = kind === "spine" ? rules.spineStepCp : rules.weightStepCg;
  if (minor % step !== 0) {
    return { level: "warn", code: "OFF_STEP", message: "not a multiple of the expected step" };
  }

  const warnMin = kind === "spine" ? rules.spineWarnMinCp : rules.weightWarnMinCg;
  const warnMax = kind === "spine" ? rules.spineWarnMaxCp : rules.weightWarnMaxCg;
  if (minor < warnMin || minor > warnMax) {
    return { level: "warn", code: "UNUSUAL_VALUE", message: "an unusual value" };
  }

  return { level: "ok", code: null, message: null };
}
