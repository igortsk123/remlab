"use client";

import { useState } from "react";
import type { CalcKind } from "@/contracts/calc";
import { Button } from "@/components/base/buttons/button";
import { LeadModal, type LeadChannel } from "./LeadModal";

// Выделенная карточка «Найдём этот товар дешевле» (П7): любой из трёх чипов открывает ОДНУ модалку
// с городом; канал определяет хвост (e-mail поле / кнопки подписки на бота после заявки).
export function LeadCard({ kind, url }: { kind: CalcKind; url: string | undefined }) {
  const [channel, setChannel] = useState<LeadChannel | null>(null);

  return (
    <div className="card stack lead-card">
      <strong style={{ fontSize: 15 }}>Найдём этот товар дешевле</strong>
      <span className="muted" style={{ fontSize: 14 }}>
        Оставьте e-mail или подпишитесь на бота: сообщим, когда найдём выгоднее, и подскажем, чем дополнить.
      </span>
      <div className="row" style={{ gap: 8 }}>
        <Button type="button" color="secondary" size="sm" className="rounded-full" onClick={() => setChannel("tg")}>Телеграм</Button>
        <Button type="button" color="secondary" size="sm" className="rounded-full" onClick={() => setChannel("max")}>MAX</Button>
        <Button type="button" color="secondary" size="sm" className="rounded-full" onClick={() => setChannel("email")}>✉ Сообщить по почте</Button>
      </div>
      {channel && <LeadModal kind={kind} url={url} channel={channel} onClose={() => setChannel(null)} />}
    </div>
  );
}
