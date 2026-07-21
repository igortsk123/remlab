"use client";

import { useState } from "react";
import type { CalcKind } from "@/contracts/calc";
import { LeadModal } from "./LeadModal";

const TG_BOT = process.env.NEXT_PUBLIC_TELEGRAM_BOT;
const MAX_BOT = process.env.NEXT_PUBLIC_MAX_BOT;

// Выделенная карточка «Найдём этот товар дешевле»: контакт (боты/почта) под конкретный товар (url).
export function LeadCard({ kind, url }: { kind: CalcKind; url: string | undefined }) {
  const [modal, setModal] = useState(false);
  const tgHref = TG_BOT ? `https://t.me/${TG_BOT}` : null;
  const maxHref = MAX_BOT ? `https://max.ru/${MAX_BOT}` : null;

  return (
    <div className="card stack lead-card">
      <strong style={{ fontSize: 15 }}>Найдём этот товар дешевле</strong>
      <span className="muted" style={{ fontSize: 13 }}>
        Оставьте e-mail или подпишитесь на бота — сообщим, когда найдём выгоднее, и подскажем, чем дополнить.
      </span>
      <div className="row" style={{ gap: 8 }}>
        {tgHref
          ? <a className="chip" href={tgHref} target="_blank" rel="noopener noreferrer">Телеграм</a>
          : <button type="button" className="chip">Телеграм</button>}
        {maxHref
          ? <a className="chip" href={maxHref} target="_blank" rel="noopener noreferrer">MAX</a>
          : <button type="button" className="chip">MAX</button>}
        <button type="button" className="chip" onClick={() => setModal(true)}>✉ Сообщить по почте</button>
      </div>
      {modal && <LeadModal kind={kind} url={url} onClose={() => setModal(false)} />}
    </div>
  );
}
