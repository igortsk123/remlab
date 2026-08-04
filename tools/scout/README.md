# scout — разведочные скрипты каталога Гдеслона (сессия 2026-08-01)

Не часть проекта (tools/* в .gitignore). Скопированы из /tmp-scratchpad, чтобы пережить ребут VM.
БД: docker-контейнер `remlab-devdb` (pgvector/pg17, порт 127.0.0.1:5433, user remlab/dev, db remlab,
таблицы products 87 635 строк, scrape_queue, view lr_roles). После ребута: `docker start remlab-devdb`.

- `load2.py` — фиды (ZIP YML из кабинета) → products.tsv → \copy в products. Запуск из папки с feeds/f*/
- `scraper.py` — волна 1 дозаполнения размеров tvoydom (очередь scrape_queue, идемпотентен, продолжает с места)
- `export.py` — Excel-файлы курации (файл на роль, 3 листа тиров, миниатюры; нужны python3-openpyxl, python3-pil)
- `analyze.py` — отчёт покрытия размеров по фидам (без БД)

Ссылки фидов и токен — у владельца / в `.env.local` (GDESLON_API_TOKEN).
