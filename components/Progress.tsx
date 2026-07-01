export function Progress({ step, total = 5 }: { step: number; total?: number }) {
  return (
    <div className="progress" aria-label={`Шаг ${step} из ${total}`}>
      {Array.from({ length: total }).map((_, i) => (
        <span key={i} data-on={i < step} />
      ))}
    </div>
  );
}
