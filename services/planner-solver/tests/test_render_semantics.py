"""Подача плана (P5 свода №12 + владелец 17.08 №2/№15/№18/№19): подпись ориентации ТОЛЬКО когда
предмет куда-то повёрнут («→ к ТВ» при ≤15°, «под N° к X» при развороте — градусы нужны для 3D/LLM);
симметричные предметы (обеденный стол, стулья, столик, хранение) — без подписи ориентации; вырез
контура подписан по смыслу (пилон/колонна внутрь vs снаружи у эркера/скоса); пуф — с назначением."""
import os

SCOUT = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tools', 'scout')


def test_render_labels_are_semantic():
    src = open(os.path.join(SCOUT, 'solver_run.py'), encoding='utf-8').read()
    assert 'def _facing_word' in src and 'def _pouf_role' in src
    body = src.split('def _facing_word')[1].split('def _pouf_role')[0]
    assert "if _base not in ('диван','кресло'):" in body and 'return None' in body, \
        'подпись ориентации — только у направленных (владелец №15/№19: стол/стул не подписывать)'
    assert '→ к' in body and 'под {int(5*round' in body, 'точный взгляд «→ к X», разворот — «под N° к X»'
    assert 'пилон/колонна' in src and "'снаружи'" in src, 'вырез контура: пилон внутрь vs снаружи у эркера (владелец №18)'
    assert "'тв-тумба':0" in src and "'столик':4" in src   # приоритет фокуса над столиком
