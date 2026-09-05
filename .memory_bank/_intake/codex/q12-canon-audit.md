АУДИТ БИБЛИОТЕКИ КАНОНОВ (задача владельца 19.08: «сделай аудит канонов с Codex, предложи ещё или поправь эти»).

КОНТЕКСТ. Каноны — фундамент продукта: солвер собирает интерьер из них. Модель принята в ADR-0112:
функция × якорь-возможность × форма. Библиотека рисуется теми же плейсерами, что и рабочие планы
(`tools/scout/canon_gallery.py`, 52 карточки, покрытие паспорта полное, каждая проходит боевой
validate; допустимые мягкие — явным allowlist в паспорте).

ЧАСТОТЫ ПРАКТИКИ ОТ ВЛАДЕЛЬЦА (лежат в `tools/scout/rules/practice_priors.json`, status
shadow_hypothesis): по зоне у окна — кресло/пара кресел 28%, скамья/сиденье 19%, растения 17%,
пусто 17%, стол/бюро 10%, диван 9%. Присутствие предметов в гостиной: диван 96%, столик 88%,
ковёр 84%, ТВ 78%, хранение 74%, кресло 61%, торшер 55%, растения 52%, обеденный стол 48%,
камин 22%, пуф 20%, банкетка 12%, бар/drinks trolley 7%.

ТЕКУЩИЙ СОСТАВ (zone.scheme | anchor/form | статус):
seating.default | anchor=runtime form=group_default | ok
seating.bulky | anchor=runtime form=bulky | ok
seating.facing | anchor=runtime form=armchairs_vis_a_vis | ok
seating.bridge | anchor=runtime form=diagonal_bridge | ok
seating.tandem_r | anchor=runtime form=side_pair_right | ok
seating.tandem_l | anchor=runtime form=side_pair_left | ok
seating.u | anchor=runtime form=u_shape | ok
seating.square | anchor=runtime form=three_sided_pair | ok
seating.pouf_table | anchor=runtime form=pouf_as_table | ok
seating.floating_pair | anchor=object:media_bearer form=floating_pair | ok
seating.gap_compact | anchor=runtime form=compact_table_gap | ok
seating.window_back | anchor=window form=sofa_back_to_window | ok
seating.media_parallel | anchor=runtime form=armchair_parallel_to_sofa | ok
seating.media_half | anchor=runtime form=armchair_half_turn_to_screen | ok
seating.media_bridge | anchor=runtime form=diagonal_pair_to_screen | ok
seating.L_right | anchor=runtime form=l_joint_mirrored | ok
seating.L_left | anchor=runtime form=l_joint | ok
media.media_centered | anchor=wall_segment form=centered | ok
media.media_mirror | anchor=wall_segment form=mirrored_accent | ok
media.media_at_jamb | anchor=opening form=at_jamb | ok
media.media_corner | anchor=corner form=diagonal | ok
media.media_between_windows | anchor=wall_segment form=between_windows | ok
media.media_storage_combo | anchor=wall_segment form=row_with_companions | ok
media.media_installation | anchor=wall_segment form=row_with_companions | ok
media.fireplace_side_by_side | anchor=wall_segment form=side_by_side | ok
media.tv_over_fireplace | anchor=object:fireplace form=above | SLEEPING
media.media_builtin | anchor=wall_segment form=builtin_run | SLEEPING
fireplace.storage_flanks | anchor=object:fireplace form=storage_flanks | ok
fireplace.plant_flanks | anchor=object:fireplace form=plant_flanks | ok
fireplace.solo | anchor=wall_segment form=solo | ok
dining.dining_island | anchor=free_region form=island | ok
dining.dining_against_wall | anchor=wall_segment form=edge | ok
dining.dining_round_compact | anchor=free_region form=round_compact | ok
dining.dining_foldable | anchor=unresolved form=foldable | SLEEPING
dining.dining_edge_nook | anchor=wall_segment form=edge_nook | ok
storage.storage_perimeter | anchor=wall_segment form=row | ok
storage.storage_shallow | anchor=wall_segment form=shallow | ok
storage.storage_zone_divider | anchor=zone_boundary form=divider | SLEEPING
storage.corner_tower | anchor=corner form=tower_along_wall | ok
quiet.quiet_chat | anchor=wall_segment|free_region form=pair_vis_a_vis | ok
quiet.fireplace_flank | anchor=object:fireplace form=flanking_pair | ok
reading.window_anchor | anchor=window form=single_armchair | ok
reading.bay_anchor | anchor=bay form=single_armchair | ok
reading.corner_vignette | anchor=corner form=chair_lamp_table | ok
reading.fireplace_anchor | anchor=object:fireplace form=single_armchair | ok
decor.corner_plant | anchor=corner form=plant | ok
decor.bay_plant | anchor=bay form=plant | ok
fireplace_solo.solo | anchor=wall_segment form=solo | ok
window_seat.bench_under_window | anchor=window form=straight_bench | ok
window_seat.bay_bench | anchor=bay form=straight_bench | ok
--- zone_priority.order: ['architecture', 'focus', 'seating', 'circulation', 'media', 'dining', 'seating_extra', 'storage', 'light', 'decor']
--- группы посадки: [('armchair_pair', ['default'], 'active'), ('compact_sectional', ['default', 'pouf_table'], 'active'), ('sofa_armchair', ['default', 'pouf_table', 'facing', 'media_parallel', 'media_half'], 'active'), ('sectional_armchair', ['default', 'media_parallel', 'media_half'], 'active'), ('sofa_facing_sofa', ['default'], 'active'), ('sofa_2armchairs', ['default', 'u', 'bulky', 'pouf_table', 'facing', 'bridge', 'tandem_r', 'tandem_l', 'media_bridge'], 'active'), ('sofa_loveseat', ['default', 'L_right', 'square'], 'active'), ('sofa_4armchairs', ['default', 'u', 'pouf_table'], 'shadow_alternative'), ('sofa_loveseat_2armchairs', ['default', 'L_right', 'square'], 'active'), ('two_sofas_2armchairs', ['default', 'L_right', 'square'], 'active'), ('sofa_pouf', ['default'], 'active'), ('sofa_lamp', ['default'], 'active'), ('sofa_solo', ['default'], 'active')]
--- зоны в zones.json: ['seating_media', 'circulation', 'reading', 'dining', 'storage', 'decor', 'light']

ЧТО Я УЖЕ ВИЖУ КАК ДЫРЫ (критикуй и дополняй, я мог ошибиться):
1. В `zone_priority.order` есть зона `light`, но у неё НЕТ НИ ОДНОЙ схемы — при этом торшер
   встречается в 55% гостиных.
2. Группа `sofa_facing_sofa` (два дивана визави) исполняется, но отдельной схемы-канона нет.
3. `media_wall` (стенка как носитель) существует в коде как отдельный tpl_variant, но схемы нет.
4. Бар/drinks trolley (7%) — нет ни роли, ни схемы.
5. Стол/бюро у окна (10% по частотам владельца) — нет схемы (рабочее место у окна).
6. Растения у окна (17%) — есть только decor.corner_plant / bay_plant, схемы «растения у окна» нет.
7. `entry_zone` объявлена в zones.json, схем нет.
8. Пара кресел у окна/в эркере (частота «кресло ИЛИ ПАРА кресел» 28%) — у нас только singleton.

ВОПРОСЫ:
A. Пройди по КАЖДОЙ существующей схеме и скажи: канон это или наш костыль; правильно ли назван;
   не дублирует ли соседнюю; верны ли anchor/form; чего не хватает в паспорте (провенанс, условия,
   min-состав). Отдельно отметь схемы, которые надо ОБЪЕДИНИТЬ или ПЕРЕИМЕНОВАТЬ.
B. Какие каноны НУЖНО ДОБАВИТЬ, чтобы библиотека покрывала реальную практику гостиной? Ранжируй
   по пользе (частота × выполнимость на нашем каталоге). Для каждого: функция, якорь, форма,
   min-состав, условия применимости, провенанс с источниками.
C. Что из добавляемого мы можем сделать ЧЕСТНО сейчас (есть роли в каталоге и геометрия), а что
   требует данных/новых ролей — и каких именно.
D. Открытые дефекты, которые я знаю: `square` без зеркала; `tandem_r/l` без сертификата
   недостижимости и, возможно, right-first bias каскада; порог 45° у media_parallel (кресло с
   экраном в 43° формально проходит); зеркальные варианты у окна (±30°) и сторона торшера;
   `dining_foldable` с anchor=unresolved. Что из этого важнее всего для качества интерьера?
E. Есть ли в библиотеке схемы, которые стоит УДАЛИТЬ или перевести в sleeping как неканоничные?

Файлы репозитория смотри сам. Не изменяй их. Верни: вывод; таблицу по существующим схемам;
ранжированный список новых канонов с провенансом; что честно реализуемо сейчас; риски.
