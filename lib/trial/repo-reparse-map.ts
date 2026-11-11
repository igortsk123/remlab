// «Перечитать планировку» (план trial-reparse-01; T-20261111-02): после перечитывания у комнат и проёмов плана могут смениться номера
// (`trial_bundle.py` нумерует по порядку комнат). Правки агента хранятся по номерам ПРОЧИТАННОГО плана (`028`/`029`), поэтому публикация
// `reparse` той же транзакцией переписывает их на новые номера по карте воркера (однозначные геометрические пары, `tools/floorplan/
// conveyor.py:Reparse`): иначе следующая «Обустроить» положила бы правку по старому номеру на чужую комнату. Переименование — в два шага
// (сперва во временный ключ `~…`): ключ строки — первичный, обмен номерами двух правок иначе упёрся бы в него посреди обновления.

import { sql } from "drizzle-orm";
import type { TrialReparseMap } from "@/contracts/trial-bundle";
import type { Tx } from "@/lib/trial/repo-rebuild";

export async function applyReparseMap(tx: Tx, jobId: string, map: TrialReparseMap): Promise<void> {
  const rooms = map.rooms.filter((m) => m.from !== m.to);
  for (const m of rooms) {
    await tx.execute(sql`update trial_room_edits set room_key = ${`~${m.panel}|${m.from}`}
      where job_id = ${jobId} and room_key = ${`${m.panel}|${m.from}`}`);
  }
  for (const m of map.rooms) {
    const key = m.from === m.to ? `${m.panel}|${m.from}` : `~${m.panel}|${m.from}`;
    await tx.execute(sql`update trial_room_edits set room_key = ${`${m.panel}|${m.to}`}, src_id = ${m.to},
        anchor = ${JSON.stringify(m.anchor)}::jsonb, updated_at = now()
      where job_id = ${jobId} and room_key = ${key}`);
  }
  const ops = map.openings.filter((m) => m.key !== m.to);
  for (const m of ops) {
    await tx.execute(sql`update trial_opening_edits set op_key = ${`~${m.panel}|${m.key}`}
      where job_id = ${jobId} and op_key = ${`${m.panel}|${m.key}`}`);
  }
  for (const m of map.openings) {
    const key = m.key === m.to ? `${m.panel}|${m.key}` : `~${m.panel}|${m.key}`;
    await tx.execute(sql`update trial_opening_edits set op_key = ${`${m.panel}|${m.to}`}, src_idx = ${m.srcIdx},
        src_c = ${m.srcC ? JSON.stringify(m.srcC) : null}::jsonb, c = ${JSON.stringify(m.c)}::jsonb, updated_at = now()
      where job_id = ${jobId} and op_key = ${key}`);
  }
}
