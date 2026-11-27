import pytest

from testign import coverage_rules as cr

UPDATE = "Cart edit/Cart lines/[Update]"
QTY = "Cart edit/Cart lines/[Quantity]"
NOTE = "Cart edit/Cart lines/[Note]"
CONTROLS = [
    {"about": UPDATE, "type": "button", "action": True, "needs": [QTY, NOTE], "goes_to": "Checkout"},
    {"about": QTY, "type": "textbox", "required": True, "format": "integer", "range": {"min": 1, "max": 99}},
    {"about": NOTE, "type": "textbox", "length": {"max": 20}},
    {"about": "Cart edit/Cart lines", "type": "area"},
]


def listing(depth="standard", cases=(), skips=(), roles=()):
    return {"depth": depth, "controls": cr.check_controls(CONTROLS), "roles": list(roles), "skips": list(skips),
            "cases": [{"case": f"c{n}", **c} for n, c in enumerate(cases, start=1)]}


def required_ids(depth):
    return {(c["rule"], c["about"]) for c in cr.required(listing(depth))}


def test_each_depth_requires_more_and_keeps_the_shallower_checks():
    smoke, standard, thorough = required_ids("smoke"), required_ids("standard"), required_ids("thorough")
    assert smoke < standard < thorough
    assert ("action.normal", UPDATE) in smoke and ("action.navigate", UPDATE) in smoke
    assert ("state.empty", UPDATE) in standard - smoke and ("validation.boundary", QTY) in standard
    assert ("robustness.double", UPDATE) in thorough - standard and ("combination.pairs", UPDATE) in thorough
    rows = {(c["rule"], c["about"]): c["rows"] for c in cr.checks(listing("thorough"))}
    assert rows[("state.missing_one", UPDATE)] == 2 and rows[("state.invalid", UPDATE)] == 1
    assert rows[("validation.boundary", QTY)] == 4 and rows[("validation.boundary", NOTE)] == 2


def test_a_list_without_depth_tracks_nothing():
    old = {**listing(), "depth": None}
    assert cr.required(old) == [] and cr.view(old) is None and cr.summary(old) is None and cr.missing(old) == []


def test_covered_skipped_partial_missing_and_optional():
    data = listing("standard", cases=[
        {"rule": "state.missing_one", "about": UPDATE},
        {"rule": "action.normal", "about": UPDATE, "covers": [{"rule": "action.navigate", "about": UPDATE}]},
        {"rule": "robustness.double", "about": UPDATE},
    ], skips=[{"rule": "state.empty", "about": UPDATE, "reason": "the button is hidden until a line exists"}])
    status = {(c["rule"], c["about"]): c["status"] for c in cr.coverage(data, everything=True)}
    assert status[("action.normal", UPDATE)] == "covered" and status[("action.navigate", UPDATE)] == "covered"
    assert status[("state.empty", UPDATE)] == "skipped"
    assert status[("state.missing_one", UPDATE)] == "partial"  # needs 2 cases, has 1
    assert status[("state.invalid", UPDATE)] == "missing"
    assert status[("robustness.double", UPDATE)] == "covered"  # optional at standard but covered anyway
    assert status[("state.refill", UPDATE)] == "optional"
    view = cr.view(data)
    assert view["rows"][0]["required"] and not view["rows"][-1]["required"]
    assert view["covered"] + view["skipped"] + view["missing"] == view["required"]


def test_roles_count_only_when_more_than_one():
    assert ("role.each", UPDATE) not in required_ids("standard")
    rows = {(c["rule"], c["about"]): c["rows"] for c in cr.checks(listing("standard", roles=["staff", "admin", "guest"]))}
    assert rows[("role.each", UPDATE)] == 3


def test_problems_name_references_that_point_nowhere():
    data = listing(cases=[{"rule": "action.normal", "about": "Other/[Go]"}],
                   skips=[{"rule": "state.empty", "about": QTY, "reason": "x"}])
    data["controls"].append({"about": "X/[Send]", "type": "button", "action": True, "needs": ["X/[Missing]"]})
    found = " | ".join(cr.problems(data))
    assert "X/[Missing]" in found and "Other/[Go]" in found and "state.empty" in found


def test_shapes_are_checked():
    with pytest.raises(cr.CoverageError):
        cr.check_controls([{"about": "A", "type": "spaceship"}])
    with pytest.raises(cr.CoverageError):
        cr.check_controls([{"about": "A", "type": "button"}, {"about": " A ", "type": "button"}])
    with pytest.raises(cr.CoverageError):
        cr.check_skips([{"rule": "state.empty", "about": "A", "reason": "  "}])
    with pytest.raises(cr.CoverageError):
        cr.check_case_fields({"rule": "not.a.rule", "about": "A"})
    with pytest.raises(cr.CoverageError):
        cr.check_case_fields({"about": "A"})
    with pytest.raises(cr.CoverageError):
        cr.check_depth("deep")
    assert cr.check_case_fields({"rule": "state.empty", "about": " A / [B] "}) == {"rule": "state.empty", "about": "A/[B]"}
    assert cr.adds_checks(listing("smoke"), "standard") and not cr.adds_checks(listing("thorough"), "smoke")


def test_sheet_rows_list_every_check():
    rows = cr.sheet_rows(listing("smoke"))
    assert rows[0] == ["Test depth: smoke"] and rows[1][0] == "Group"
    assert len(rows) == 2 + len(cr.checks(listing("smoke")))
    assert cr.catalogue()[0]["id"] == "display.initial"
