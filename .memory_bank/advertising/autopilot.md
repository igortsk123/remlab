---
tier: 2
topic: ads-autopilot
scope: Автопилот рекламы на сервере — джобы, пороги, режимы (dry-run/боевой), как выключить
tier1: ../core/marketing-acquisition.md
updated: 2026-07-11
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-11
review_after: "2026-07-18"
---

# Автопилот рекламы (задеплоен 2026-07-11, режим DRY-RUN)

> Код: `infra/server/ads-watchdog/` (git) → сервер `/opt/remlab/ads-watchdog/`.
> Секреты: `.env` там же (600): Direct-токен, TG-бот, Gemini. Деплой: `deploy-watchdog.sh`.
> Тесты: `python3 -m unittest discover infra/server/ads-watchdog/tests` (9 шт).

## Джобы (systemd-таймеры, все — journalctl -u 'remlab-ads-*')
| Таймер | Когда | Что | Право записи в Директ |
|---|---|---|---|
| `remlab-ads-check` | каждые 30 мин | стоп-кран >700 ₽/день или >300 ₽/час → suspend; события статуса (модерация/старт) → TG; CPC>20 и AT>30% → warn; 2 дня <50 показов → BidCeiling +5 (max 25) | suspend, BidCeiling |
| `remlab-ads-minus` | 08–22 МСК / 2ч | новые поисковые запросы → Gemini → ≤10 минусов (ядро под стоп-листом) | NegativeKeywords |
| `remlab-ads-ab` | 10:05 МСК | группе с ≥300 пок/7д и CTR<2.5% — добавить 1 A/B-текст (валидация длин/брендов) | ads.add (только добавление) |
| `remlab-ads-report` | 21:00 МСК | сводка Директ по группам + воронка Метрики + действия роботов → TG | — |

## Модели AI (бенч 2026-07-11: 3 модели × 2 задачи)
- **Минусовка — Gemini** `gemini-flash-latest` (сейчас = линейка 2.5 Flash): классификацию все
  модели прошли 8/8, Gemini ~15× дешевле GPT-5.1 → остаётся.
- **Тексты объявлений — GPT-5.1** (`gpt-5.1-chat-latest`, ключ OpenAI соседей — жив, доступ
  gpt-4.1/gpt-5/5.1): русский заметно естественнее + ключевые фразы в Title1; фолбэк на Gemini
  при недоступности (`common.llm_for_ads`). Гоча GPT-5.x: max_completion_tokens давать с запасом
  (reasoning-токены съедают лимит, при 16 вернулся пустой ответ).
- Ключи: `/opt/remlab/ads-watchdog/.env` (`GEMINI_API_KEY`, `OPENAI_API_KEY`,
  `OPENAI_AD_MODEL` — переопределение модели текстов без правки кода).

## Пороги (решения владельца 2026-07-11)
День 700 ₽ · час 300 ₽ · CPC-предупреждение 20 ₽ · AT-доля 30% · авто-потолок ставки 25 ₽
(шаг 5 ₽, раз в 48ч) · минусов ≤10/ран · A/B ≤1/группа/нед, ≤4 объявлений в группе.
Константы — `decisions.py` (чистые функции, покрыты тестами).

## Режимы и управление
- **Сейчас: DRY_RUN=1** — в Директ НЕ пишет, в TG шлёт «🧪 [РЕПЕТИЦИЯ] что бы сделал».
- **Боевой:** в `/opt/remlab/ads-watchdog/.env` поставить `DRY_RUN=0` (план: после 3–5 дней
  чистой репетиции; поэтапность — minus → check → bid → ab, см. план ads-autopilot).
- **Выключить всё:** `ssh root@89.167.127.0 touch /opt/remlab/ads-watchdog/DISABLED`
  (или `systemctl disable --now 'remlab-ads-*'`). Убрать файл — снова работает.
- **Правила-инварианты:** возобновление кампании после стоп-крана — ТОЛЬКО человек
  (робот лишь напоминает раз в день); робот не выключает объявления/ключи; ядро семантики
  минусовать не может (`CORE_STOP_ROOTS`).
- Telegram: бот `@remontlab1_bot` → владельцу (chat 95903801); токен — `../_secrets/ACCESS.md`.

## Состояние
- **Модерация кампании 712721026 ПРОЙДЕНА** (Status=ACCEPTED, зафиксировано первым раном
  check 2026-07-11 11:44 UTC). Ждёт пополнения баланса — старт покажет TG «🚀».
- Dry-run проверен вручную: check/report/minus отработали с сервера, отчёт доставлен в TG,
  `state.json` пишется. Метрика в отчёте работает (визиты+6 целей).
- Роботы Memory Bank НЕ пишут: их журнал — TG + `state.json` (`actions`); в память переносим
  на еженедельных разборах.

## Грабли API (добыты 2026-07-11)
- Reports API: `DateRangeType` — верхний уровень params, НЕ в SelectionCriteria (8000).
- Метрика stat-API без dimensions: `totals` — плоский массив.
- Остальные (Errors:[]=успех, AutotargetingCategories=массив, символы в текстах) —
  `campaign_state.md` §Мины.

**Tier 1:** `../core/marketing-acquisition.md` · план — `../plans/ads-autopilot.md`.
