import pytest

from hi import scene3d
from hi.scene3d import SceneError, normalize, render_3d


def problems(scene):
    with pytest.raises(SceneError) as e:
        normalize(scene)
    return e.value.problems


def one(obj, **scene):
    return normalize({"objects": [obj], **scene})["objects"][0]


def test_a_surface_keeps_its_expression_range_and_colouring():
    s = one({"type": "surface", "expr": " sin(x*2 + t) * cos(y) ", "x": [-3, 3, 64], "y": [-2, 2], "colorBy": "height", "palette": "plasma"})
    assert s["expr"] == "sin(x*2 + t) * cos(y)" and s["x"] == [-3, 3, 64.0] and s["y"] == [-2, 2, 48.0]
    assert s["colorBy"] == "height" and s["palette"] == "plasma"


@pytest.mark.parametrize("bad,fragment", [
    ({"type": "surface", "expr": "sin(x", "x": [0, 1, 8], "y": [0, 1, 8]}, "ends too soon"),
    ({"type": "surface", "expr": "z + 1", "x": [0, 1, 8], "y": [0, 1, 8]}, "unknown name"),
    ({"type": "surface", "expr": "1 / 0", "x": [0, 1, 8], "y": [0, 1, 8]}, "finite"),
    ({"type": "surface", "expr": "x", "x": [1, 0, 8], "y": [0, 1, 8]}, "above min"),
    ({"type": "surface", "expr": "x", "x": [0, 1, 9999], "y": [0, 1, 8]}, None),
    ({"type": "surface", "expr": "x", "x": "wide", "y": [0, 1, 8]}, "min, max"),
    ({"type": "parametric", "fx": "u", "fy": "v", "u": [0, 1], "v": [0, 1]}, "empty"),
    ({"type": "curve", "fx": "u", "fy": "u", "fz": "x", "u": [0, 1]}, "unknown name"),
])
def test_bad_generated_shapes_are_refused(bad, fragment):
    found = problems({"objects": [bad]}) if fragment else None
    if fragment is None:
        assert one(bad)["x"][2] == scene3d.MAX_GRID  # a huge step count is clamped, not trusted
    else:
        assert fragment in " ".join(found)


def test_a_surface_that_is_too_dense_overall_is_refused():
    big = {"type": "surface", "expr": "x", "x": [0, 1, 128], "y": [0, 1, 128]}
    assert "mesh points" in " ".join(problems({"objects": [big] * 5}))


def test_parametric_and_curve_shapes():
    sphere = one({"type": "parametric", "fx": "cos(u)*sin(v)", "fy": "cos(v)", "fz": "sin(u)*sin(v)", "u": [0, 6.283, 64], "v": [0, 3.1416, 32]})
    helix = one({"type": "curve", "fx": "cos(u)", "fy": "u*0.2", "fz": "sin(u)", "u": [0, 18.85, 300], "radius": 0.04})
    assert sphere["u"][2] == 64 and helix["u"][2] == 300 and helix["radius"] == 0.04


def test_keyframe_tracks_are_sorted_checked_and_given_defaults():
    o = one({"type": "box", "animate": {"tracks": [{"property": "position", "keys": [{"t": 2, "value": [0, 2, 0]}, {"t": 0, "value": [0, 0, 0], "ease": "bounce"}]},
                                                    {"property": "color", "keys": [{"t": 0, "value": "red"}, {"t": 1, "value": "#00f"}], "loop": "pingpong"},
                                                    {"property": "opacity", "keys": [{"t": 0, "value": 0}, {"t": 1, "value": 1}]}]}})
    pos, col, op = o["animate"]["tracks"]
    assert [k["t"] for k in pos["keys"]] == [0, 2] and pos["keys"][0]["ease"] == "bounce" and pos["keys"][1]["ease"] == "easeInOut" and pos["loop"] == "loop"
    assert col["loop"] == "pingpong" and col["keys"][0]["value"] == "red" and op["keys"][1]["value"] == 1


@pytest.mark.parametrize("track,fragment", [
    ({"property": "mass", "keys": [{"t": 0, "value": 1}]}, "property"),
    ({"property": "position", "keys": []}, "keys"),
    ({"property": "position", "keys": [{"t": 0, "value": [1, 2]}]}, "3 numbers"),
    ({"property": "color", "keys": [{"t": 0, "value": "rgb(1,2,3)"}]}, "color"),
    ({"property": "position", "keys": [{"t": 0, "value": [0, 0, 0], "ease": "wobble"}]}, "ease"),
    ({"property": "position", "keys": [{"t": "soon", "value": [0, 0, 0]}]}, "number"),
])
def test_bad_tracks_are_refused(track, fragment):
    assert fragment in " ".join(problems({"objects": [{"type": "box", "animate": {"tracks": [track]}}]}))


def test_orbit_pulse_path_and_bob():
    a = one({"type": "sphere", "animate": {"bob": 0.3, "pulse": {"amount": 0.4, "speed": 3},
                                           "orbit": {"radius": 3, "speed": 1.2, "axis": "z", "phase": 1, "tilt": 20},
                                           "path": {"points": [[0, 0, 0], [1, 1, 0], [2, 0, 1]], "duration": 6, "loop": "pingpong", "orient": True}}})["animate"]
    assert a["bob"] == 0.3 and a["pulse"] == {"amount": 0.4, "speed": 3} and a["orbit"]["axis"] == "z" and a["orbit"]["tilt"] == 20
    assert a["path"]["loop"] == "pingpong" and a["path"]["orient"] and len(a["path"]["points"]) == 3
    assert "points" in " ".join(problems({"objects": [{"type": "box", "animate": {"path": {"points": [[0, 0, 0]]}}}]}))


def test_the_old_animate_shape_still_works():
    assert one({"type": "box", "animate": {"rotate": [0, 1, 0], "bob": 0.2}})["animate"]["rotate"] == [0, 1, 0]


def test_repeat_in_every_mode_and_the_instance_limit():
    ring = one({"type": "sphere", "repeat": {"mode": "ring", "count": 12, "radius": 2, "axis": "y", "faceCenter": True, "stagger": 0.1}})["repeat"]
    grid = one({"type": "box", "repeat": {"mode": "grid", "counts": [4, 1, 4], "spacing": [1.5, 1, 1.5]}})["repeat"]
    line = one({"type": "box", "repeat": {"mode": "linear", "count": 8, "step": [1, 0, 0], "rotateStep": [0, 15, 0], "scaleStep": 0.9}})["repeat"]
    assert ring["total"] == 12 and ring["radius"] == 2 and grid["total"] == 16 and grid["counts"] == [4, 1, 4] and line["total"] == 8 and line["scaleStep"] == 0.9
    assert "expanded" in " ".join(problems({"objects": [{"type": "box", "repeat": {"mode": "grid", "counts": [20, 20, 20]}}]}))
    group = {"type": "group", "repeat": {"mode": "linear", "count": 50}, "children": [{"type": "box"}] * 50}  # 50 copies of 51 objects
    assert "expanded" in " ".join(problems({"objects": [group]}))
    assert "mode" in " ".join(problems({"objects": [{"type": "box", "repeat": {"mode": "spiral"}}]}))


def test_particles_lines_labels_and_arrows():
    pts = one({"type": "points", "count": 600, "emitter": "fountain", "gravity": -3, "palette": "warm", "seed": 4})
    assert pts["count"] == 600 and pts["emitter"] == "fountain" and pts["palette"] == "warm" and pts["seed"] == 4
    assert one({"type": "points", "count": 10 ** 9})["count"] == scene3d.MAX_PARTICLES
    assert one({"type": "line", "points": [[0, 0, 0], [1, 1, 1]], "dashed": True})["dashed"]
    label = one({"type": "label", "text": "x" * 200, "size": 0.5, "background": "#000"})
    assert len(label["text"]) == 80 and label["background"] == "#000"
    assert "text" in " ".join(problems({"objects": [{"type": "label"}]}))
    assert one({"type": "arrow", "from": [0, 0, 0], "to": [1, 2, 3]})["to"] == [1, 2, 3]
    assert "emitter" in " ".join(problems({"objects": [{"type": "points", "emitter": "rocket"}]}))


def test_physical_materials_and_textures():
    m = one({"type": "sphere", "material": {"kind": "physical", "transmission": 0.9, "ior": 1.5, "clearcoat": 1, "texture": {"kind": "checker", "colors": ["#fff", "#000"], "repeat": [4, 4]}}})["material"]
    assert m["kind"] == "physical" and m["transmission"] == 0.9 and m["texture"] == {"kind": "checker", "colors": ["#fff", "#000"], "repeat": [4.0, 4.0]}
    assert one({"type": "box", "material": {"texture": "stripes"}})["material"]["texture"]["kind"] == "stripes"
    assert "texture" in " ".join(problems({"objects": [{"type": "box", "material": {"texture": "marble"}}]}))


def test_scene_level_options():
    s = normalize({"duration": 12, "loop": False, "shadows": True, "ground": {"color": "#222", "size": 20}, "fog": {"near": 3, "far": 30},
                   "environment": True, "camera": {"position": [4, 3, 5], "orbit": {"radius": 8, "height": 3, "speed": 0.2},
                                                   "tracks": [{"property": "target", "keys": [{"t": 0, "value": [0, 0, 0]}, {"t": 4, "value": [0, 2, 0]}]}]},
                   "objects": [{"type": "box"}]})
    assert s["duration"] == 12 and s["loop"] is False and s["shadows"] and s["environment"] and s["ground"] == {"color": "#222", "size": 20}
    assert s["fog"]["far"] == 30 and s["camera"]["orbit"]["radius"] == 8 and s["camera"]["tracks"][0]["property"] == "target"
    assert normalize({"objects": [{"type": "box"}], "ground": True})["ground"]["size"] == 30
    assert "property" in " ".join(problems({"camera": {"tracks": [{"property": "fov", "keys": [{"t": 0, "value": 1}]}]}, "objects": [{"type": "box"}]}))
    assert normalize({"objects": [{"type": "box"}]})["loop"] is True


def test_the_tool_accepts_a_rich_scene_and_reports_the_count(tmp_vault):
    scene = {"title": "Ripple", "shadows": True, "ground": True, "camera": {"orbit": {"radius": 7}}, "objects": [
        {"type": "surface", "expr": "sin(sqrt(x^2 + y^2) * 3 - t * 2) * 0.3", "x": [-4, 4, 80], "y": [-4, 4, 80], "colorBy": "height"},
        {"type": "sphere", "radius": 0.15, "repeat": {"mode": "ring", "count": 16, "radius": 3, "stagger": 0.1}, "animate": {"pulse": {"amount": 0.5}}}]}
    out = render_3d.invoke({"scene": scene})
    assert out.endswith(".json") and "ripple-" in out and "2 objects" in out
    assert render_3d.invoke({"scene": {"objects": [{"type": "surface", "expr": "oops(", "x": [0, 1], "y": [0, 1]}]}}).startswith("Not rendered")
