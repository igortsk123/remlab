// Вид комнаты по названию, которое агент дал в окошке правки (T-20261110-36): от вида зависит, обставляется ли комната (гостиная и спальня —
// `tools/scout/trial_bundle.py:FURNISHED`) и какой она стадии. Русские и английские слова; не узнали — `other` («Помещение»).

export type RoomKind = "living" | "bedroom" | "kitchen" | "bathroom" | "hall" | "other";

const RULES: [RoomKind, RegExp][] = [
  ["bathroom", /ванн|туалет|санузел|с\/у|уборн|душев|bath|toilet|\bwc\b|shower|cloakroom/i],
  ["living", /гостин|^зал\b|living|lounge|reception|sitting/i],   // «Кухня-гостиная» — гостиная: её обставляют
  ["kitchen", /кухн|kitchen/i],
  ["bedroom", /спальн|детск|bedroom/i],
  ["hall", /коридор|прихож|холл|\bhall|corridor|landing|entrance/i],
];

export function roomKindOf(name: string): RoomKind {
  return RULES.find(([, re]) => re.test(name))?.[0] ?? "other";
}
