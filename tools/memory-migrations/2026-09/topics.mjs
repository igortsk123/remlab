// Темы, словари и эвристика классификации.
export const TOPICS = {
  mesh: { file: 'mesh-salad-pool.md', slug: 'lessons-mesh-salad-pool', title: 'Меши, Salad, пул нод', scope: 'Уроки: меши (Hunyuan, DINOv2), ориентация и цвет мешей, пул нод Salad, приёмник, сторож денег — читать перед планом по этой теме' },
  catalog: { file: 'catalog-stock.md', slug: 'lessons-catalog-stock', title: 'Каталог, фиды, наличие, размеры', scope: 'Уроки: каталог — фиды, Гдеслон, наличие, размеры, вырезка фона, обогащение, сборка сетов — читать перед планом по этой теме' },
  layout: { file: 'layout-solver.md', slug: 'lessons-layout-solver', title: 'Расстановка: зоны, солвер, шаблоны, экзамен', scope: 'Уроки: расстановка — зоны, солвер, шаблоны, каноны, экзамен, рефери, правила гостиной — читать перед планом по этой теме' },
  viz: { file: 'viz-render.md', slug: 'lessons-viz-render', title: 'Визуализация: depth, fal, панорамы, маски, кадр', scope: 'Уроки: визуализация — depth, fal, панорамы, маски, генерация кадра — читать перед планом по этой теме' },
  demo: { file: 'demo-planner.md', slug: 'lessons-demo-planner', title: 'Демо-планировщик, кадры демо, витрина/конструктор', scope: 'Уроки: демо-планировщик — кадры демо, витрина, конструктор, одностраничный html — читать перед планом по этой теме' },
  devops: { file: 'devops-deploy.md', slug: 'lessons-devops-deploy', title: 'DevOps: docker, exit-fi, деплой, CI, хуки, инструменты', scope: 'Уроки: devops — docker/buildkit, exit-fi, gitignore, деплой, CI, хуки, инструменты dev-машины — читать перед планом по этой теме' },
  memory: { file: 'memory-process.md', slug: 'lessons-memory-process', title: 'Память, процесс, работа с владельцем', scope: 'Уроки: банк памяти, блокнот, Codex, работа с владельцем, дисциплина процесса — читать перед планом по этой теме' },
  estimate: { file: 'estimate-ads-leads.md', slug: 'lessons-estimate-ads-leads', title: 'Смета, калькуляторы, Директ, лиды (+ source-KB)', scope: 'Уроки: смета, калькуляторы, Директ, лиды; source-KB — читать перед планом по этой теме' },
};
export const TOPIC_ORDER = ['mesh', 'catalog', 'layout', 'viz', 'demo', 'devops', 'memory', 'estimate'];

// Словарь по тексту (×1 за каждый сработавший ключ)
export const DICT = {
  mesh: [/salad/i, /hunyuan/i, /dinov2/i, /\bмеш(а|у|е|и|ей|ам|ами|ах|ом)?\b/i, /\bmesh/i, /\bнод(а|ы|у|е|ой|ах|ами|ам)?\b/i, /\bпул(а|у|е|ом)?\b/i, /\bglb\b/i, /trimesh/i, /ориентац/i, /приёмник|receiver/i, /сторож денег/i, /прогрев/i, /\bgpu/i, /тариф/i, /container_group|autostart|storage_amount|реплик/i, /ssh_run|cull_slow|warm/i, /mesh_ready|mesh_status|MESH_/, /покраск|альбедо|текстур/i, /cabinet_front/i, /earlyoom|journalctl/i, /\bобраз(а|у|ом|е)?\b/i, /квот/i, /машин(а|ы|у|е)\b/i, /генератор(а|у)? 3d|генератор(у|а)? меш/i, /закачк|докач/i, /зомби/i, /batch_show|apply_repairs|repair/i, /\bсет(ов|ы)? (мешам|с мешом)/i],
  catalog: [/фид/i, /гдеслон|gdeslon/i, /налич/i, /in_stock|sold-out|\boos\b/i, /health\b|linkcheck|page_alive|img_alive|_probe|проб(а|у|ой)\b/i, /карточк/i, /категори|таксоном|category_map|feed_taxonomy/i, /cat_role|роль товара|роли товар/i, /габарит|dim_resolver|\bdims?\b/i, /вырезк|birefnet|rmbg|bria|matting|mask_bench|hybrid_mask|components\.py|collage\.py/i, /обогащ|enrich|desc_quality|style_score|style-|style_rules|style-matrix/i, /\bclip\b|phash/i, /batch api|батч/i, /tvoydom|divan\.ru|mnogomebeli|nonton|gipfel/i, /\bheal\b|лечени/i, /sets3|compose2?|композитор/i, /каталог/i, /\bsku\b/i, /товар/i, /магазин/i, /подтип|пуф/i, /стил(ь|я|и|ей|ем)\b/i, /описани/i, /фото товар|фото тов/i, /photo_fit|photo_assessment|set_identity|set_id|set_changes/i, /цен(а|ы|е)\b/i, /ссылк/i, /цдн|cdn/i],
  layout: [/\bзон/i, /солвер|solver/i, /\bbeam\b|\bdfs\b/i, /шаблон|template|tpl_/i, /канон/i, /экзамен|acceptance/i, /рефери|referee/i, /occupancy|zones\.json|composition\.json/i, /validate|валидатор|\bhard\b/i, /ARMCHAIR|CHAIR_ORPHAN|ACCESS_BLOCKED|WINDOW_BLOCKED|SCREEN_OVER|NOT_AT_WALL|MEDIA_MISSING|QUIET_DIAG|ZDBG|LEVEL-A|LAYER_STRENGTHS/, /лестниц|ступен/i, /посадочн|seating|sofa_|console_behind|media_wall|edge_nook/i, /фаззер|fuzz/i, /seat_axis|_axis_|axis_contract/i, /residual|cohesion/i, /dining|столов(ая|ой|ую)|обеденн/i, /\bmedia\b|медиа|камин/i, /раскладк|расстановк|планировк/i, /планнер|planner/i, /маршрут|проход(имост)?/i, /носител/i, /якор/i, /гостин/i, /движ(ок|ка|ки|ке|ком)/i, /\bсцен(а|ы|у|е)?\b/i, /правил(о|а)\b/i, /геометри/i, /бэнд|band/i, /порог/i, /кресл/i, /щел/i, /контур/i, /solver_run|acceptance_run|solver_check|render_plan/i, /гейт/i, /baseline|a\/b/i],
  viz: [/depth|глубин/i, /\bfal\b|fal-ai|fal\./i, /панорам/i, /маск(а|и|у|е|ой|ам|ами)?\b/i, /генерац/i, /кадр/i, /gpt-image|sdxl|controlnet|esrgan|nano-banana|images\/edits|openai/i, /\bclay\b/i, /вклей/i, /коллаж/i, /легенд/i, /промпт/i, /камер/i, /объектив|\bfov/i, /viz_|scene_check|scene_build|scene_report|pano_views|process_report|steps\.py|measure_angle|scene\.py/i, /финальн(ый|ого|ом) проход/i, /эталон/i, /разметк|set-of-mark/i, /инпейнт/i, /\bvlm/i, /billboard|стояч(ая|ие|ей) вырезк/i, /аппликац/i, /реализм|фотореализ/i, /вид сверху|ортограф/i, /референс/i, /safety/i, /\bseed\b|зерно/i, /плитк|\bшов|шва\b/i, /апскейл/i, /clay-рендер|рендер/i, /модель (рисует|ставит|переставля|достраива|копирует|перестраивала)/i, /проём|окн(о|а)\b/i, /след(а|ом)? (на полу|предмета)/i, /\bплан(а|у|ом)?\b/i, /вид(а|ов|ы)?\b/i, /мыло|резк/i, /свет/i],
  demo: [/демо|demo/i, /draft_render|draft_service|flat215/i, /конструктор/i, /витрин/i, /галере/i, /одностраничн|\bhtml\b|\bcss\b|селектор/i, /playwright|скриншот/i, /черновик|эскиз|s3_lite/i, /topview|топ-вью|топвью/i, /крапин|заплатк/i, /pydantic/i, /consBack|окно (кадра|подбора)/i, /revision\(\)/, /кнопк/i, /мобильн/i, /лист(а|у)? (подбора|генерац)/i, /упрощ|fast_simplification|preserve_border/i, /черновой|эскизн/i, /cams_from_request|scene_from_request/i, /monkeypatch|np\.save/i, /спрайт|publish_demo/i],
  devops: [/docker|buildkit|dockerfile|builder prune/i, /exit-fi/i, /gitignore/i, /деплой|deploy/i, /\bci\b|github|workflow_run/i, /\bхук|\bhook/i, /\bgit\b/i, /pnpm|\blint|typecheck|next start|standalone/i, /caddy/i, /iptables|input drop/i, /\bscp\b|rsync/i, /smoke|:prev/i, /dev-vm|pakardev/i, /\bpip\b|venv|pep 668/i, /\/tmp|tmpfs/i, /pkill|pgrep|nohup|run_in_background|kill -0|\bpid\b/i, /edquot|квота фс/i, /psql|on_error_stop/i, /heredoc|edit-инструмент/i, /str\.replace|py_compile|pyflakes|argv|argparse/i, /\bcron|крон/i, /flock|замк(а|ом|у)?\b|exam\.lock/i, /харнесс|\bbash\b|оболочк/i, /миграци|db_migrate|\.sql/i, /контейнер/i, /сборк/i, /сервер/i, /bind-монт|inode|sed -i/i, /\bпин(ы|ов)?\b|requirements|pypi/i, /vercel/i, /open\(f/, /\bimport\b|импорт/i, /скрипт/i, /процесс/i, /\bpatch\b|патч/i, /\bssh\b/i, /worktree|коммит|commit/i, /e2e/i, /тест(а|ы|ов|е)?\b/i, /diff|дифф/i],
  memory: [/памят|\bбанк(а|е)?\b|блокнот|memory-check|session-scratch|канон-файл/i, /codex/i, /владел/i, /дисциплин/i, /гипотез/i, /спраш|уточня/i, /требование владельца|правило владельца|решение владельца/i, /пересылать/i, /урок(а|у|ом)? \d+|повтор урока/i, /сухой прогон|dry-run/i, /access-inventory|реестр интеграций/i, /масштабируем/i, /самопроверк/i, /каять|приписа/i, /сессии|сессия/i, /разрешени/i, /совет/i, /план(е|а)? (записал|и закрыл)/i, /совет|рекоменд/i, /оценк/i, /обещани/i, /вывод/i, /проверк/i],
  estimate: [/смет/i, /калькулятор/i, /директ/i, /\bлид/i, /рулон|за м²|за упак|единиц/i, /аналитик/i, /монетизац/i, /партнёрк|реф-|erid|gsaid|\bклик/i, /yookassa/i, /дефолт/i, /удаление функциональности/i, /e2e|локатор|getbyrole/i, /tooltip|\brac\b|hint-popover|@layer|утилити|media-query|text-white|препролёт/i, /ozon|\bwb\b|анблокер/i, /ии-фолбэк/i, /source-kb|recall|экстрактор|судь(я|ёй)|terra|\bseed\b|value_type|INFERRED|REVIEW_JUDGE/i, /юзер/i, /ui-мелоч/i],
};

// ADR → тема (×2)
const ADR_TOPIC = [
  [[27, 34, 35, 36, 37], 'estimate'],
  [[42, 50, 51, 76, 83, 97, 99, 102, 103, 104, 105, 106, 112, 113, 114, 115, 116, 117, 118, 119, 120, 122], 'layout'],
  [[55], 'devops'], [[57, 58, 60, 62, 63, 64], 'viz'], [[65, 73, 121, 141, 144, 147, 171, 172], 'catalog'],
  [[132, 135, 137, 142, 143, 145, 146, 152, 153, 154, 157, 160, 168, 170, 173, 174, 175, 176, 178], 'mesh'],
  [[139, 150, 179], 'devops'], [[140, 164, 165, 166, 167, 183, 184], 'demo'],
];
// Тема секции (×3) по подстроке заголовка
const SECTION_TOPIC = [
  ['source-KB', 'estimate'], ['Уроки 200–225', 'layout'], ['Уроки 226–234', 'layout'], ['Уроки 278–282', 'layout'],
  ['Ситуационные каноны', 'layout'], ['Уроки 283–287', 'layout'], ['Уроки 288–291', 'layout'], ['Уроки 292–296', 'layout'],
  ['перенос из core/lessons.md 26.08', 'layout'], ['вырезка фона', 'catalog'], ['Уроки 308–312', 'mesh'],
  ['пул Salad и границы', 'mesh'], ['Уроки 369–371', 'demo'], ['логи и молчаливые пропуски', 'mesh'], ['Уроки 374–377', 'demo'],
  ['щели в мешах', 'demo'], ['Уроки 382–384', 'mesh'], ['Уроки 385–386', 'mesh'], ['пул мешей', 'mesh'], ['работа над ошибками пула', 'mesh'],
  ['тарифы, автостарт', 'mesh'],
];

export function score(rec) {
  const s = Object.fromEntries(TOPIC_ORDER.map(t => [t, 0]));
  for (const [sub, t] of SECTION_TOPIC) if (rec.section.includes(sub)) s[t] += 3;
  for (const m of rec.text.matchAll(/ADR-(\d{4})/g)) {
    const n = Number(m[1]);
    for (const [ids, t] of ADR_TOPIC) if (ids.includes(n)) s[t] += 2;
  }
  for (const t of TOPIC_ORDER) for (const re of DICT[t]) if (re.test(rec.text)) s[t] += 1;
  const sorted = TOPIC_ORDER.map(t => [t, s[t]]).sort((a, b) => b[1] - a[1]);
  return { scores: s, top: sorted[0][0], second: sorted[1][0], margin: sorted[0][1] - sorted[1][1] };
}
