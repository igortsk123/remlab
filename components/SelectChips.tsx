"use client";

import { useState } from "react";

type Opt = { value: string; label: string; disabled?: boolean };

export function SelectChips({
  name,
  options,
  mode = "multi",
  initial = [],
}: {
  name: string;
  options: Opt[];
  mode?: "single" | "multi";
  initial?: string[];
}) {
  const [sel, setSel] = useState<string[]>(initial);

  function toggle(v: string) {
    setSel((s) =>
      mode === "single" ? [v] : s.includes(v) ? s.filter((x) => x !== v) : [...s, v],
    );
  }

  return (
    <div className="row">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className="chip"
          data-selected={sel.includes(o.value)}
          data-disabled={o.disabled}
          onClick={() => !o.disabled && toggle(o.value)}
        >
          {o.label}
        </button>
      ))}
      {sel.map((v) => (
        <input key={v} type="hidden" name={name} value={v} />
      ))}
    </div>
  );
}
