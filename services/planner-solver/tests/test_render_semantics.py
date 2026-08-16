"""P5 свода №12: подача плана — фасад словами (не градусы), пилон подписан, пуф с назначением."""
import os

SCOUT = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tools', 'scout')


def test_render_labels_are_semantic():
    src = open(os.path.join(SCOUT, 'solver_run.py'), encoding='utf-8').read()
    assert 'def _facing_word' in src and 'def _pouf_role' in src
    assert "}°\"" not in src.split('def _facing_word')[1].split('img.save')[0], \
        'голые градусы в подписи предмета (владелец №19)'
    assert 'пилон/выступ' in src, 'вырез контура должен подписываться (владелец №5)'
    # приоритет фокуса над столиком в подписи фасада посадки
    assert "'тв-тумба':0" in src and "'столик':4" in src
