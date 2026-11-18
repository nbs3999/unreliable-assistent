import pytest
from assistant.harness import repair_args, repair_lot, repair_sku
from assistant.harness.repair import repair_codes_in_text


@pytest.mark.parametrize("raw,expected", [("SKU99", "SKU-099"), ("sku-7", "SKU-007"), ("SKU-099", "SKU-099")])
def test_sku_repair(raw, expected):
    assert repair_sku(raw) == expected


@pytest.mark.parametrize("raw,expected", [("lot 44", "LOT-00044"), ("LOT-88392", "LOT-88392")])
def test_lot_repair(raw, expected):
    assert repair_lot(raw) == expected


def test_unrepairable_returns_none():
    assert repair_sku("widget") is None


def test_repair_args_records_each_change():
    fixed, repairs = repair_args({"sku": "SKU99", "lot": "lot 44", "note": "keep"})
    assert fixed == {"sku": "SKU-099", "lot": "LOT-00044", "note": "keep"}
    assert {r["field"] for r in repairs} == {"sku", "lot"}


def test_repair_codes_in_free_text():
    assert repair_codes_in_text("check SKU99 and lot 44 now") == "check SKU-099 and LOT-00044 now"
