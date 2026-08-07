-- T1 truth-first (P0 аудита рефери): провенанс размеров.
-- dims_evidence: {w|d|h|len|dia: {raw, unit, source}} — из чего и как resolved каждая ось.
-- dims_source (колонка уже есть) теперь заполняется сводкой резолвера, напр. "param:2 prior-mm:1";
-- значения 'scrape'/'manual' — authority: фид их не затирает (правка рефери: recency
-- сравнивается внутри уровня доверия, а не всегда перебивает provenance).
alter table products add column if not exists dims_evidence jsonb;
