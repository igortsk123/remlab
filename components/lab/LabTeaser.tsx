import type { ReactNode } from "react";
import { Button } from "@/components/base/buttons/button";

// Тизер раздела лаборатории, который ещё в разработке: что здесь появится и куда пойти посмотреть.
// children — необязательная строка под кнопкой (например, ссылка на уже созданные дизайны).
export function LabTeaser({ icon, title, lead, href, cta, children }: {
  icon: string;
  title: string;
  lead: string;
  href: string;
  cta: string;
  children?: ReactNode;
}) {
  return (
    <div className="card stack" style={{ marginTop: 20, textAlign: "center", padding: "28px 24px" }}>
      <div style={{ fontSize: 34, lineHeight: 1 }} aria-hidden>{icon}</div>
      <h2 style={{ margin: 0, fontSize: 20 }}>{title}</h2>
      <p className="muted" style={{ margin: "0 auto", maxWidth: "44ch" }}>{lead}</p>
      <Button color="secondary" size="lg" href={href} className="self-center">{cta}</Button>
      {children}
    </div>
  );
}
