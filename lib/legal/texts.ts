// Тексты политики, cookie и условий (план b2b-04, ADR-0268) — ЧЕРНОВИКИ ДЛЯ ЮРИСТА. Факты (какие данные, где
// хранятся, сколько живут, кому уходят) — из карты данных `docs/data-map.md`; юридические формулировки, основания
// и сроки, которые выбирает владелец, — местами `{{…}}`. Правило проекта: юридическую логику не реализуем.

export type LegalDoc = "privacy" | "cookies" | "terms";
export type LegalLang = "ru" | "en";
export type LegalSection = { h: string; p: string[] };
export type LegalText = { title: string; draftNote: string; sections: LegalSection[] };

const OPERATOR = "{{ОПЕРАТОР: наименование, ОГРН/ОГРНИП, адрес}}";
const OPERATOR_EN = "{{CONTROLLER: legal name, registration number, address}}";

const RU: Record<LegalDoc, LegalText> = {
  privacy: {
    title: "Политика обработки персональных данных",
    draftNote: "Черновик: текст проверяет юрист; места в фигурных скобках заполняет владелец.",
    sections: [
      { h: "Кто обрабатывает данные", p: [`Оператор: ${OPERATOR}. Связь по вопросам данных: {{e-mail для запросов}}.`] },
      {
        h: "Какие данные и зачем",
        p: [
          "Заявка «найдём дешевле» и вопросы по смете: e-mail или чат мессенджера, город, ссылки на товары — чтобы ответить на заявку.",
          "«Отправить подборку себе» в демо: номер или имя в мессенджере — только чтобы доставить фотографии и список мебели.",
          "Ссылка от менеджера застройщика: мы не спрашиваем имя и телефон покупателя; видно только, что по ссылке открывали и выбирали.",
          "Технические данные: адрес IP — для защиты от злоупотреблений: в счётчиках частоты запросов — до двух суток, в заявке «отправить себе» — вместе с ней (90 дней), в журнале сервера — {{срок хранения журналов}}.",
          "Фото комнаты (если вы загружаете его для подбора) — чтобы построить предложение по ремонту.",
        ],
      },
      {
        h: "Сколько храним",
        p: [
          "Контакт для «отправить себе» — 90 дней. Счётчики посещений без идентификаторов — до 400 дней.",
          "Заявки — {{срок хранения заявок}}. Журналы обработки фото и текстов ИИ — 90 дней.",
        ],
      },
      {
        h: "Кому передаём",
        p: [
          "Хостинг: {{провайдер и страна сервера}}. Доставка сообщений: Telegram. Аналитика сайта: Яндекс.Метрика.",
          "Обработка фото и текстов моделями ИИ: {{поставщики ИИ и страны — трансграничная передача}}.",
          "Застройщику, по ссылке которого вы пришли, — только обезличенные действия по этой ссылке.",
        ],
      },
      { h: "Ваши права", p: ["Узнать, какие данные о вас есть, исправить или удалить их: напишите на {{e-mail для запросов}}. {{Порядок и сроки ответа}}."] },
      { h: "Основание обработки", p: ["{{Основание: согласие / договор / законный интерес — определяет юрист}}."] },
    ],
  },
  cookies: {
    title: "Cookie и хранение в браузере",
    draftNote: "Черновик: текст проверяет юрист.",
    sections: [
      { h: "Что сохраняется", p: [
        "Яндекс.Метрика (cookie и запись действий на странице) — статистика посещений и улучшение сайта.",
        "Настройки в вашем браузере (localStorage): язык, масштаб шрифта, избранное и номера ваших коллекций — чтобы сайт помнил ваш выбор. Эти данные к нам не уходят.",
        "Идентификатор сеанса (cookie) — чтобы ваши сметы и проекты открывались у вас.",
      ] },
      { h: "Как отказаться", p: ["Cookie Метрики можно удалить в настройках браузера; в английской версии сайта Метрика включается только после вашего согласия."] },
    ],
  },
  terms: {
    title: "Условия использования",
    draftNote: "Черновик: текст проверяет юрист.",
    sections: [
      { h: "Что это за сервис", p: ["Калькуляторы материалов, сметы и демонстрация мебели в квартире. Цены и наличие — от магазинов, на дату, указанную рядом с ценой; итоговую цену и наличие уточняйте у продавца."] },
      { h: "Ссылки на магазины", p: ["Часть ссылок — партнёрские: магазин может платить нам комиссию, цена для вас от этого не меняется."] },
      { h: "Ответственность", p: ["{{Ограничение ответственности — формулирует юрист}}."] },
    ],
  },
};

const EN: Record<LegalDoc, LegalText> = {
  privacy: {
    title: "Privacy notice",
    draftNote: "Draft: to be reviewed by a lawyer; placeholders in braces are filled in by the owner.",
    sections: [
      { h: "Who we are", p: [`Controller: ${OPERATOR_EN}. Data requests: {{privacy e-mail}}.`] },
      {
        h: "What we collect and why",
        p: [
          "“Send to myself” in the demo: your messenger handle or number — only to deliver the photos and the furniture list.",
          "A link from the developer's sales manager: we do not ask for your name or phone; we only record what was opened and chosen via that link.",
          "Technical data: IP address — to prevent abuse: up to two days in rate-limit counters, 90 days with a “send to myself” request, {{server log retention}} in server logs.",
        ],
      },
      { h: "How long we keep it", p: ["Delivery contact — 90 days. Visit counters without identifiers — up to 400 days. Other records — {{retention periods}}."] },
      { h: "Who receives it", p: ["Hosting: {{provider and country}}. Messaging: Telegram. Analytics (only with your consent): Yandex Metrica. AI processing: {{AI providers and countries}}."] },
      { h: "Your rights", p: ["You can request access, correction or deletion of your data at {{privacy e-mail}}. {{Lawful basis, DSAR procedure and response time — to be set by a lawyer (UK GDPR)}}."] },
    ],
  },
  cookies: {
    title: "Cookies and browser storage",
    draftNote: "Draft: to be reviewed by a lawyer.",
    sections: [
      { h: "What is stored", p: [
        "Yandex Metrica analytics cookies — only after you accept them in the banner.",
        "Preferences in your browser (localStorage): language, font size, favourites and the numbers of your saved collections. These stay on your device.",
      ] },
      { h: "Changing your choice", p: ["Clear site data in your browser to withdraw consent; the banner will ask again."] },
    ],
  },
  terms: {
    title: "Terms of use",
    draftNote: "Draft: to be reviewed by a lawyer.",
    sections: [
      { h: "The service", p: ["A furniture and fit-out demonstration for a specific apartment. Prices and availability come from shops and are dated; confirm the final price with the seller."] },
      { h: "Affiliate links", p: ["Some links are affiliate links: the shop may pay us a commission at no extra cost to you."] },
      { h: "Liability", p: ["{{Limitation of liability — to be drafted by a lawyer}}."] },
    ],
  },
};

export function legalText(doc: LegalDoc, lang: LegalLang): LegalText {
  return (lang === "en" ? EN : RU)[doc];
}
