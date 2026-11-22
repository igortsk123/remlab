import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { JOB_ID_START_RE, randomJobId, randomToken, TOKEN_RE } from "@/lib/token";

// Номер задания пробы (T-20261119-02, уроки T-20261119-01/1): первый знак — буква или цифра. Стадии Python берут номер позиционным
// аргументом и именем папки; `-…` argparse примет за флаг, `_…` отвергают `trial_bundle._check_input` и `trial_demo.out_dir`
// (`[A-Za-z0-9][A-Za-z0-9_.-]{0,63}`) — 2 загрузки из 64 теряли тур без следа. Правило генератора обязано проходить ВСЕ проверки номера в Python.

const pyRules = (): { file: string; re: RegExp }[] =>
  ["tools/scout/trial_bundle.py", "tools/scout/trial_demo.py"].map((file) => {
    const src = readFileSync(path.join(process.cwd(), file), "utf8");
    const m = /re\.fullmatch\(r'(\[A-Za-z0-9\]\[A-Za-z0-9_\.-\]\{0,63\})',\s*(?:job_id|trial_id)\s+or/.exec(src);
    if (!m) throw new Error(`${file}: проверка номера задания не найдена (правило поменялось — сверить генератор)`);
    return { file, re: new RegExp(`^${m[1]}$`) };
  });

describe("randomJobId", () => {
  it("первый знак — буква или цифра, остальное — как у токена (22 знака base64url)", () => {
    for (let i = 0; i < 20_000; i++) {
      const id = randomJobId();
      expect(id).toMatch(TOKEN_RE);
      expect(id).toMatch(JOB_ID_START_RE);
    }
  });

  it("токен на `_`/`-` отбрасывается, берётся следующий; прочие токены без ограничений", () => {
    const seq = [`-${"A".repeat(21)}`, `_${"B".repeat(21)}`, `C${"D".repeat(21)}`];
    let n = 0;
    expect(randomJobId(() => seq[n++]!)).toBe(seq[2]);
    expect(n).toBe(3);
    // `randomToken` не менялся: на `_`/`-` по-прежнему начинается ≈ 1 из 32 (все остальные токены сайта)
    let bad = 0;
    for (let i = 0; i < 20_000; i++) if (!JOB_ID_START_RE.test(randomToken())) bad++;
    expect(bad).toBeGreaterThan(300);
    expect(bad).toBeLessThan(1000);
  });

  it("генератор, который не даёт годного номера, — ошибка, а не вечный цикл", () => {
    expect(() => randomJobId(() => `_${"A".repeat(21)}`)).toThrow("job_id_unavailable");
  });
});

describe("одно правило на все проверки номера в Python", () => {
  const rules = pyRules();

  it("обе проверки найдены (trial_bundle._check_input, trial_demo.out_dir)", () => {
    expect(rules.map((r) => r.file)).toEqual(["tools/scout/trial_bundle.py", "tools/scout/trial_demo.py"]);
  });

  it("каждый выданный номер проходит обе проверки", () => {
    for (const { re } of rules) for (let i = 0; i < 20_000; i++) expect(randomJobId()).toMatch(re);
  });

  it("номер на `_`/`-` обе проверки отвергают — поэтому они не выдаются", () => {
    for (const { re } of rules) {
      expect(`_${"A".repeat(21)}`).not.toMatch(re);
      expect(`-${"A".repeat(21)}`).not.toMatch(re);
    }
  });
});
