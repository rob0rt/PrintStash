"""U1 slot discovery and physical tool validation without printer I/O."""
import pytest

from app.modules.printing.snapmaker_u1 import (
    color_hex,
    loaded_slots,
    logical_filaments,
    validate_mapping,
)


@pytest.fixture
def state():
    return {"result": {"status": {"print_task_config": {
        "filament_exist": [True, True, True, False],
        "filament_type": ["PETG", "PLA", "PLA", "PETG"],
        "filament_sub_type": ["Matte", "", "", ""],
        "filament_vendor": ["SUNLU", "Snapmaker", "", ""],
        "filament_color_rgba": ["55AA44FF", "223344FF", "AABBCCFF", "000000FF"],
    }}}}


def test_loaded_slots(state):
    slots = loaded_slots(state)
    assert len(slots) == 4
    assert slots[0] == {
        "index": 0, "present": True, "material": "PETG",
        "subtype": "Matte", "vendor": "SUNLU", "color": "#55AA44",
    }
    assert slots[-1]["present"] is False


def test_missing_presence_is_an_error():
    with pytest.raises(ValueError, match="state_unavailable"):
        loaded_slots({"result": {"status": {"print_task_config": {}}}})


def test_orca_tool_and_color_metadata():
    filaments = logical_filaments([
        "; filament_type = PETG,PLA,PETG\n",
        "; filament_colour = #55AA44,#112233,#AABBCC\n",
        "; filament_used_g = 6.9,4.2,2.5\n",
        "; T8 in a comment\n",
        "M104 T7 S220\n",
        "T2\n",
        "T0 ; switch tools\n",
    ])
    assert [f["index"] for f in filaments] == [0, 2]
    assert filaments[0]["material"] == "PETG"
    assert filaments[0]["grams"] == 6.9
    assert filaments[1]["color"] == "#AABBCC"


def test_single_tool_is_implicit():
    assert logical_filaments(["; filament_type = PLA\n", "G1 X0\n"])[0]["index"] == 0
    with pytest.raises(ValueError, match="tools_unknown"):
        logical_filaments(["; filament_type = PETG,PLA\n", "G1 X0\n"])


def test_validate_complete_distinct_loaded_mapping(state):
    filaments = [{"index": 0, "material": "PETG"}, {"index": 1, "material": "PLA"}]
    slots = loaded_slots(state)
    validate_mapping(filaments, slots, [(0, 0), (1, 1)], allow_material_mismatch=False)
    for mapping, reason in [
        ([(0, 0)], "mapping_incomplete"),
        ([(0, 0), (1, 0)], "mapping_invalid"),
        ([(0, 0), (1, 3)], "head_empty"),
        ([(0, 1), (1, 0)], "material_mismatch"),
    ]:
        with pytest.raises(ValueError, match=reason):
            validate_mapping(filaments, slots, mapping, allow_material_mismatch=False)
    validate_mapping(filaments, slots, [(0, 1), (1, 0)], allow_material_mismatch=True)


def test_color_validation():
    assert color_hex("#ffeeccff") == "#FFEECC"
    assert color_hex("invalid") is None
