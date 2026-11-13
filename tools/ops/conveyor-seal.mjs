// ПЕЧАТЬ СОБРАННОГО ФАЙЛА — пара `tools/ops/conveyor_seal.py` для node (T-20261112-121, план conveyor-guards-01 шаг 2).
// `"_seal": "<sha256>"` — хеш текста файла с пустым значением печати; ручная правка ломает печать → красный `conveyor_check.py`.
import { createHash } from "node:crypto";

const SEAL = /"_seal":\s*"([0-9a-f]*)"/;

/** Текст с проставленной печатью; ключ `_seal` в тексте обязателен. */
export function sealText(text) {
  const m = SEAL.exec(text);
  if (!m) throw new Error('в тексте нет ключа "_seal" — генератор обязан его писать');
  const at = m.index + m[0].length - 1 - m[1].length;
  const blank = text.slice(0, at) + text.slice(at + m[1].length);
  return blank.slice(0, at) + createHash("sha256").update(blank, "utf8").digest("hex") + blank.slice(at);
}

/** true — цела, false — сломана, null — печати нет. */
export function verifyText(text) {
  return SEAL.test(text) ? sealText(text) === text : null;
}
