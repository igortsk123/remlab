"use client";

import type { ReactNode } from "react";
import { Button as AriaButton, Dialog as AriaDialog, DialogTrigger as AriaDialogTrigger, Popover as AriaPopover } from "react-aria-components";
import { cx } from "@/utils/cx";

// Подсказка-поповер по тапу/клику. React Aria Tooltip принципиально НЕ открывается на
// тач-экранах (hover/клавиатура only), поэтому «?»-подсказки калькуляторов живут на Popover:
// тап — открыть, тап мимо или Esc — закрыть. Работает одинаково на телефоне и десктопе.
export function HintPopover({ hint, children, className }: { hint: string; children: ReactNode; className?: string }) {
  return (
    <AriaDialogTrigger>
      <AriaButton
        aria-label={hint}
        className={cx(
          "inline-flex size-6 shrink-0 cursor-help items-center justify-center rounded-full text-fg-quaternary outline-brand hover:text-fg-tertiary focus-visible:outline-2 focus-visible:outline-offset-2",
          className,
        )}
      >
        {children}
      </AriaButton>
      <AriaPopover
        offset={6}
        className={({ isEntering, isExiting }) =>
          cx(
            "max-w-[280px] rounded-lg bg-primary-solid px-3 py-2.5 text-xs leading-relaxed font-medium text-white shadow-lg outline-hidden",
            isEntering && "duration-150 ease-out animate-in fade-in",
            isExiting && "duration-100 ease-in animate-out fade-out",
          )
        }
      >
        <AriaDialog className="outline-hidden">{hint}</AriaDialog>
      </AriaPopover>
    </AriaDialogTrigger>
  );
}
