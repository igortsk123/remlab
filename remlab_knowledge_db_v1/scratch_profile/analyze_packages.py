#!/usr/bin/env python3
"""Analysis of 13 CHAPTER_KNOWLEDGE_PACKAGE v3.2 JSONs: review queue, exclusions,
coverage audit, needs_verification, chapter_summary recount."""
import json, glob, os, re, collections

SRC = '/home/pakar/igor/remlab/remlab_knowledge_db_v1/sources/RID_MITTON_NYSTUEN_2016_3E/*.json'
files = sorted(glob.glob(SRC), key=lambda f: (
    int(re.search(r'ch(\d+)', f).group(1)), f))

# ---------- ordered keyword rules for review-queue clustering ----------
RULES = [
    ('A. Идентичность пакета (source_id/библиография/маппинг страниц/сегменты)',
     ['source_collection_id', 'bibliographic', 'master page mapping', 'source_page_master_file',
      'master pdf file name', 'source_file_name', 'segment index and segment total',
      'segment, not a complete chapter', 'only the closing part', 'input is a partial chapter',
      'input is a segment', 'references list', 'segment metadata']),
    ('B. Метрика/империал не сходятся (ошибки конвертации в книге)',
     ['metric equival', 'metric value', 'metric equivalents', 'imperial and metric',
      'imperial/metric', 'printed as', 'prints', 'converts to', 'conversion', 'factor-of-ten',
      'factor of ten', 'unit error', 'unit conflict', 'do not convert', 'does not match its imperial',
      'off by roughly a factor', 'metric range', 'metric conversion', 'not equivalent']),
    ('C. Значение отсутствует/отложено в другой раздел или главу',
     ['outside this input', 'not part of this input', 'outside this segment', 'not in this input',
      'no value', 'without giving a dimension', 'no numeric', 'not quantified', 'no dimension',
      'gives no value', 'gives no numeric', 'no distance value', 'not given', 'never given',
      'deferred', 'defers', 'no value given', 'no slope value', 'no load value',
      'without any opening dimensions', 'without reproducing any values', 'delegated to',
      'no counter height', 'no cavity depth', 'no door width', 'not dimensioned',
      'carries no dimensions', 'no absolute illuminance', 'never quantified', 'with no offset',
      'with no angle value', 'not shown in the figure', 'numbers appear elsewhere',
      'no matching answer', 'no dimensional answer', 'only the question is available',
      'unquantified', 'without stating any numeric', 'no numeric value']),
    ('D. Чтение чертежей/рисунков (нечитаемо, неразмечено, интерпретация)',
     ['read from the drawing', 'read from a drawn', 'read from drawn', 'unlabelled', 'not labelled',
      'legib', 'hand-lettered', 'rasteris', 'could not be read', 'could not be assigned',
      'read visually', 'axis assignment', 'inferred from position', 'inferred from drawing',
      'interpretation of an unlabelled', 'not reliably', 'endpoints', 'endpoint',
      'could not be identified', 'sum-checked', 'do not sum', 'dimension chain',
      'reading of', 'read from rendered', 'read from annotations', 'read from the figure',
      'figure annotation with no supporting text', 'annotation next to', 'whose subject',
      'not stated in figure', 'drawn but not described', 'read at limited resolution',
      'legend letter', 'label']),
    ('E. Внутренние конфликты значений в источнике (двойные значения)',
     ['conflict', 'contradiction', 'contradicts', 'diverges', 'both preserved', 'both are retained',
      'not averaged', 'differs from', 'two different metric', 'three different', 'claimed by both',
      'divergence', 'does not reconcile', 'does not match the ratio', 'does not match the number',
      'stated as varying', 'disagree']),
    ('F. Качественные/размытые формулировки источника',
     ['qualitative', 'qualitatively', "'small' versus 'large'", 'similar dimensions',
      'rough', 'roughly eye level', 'few feet', 'vary by locality', 'varies', 'vary greatly',
      'varying greatly', 'author examples', 'not decision thresholds', 'relative comparison',
      'no threshold ratio', 'indicative bands', 'alludes to']),
    ('G. Вывод/инференс экстрактора (не утверждение источника)',
     ['derived', 'inference', 'computed by the extractor', 'inferred from two examples',
      'is derived']),
    ('H. Цитируемые стандарты/коды (редакция, актуальность, применимость)',
     ['cited standard', 'irc citations', 'edition', 'currency', 'adoption must be checked',
     'undated', 'per jurisdiction', 'without naming a code', 'does not cite']),
]

def classify(reason):
    low = reason.lower()
    for name, kws in RULES:
        for kw in kws:
            if kw in low:
                return name
    return 'Z. Прочее'

review_rows = []          # (file_tag, record_id, reason, theme)
for f in files:
    d = json.load(open(f))
    tag = os.path.basename(f).replace('remlab_SOURCE_ID_MISSING_', '').replace('.json', '')
    for q in d['chapter_review_queue']:
        review_rows.append((tag, q.get('record_id'), q['reason'], classify(q['reason'])))

theme_counter = collections.Counter(t for *_, t in review_rows)
none_count = sum(1 for _, rid, *_ in review_rows if rid is None)

print('== 1. CHAPTER_REVIEW_QUEUE ==')
print(f'total={len(review_rows)}  record_id=None (пакетные)={none_count}  привязанные к records={len(review_rows)-none_count}')
for theme, cnt in sorted(theme_counter.items()):
    n_none = sum(1 for _, rid, _, t in review_rows if t == theme and rid is None)
    exs = [f'{tag}/{rid or "PKG"}: {r[:90]}' for tag, rid, r, t in review_rows if t == theme][:2]
    print(f'  {theme}: {cnt} (из них пакетных {n_none})')
    for e in exs:
        print(f'     ex: {e}')

# where do the None items concentrate
none_by_file = collections.Counter(tag for tag, rid, *_ in review_rows if rid is None)
print('  None-позиции по файлам:', dict(none_by_file))

# ---------- 2. excluded_source_items ----------
print('\n== 2. EXCLUDED_SOURCE_ITEMS ==')
excl_rows = []
for f in files:
    d = json.load(open(f))
    tag = os.path.basename(f).replace('remlab_SOURCE_ID_MISSING_', '').replace('.json', '')
    for x in d['excluded_source_items']:
        excl_rows.append((tag, x['exclusion_reason'], x.get('evidence_locator', ''), x.get('notes', '')))
print('total =', len(excl_rows))
er = collections.Counter(r for _, r, *_ in excl_rows)
for reason, cnt in er.most_common():
    print(f'  {reason}: {cnt}')

TOPIC_RULES = [
    ('история/эволюция жилья', ['histor', 'evolution', '1900', 'colonial', 'era', 'past', 'trend']),
    ('устойчивость/экология', ['sustainab', 'green', 'leed', 'energy', 'environment', 'recycl', 'renewable']),
    ('материалы/отделка (качественно)', ['material', 'finish', 'surface', 'wood species', 'tile', 'countertop material', 'flooring']),
    ('процесс проектирования/бизнес', ['design process', 'client', 'budget', 'cost', 'business', 'career', 'profession', 'contractor', 'project management', 'resale', 'roi']),
    ('свет/электрика (качественно)', ['light', 'lamp', 'lumen', 'electrical', 'wiring']),
    ('психология/социология', ['proxemic', 'psycholog', 'privacy', 'territorial', 'behavior', 'social']),
    ('графика/чертёжные конвенции', ['drawing convention', 'drafting', 'symbol', 'sheet', 'annotation', 'graphic', 'lettering', 'title block']),
    ('сантехника/инженерка (качественно)', ['plumbing', 'hvac', 'mechanical', 'duct', 'water heater', 'venting']),
    ('библиография/оргтекст', ['reference', 'bibliograph', 'glossary', 'exercise', 'summary', 'review question', 'learning objective', 'introduction']),
]
def topic(loc, notes):
    low = (loc + ' ' + notes).lower()
    for name, kws in TOPIC_RULES:
        for kw in kws:
            if kw in low:
                return name
    return 'другое'
tc = collections.Counter(topic(l, n) for _, _, l, n in excl_rows)
print(' темы исключённого:')
for t, c in tc.most_common():
    print(f'  {t}: {c}')
print(' примеры "другое":')
for _, r, l, n in excl_rows:
    if topic(l, n) == 'другое':
        print('   -', r, '|', l[:100])

# ---------- 3. coverage_audit ----------
print('\n== 3. COVERAGE_AUDIT ==')
for f in files:
    d = json.load(open(f))
    tag = os.path.basename(f).replace('remlab_SOURCE_ID_MISSING_', '').replace('.json', '')
    ca = d['coverage_audit']
    found = ca['relevant_source_items_found']
    mapped = ca['relevant_source_items_mapped_to_records']
    excl = ca['relevant_source_items_excluded']
    mismatch = '' if found == mapped + excl else f'  <-- MISMATCH found({found}) != mapped({mapped})+excl({excl})'
    flag = '' if ca['coverage_complete'] else '  ** coverage_complete=FALSE **'
    print(f'{tag}: pages {ca["page_count_processed"]}/{ca["page_count_provided"]}, found={found}, mapped={mapped}, excluded={excl}{mismatch}{flag}')
    if ca['unreadable_or_ambiguous_pages']:
        print(f'   unreadable/ambiguous: {ca["unreadable_or_ambiguous_pages"]}')
    if ca['unprocessed_pages']:
        print(f'   unprocessed: {ca["unprocessed_pages"]}')
    if not ca['coverage_complete']:
        print(f'   notes: {ca["notes"]}')

# ---------- 4. needs_verification at record level ----------
print('\n== 4. NEEDS_VERIFICATION (records) ==')
VRULES = [
    ('метрика/империал не сходятся', ['metric', 'conversion', 'convert', 'mm', 'imperial', 'equivalent']),
    ('чтение чертежа/нечитаемость/неразмеченные размеры', ['figure', 'drawing', 'drawn', 'unlabel', 'legib', 'read', 'axis', 'endpoint', 'arrow', 'annotation', 'sketch', 'rasteris', 'resolution']),
    ('значение отсутствует/отложено', ['not given', 'no value', 'no numeric', 'outside this', 'defer', 'not part of this input', 'not quantified', 'without', 'unstated', 'gives no', 'not stated', 'never given', 'delegated', 'elsewhere']),
    ('внутренний конфликт значений', ['conflict', 'contradic', 'differs', 'diverg', 'inconsist', 'does not match', 'two different', 'disagree', 'versus']),
    ('вывод экстрактора/инференс', ['derived', 'inference', 'inferred', 'computed']),
    ('цит. стандарты/редакции кодов', ['cited', 'edition', 'irc', 'ansi', 'standard', 'currency', 'jurisdiction', 'code']),
]
def vclass(reason):
    low = reason.lower()
    for name, kws in VRULES:
        for kw in kws:
            if kw in low:
                return name
    return 'прочее'
nv_total = 0; rec_total = 0
vthemes = collections.Counter(); vexamples = collections.defaultdict(list)
ctx_nv = 0
for f in files:
    d = json.load(open(f))
    tag = os.path.basename(f).replace('remlab_SOURCE_ID_MISSING_', '').replace('.json', '')
    for r in d['records']:
        rec_total += 1
        if r.get('needs_verification'):
            nv_total += 1
            th = vclass(r.get('verification_reason', ''))
            vthemes[th] += 1
            if len(vexamples[th]) < 2:
                vexamples[th].append(f'{tag}/{r["record_id"]}: {r.get("verification_reason","")[:90]}')
        for c in r.get('applicability_contexts', []):
            if c.get('needs_verification'):
                ctx_nv += 1
print(f'records total={rec_total}, needs_verification=True: {nv_total} ({nv_total/rec_total*100:.1f}%); contexts with nv={ctx_nv}')
for th, c in vthemes.most_common():
    print(f'  {th}: {c}')
    for e in vexamples[th]:
        print(f'     ex: {e}')

# ---------- 5. chapter_summary vs recount ----------
print('\n== 5. CHAPTER_SUMMARY vs RECOUNT ==')
COLS = ['operational', 'semantic', 'hard_candidate', 'soft_candidate', 'semantic_candidate',
        'reference_only', 'needs_verification', 'local_duplicate', 'local_conflict']
hdr = 'file | recs | ' + ' | '.join(COLS) + ' | cov | mismatches'
print(hdr)
grand = collections.Counter(); grand_sum = collections.Counter()
for f in files:
    d = json.load(open(f))
    tag = os.path.basename(f).replace('remlab_SOURCE_ID_MISSING_', '').replace('.json', '')
    s = d['chapter_summary']
    recs = d['records']
    actual = {
        'operational': sum(1 for r in recs if r['knowledge_type'] == 'OPERATIONAL'),
        'semantic': sum(1 for r in recs if r['knowledge_type'] == 'SEMANTIC'),
        'hard_candidate': sum(1 for r in recs if r['remlab_candidate_use'] == 'HARD_CANDIDATE'),
        'soft_candidate': sum(1 for r in recs if r['remlab_candidate_use'] == 'SOFT_CANDIDATE'),
        'semantic_candidate': sum(1 for r in recs if r['remlab_candidate_use'] == 'SEMANTIC_CANDIDATE'),
        'reference_only': sum(1 for r in recs if r['remlab_candidate_use'] == 'REFERENCE_ONLY'),
        'needs_verification': sum(1 for r in recs if r.get('needs_verification')),
        'local_duplicate': sum(1 for r in recs if r.get('local_duplicate_of')),
        'local_conflict': sum(1 for r in recs if r.get('local_conflicts_with')),
    }
    mism = []
    cells = []
    for c in COLS:
        dec = s[f'{c}_count']
        act = actual[c]
        grand[c] += act; grand_sum[c] += dec
        cells.append(f'{dec}' if dec == act else f'{dec}(act:{act})')
        if dec != act:
            mism.append(f'{c}: summary={dec} actual={act}')
    cov = 'T' if s['coverage_complete'] else 'F'
    print(f'{tag} | {len(recs)} | ' + ' | '.join(cells) + f' | {cov} | ' + ('; '.join(mism) if mism else 'OK'))
print('TOTAL actual:', dict(grand))
print('TOTAL summary:', dict(grand_sum))

# other knowledge_type / candidate_use values, sanity
kt = collections.Counter(); cu = collections.Counter()
for f in files:
    d = json.load(open(f))
    for r in d['records']:
        kt[r['knowledge_type']] += 1
        cu[r['remlab_candidate_use']] += 1
print('knowledge_type dist:', dict(kt))
print('candidate_use dist:', dict(cu))
