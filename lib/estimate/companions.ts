// «Предвосхищение» (ADR-0016): под каждый вид расчёта — сопутствующие материалы, чтобы человек
// «ничего не забыл». MVP — статичный список без цен (цены/нормы придут из pricing-db-ru).

export type CalcKind = "oboi" | "plitka" | "kraska" | "laminat";

// title — им. падеж; titleGen — «Сколько нужно <род.>»; acc — голый вин. падеж («ссылку на <обои>»);
// accYour/accYours — вин. с «выбранные вами …»/«ваши …»; work — «материалы для <работы>».
export const CALC_META: Record<
  CalcKind,
  { title: string; titleGen: string; unit: string; verb: string; acc: string; accYour: string; accYours: string; work: string }
> = {
  oboi: { title: "Обои", titleGen: "обоев", unit: "рулон", verb: "поклейки обоев", acc: "обои", accYour: "выбранные вами обои", accYours: "ваши обои", work: "поклейки" },
  plitka: { title: "Плитка", titleGen: "плитки", unit: "м²", verb: "укладки плитки", acc: "плитку", accYour: "выбранную вами плитку", accYours: "вашу плитку", work: "укладки" },
  kraska: { title: "Краска", titleGen: "краски", unit: "л", verb: "покраски", acc: "краску", accYour: "выбранную вами краску", accYours: "вашу краску", work: "покраски" },
  laminat: { title: "Ламинат", titleGen: "ламината", unit: "упаковка", verb: "укладки ламината", acc: "ламинат", accYour: "выбранный вами ламинат", accYours: "ваш ламинат", work: "укладки" },
};

export const COMPANIONS: Record<CalcKind, string[]> = {
  oboi: ["Клей обойный", "Грунтовка", "Шпатель обойный", "Валик и кисть", "Отвес/уровень"],
  plitka: ["Плиточный клей", "Крестики", "Затирка для швов", "Грунтовка", "Плиткорез"],
  kraska: ["Грунтовка", "Малярный скотч", "Валик и ванночка", "Кисть для углов", "Укрывная плёнка"],
  laminat: ["Подложка", "Плинтус", "Порожки", "Клинья распорные", "Подложка гидроизоляционная"],
};
