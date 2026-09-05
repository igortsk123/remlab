# docs/ — исторические и инженерные документы

**Канон памяти проекта — `.memory_bank/`** (вход — `.memory_bank/INDEX.md`, снимок —
`project-state.md`, решения — `decisions.md` + тома `decisions/`). Здесь лежит то, на что банк
ссылается как на историю или Tier 2:

| Файл | Роль | Статус |
|------|------|--------|
| `tech-spec-ts-stack.md` | инженерная спека стека (Tier 2 для `core/architecture.md`) | живой ориентир; гипотезы, не аксиомы |
| `master-brief-v0.3.md` | бизнес-база v0.3 (affiliate-first freemium) | история; при конфликте wins v0.4 (ADR-0016) |
| `cjm-ux-v0.2.md` | экраны/CJM v0.2 | история |
| `market-research-ru-uk.md` | исследование рынка RU/UK | Tier 2 для `core/market.md` |
| `kb-rules-classification.{md,json}` | классификация правил Source-KB | Tier 2 для `core/knowledge-db.md` |
| `DECISIONS.md` | указатель legacy — полный ADR-лог до 02.07 | заменён `.memory_bank/decisions.md` |

Новые решения и факты сюда не писать — только в `.memory_bank/`.
