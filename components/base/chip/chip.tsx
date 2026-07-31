"use client";

import type { ToggleButtonProps as AriaToggleButtonProps } from "react-aria-components";
import { ToggleButton as AriaToggleButton } from "react-aria-components";
import { cx } from "@/utils/cx";

// Чип-переключатель remlab (выбор комнаты/опций в калькуляторах) в конвенциях Untitled UI:
// react-aria ToggleButton + семантические токены. Собственный примитив — у UUI нет chip-select.
interface ChipProps extends AriaToggleButtonProps {
  size?: "sm" | "md";
}

export const Chip = ({ size = "md", className, ...props }: ChipProps) => {
  return (
    <AriaToggleButton
      {...props}
      className={(state) =>
        cx(
          "inline-flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full ring-1 ring-inset transition duration-100 ease-linear",
          "outline-brand focus-visible:outline-2 focus-visible:outline-offset-2",
          size === "md" ? "px-3.5 py-2 text-md" : "px-3 py-1.5 text-sm",
          state.isSelected
            ? "bg-brand-solid text-white ring-transparent hover:bg-brand-solid_hover"
            : "bg-primary text-secondary ring-border-primary hover:bg-secondary",
          state.isDisabled && "cursor-not-allowed opacity-45",
          typeof className === "function" ? className(state) : className,
        )
      }
    />
  );
};
