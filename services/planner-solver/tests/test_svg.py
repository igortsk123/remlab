from planner.svg import render
from planner.validate import validate
from tests.rooms import all_rooms, manual_layout


def test_svg_renders_room_items_and_verdict(tmp_path):
    room = all_rooms()[2]
    layout = validate(room, manual_layout(room))
    svg = render(layout, str(tmp_path / "plan.svg"))
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    for role in ("диван", "тв-тумба", "столик"):
        assert f">{role}</text>" in svg
    assert "нарушений нет" in svg
    assert (tmp_path / "plan.svg").exists()


def test_svg_lists_violations():
    room = all_rooms()[0]
    ps = manual_layout(room)
    ps[1] = ps[1].model_copy(update={"y": ps[0].y - 60})
    svg = render(validate(room, ps))
    assert "SOFA_TV_DIST" in svg
