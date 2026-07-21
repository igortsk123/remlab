"use client";

import { useEffect, useState, type CSSProperties } from "react";

// Число из строки с разделителем «.» или «,», включая промежуточный ввод «1,» / «1.». undefined — пусто.
export function parseNum(s: string): number | undefined {
  const t = s.replace(",", ".");
  if (t === "" || t === ".") return undefined;
  const v = parseFloat(t);
  return Number.isFinite(v) && v >= 0 ? v : undefined;
}

const numToRaw = (n: number | undefined): string => (n == null || n === 0 ? "" : String(n));

// Числовой инпут: держит «сырую» строку (даёт набрать «1,2»/«1.»/«1,»), наружу отдаёт число.
// Ресинк с внешним value — только когда оно реально разошлось (напр. автозаполнение по ссылке),
// иначе набор дробной части не сбрасывается.
export function NumInput({
  value,
  onChange,
  style,
  placeholder,
  ariaLabel,
}: {
  value: number | undefined;
  onChange: (n: number | undefined) => void;
  style?: CSSProperties;
  placeholder?: string;
  ariaLabel?: string;
}) {
  const [raw, setRaw] = useState<string>(() => numToRaw(value));

  useEffect(() => {
    if (parseNum(raw) !== value) setRaw(numToRaw(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <input
      style={style}
      inputMode="decimal"
      placeholder={placeholder}
      aria-label={ariaLabel}
      value={raw}
      onChange={(e) => {
        const t = e.target.value;
        if (!/^[0-9]*[.,]?[0-9]*$/.test(t)) return; // только цифры и один разделитель
        setRaw(t);
        onChange(parseNum(t));
      }}
    />
  );
}
