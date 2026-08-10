"""Predeclared identity текущего документа (fixed_project_identity спеки).

Пакеты несут source_collection_id=null (SOURCE_ID_MISSING) — raw не меняем;
derived-маппинг к этим ID разрешён ТОЛЬКО потому, что identity задан спекой
(metadata origin PROMPT_SUPPLIED). Резолюция по имени файла запрещена.
"""
from __future__ import annotations

SOURCE_DOCUMENT_ID = "RID_MITTON_NYSTUEN_2016_3E"
SOURCE_WORK_ID = "RID_MITTON_NYSTUEN_WORK"
SOURCE_INDEPENDENCE_GROUP_ID = "RID_MITTON_NYSTUEN_WORK"
METADATA_ORIGIN = "PROMPT_SUPPLIED"

PREDECLARED_BIBLIO = {
    "title": "Residential Interior Design: A Guide to Planning Spaces",
    "authors": ["Maureen Mitton", "Courtney Nystuen"],
    "edition": "Third Edition",
    "publication_year": 2016,
}

# Ожидаемая схема входных пакетов (несовместимая версия -> блок, спека 0C)
EXPECTED_PACKAGE_TYPE = "CHAPTER_KNOWLEDGE_PACKAGE"
EXPECTED_SCHEMA_VERSION = "3.2"
EXPECTED_VOCABULARY_VERSION = "1.2"
