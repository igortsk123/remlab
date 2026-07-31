"use client";

import { useState } from "react";
import { Chip } from "@/components/base/chip/chip";

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
        <Chip
          key={o.value}
          isSelected={sel.includes(o.value)}
          isDisabled={o.disabled}
          onChange={() => toggle(o.value)}
        >
          {o.label}
        </Chip>
      ))}
      {sel.map((v) => (
        <input key={v} type="hidden" name={name} value={v} />
      ))}
    </div>
  );
}
