import { ProgressBarBase } from "@/components/base/progress-indicators/progress-indicators";

export function Progress({ step, total = 5 }: { step: number; total?: number }) {
  return (
    <div aria-label={`Шаг ${step} из ${total}`} className="mb-5">
      <ProgressBarBase value={step} min={0} max={total} />
    </div>
  );
}
