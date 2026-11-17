import json

import pytest
from starlette.testclient import TestClient

from hi import scene3d, toolkit
from hi.scene3d import SceneError, normalize, render_3d
from hi.server.app import create_app

SNOWMAN = {"title": "Snowman", "objects": [
    {"type": "sphere", "radius": 0.6, "color": "white"},
    {"type": "sphere", "radius": 0.4, "position": [0, 0.8, 0], "color": "#ffffff"},
    {"type": "cone", "radius": 0.06, "height": 0.3, "position": [0, 0.8, 0.4], "rotation": [90, 0, 0], "color": "orange"},
]}


def problems(scene):
    with pytest.raises(SceneError) as e:
        normalize(scene)
    return e.value.problems


def test_a_scene_is_filled_in_with_defaults():
    out = normalize({"objects": [{"type": "box"}]})
    (box,) = out["objects"]
    assert box["size"] == [1, 1, 1] and box["position"] == [0, 0, 0] and box["scale"] == [1, 1, 1]
    assert box["material"] == {"kind": "standard"} and out["grid"] is True and out["axes"] is False and out["title"] == "3D scene"


def test_a_json_string_is_accepted():
    assert normalize(json.dumps(SNOWMAN))["title"] == "Snowman"


def test_numbers_are_clamped_not_trusted():
    (s,) = normalize({"objects": [{"type": "sphere", "radius": 1e12, "position": [1e9, 0, 0], "scale": 5}]})["objects"]
    assert s["radius"] == scene3d.COORD_LIMIT and s["position"][0] == scene3d.COORD_LIMIT and s["scale"] == [5, 5, 5]


def test_every_problem_is_listed_so_the_model_can_fix_them_in_one_go():
    found = problems({"objects": [{"type": "dragon"}, {"type": "box", "size": [1, 2]}, {"type": "sphere", "color": "rgb(1,2,3)"}, "x"]})
    text = " ".join(found)
    assert len(found) == 4 and "dragon" in text and "size" in text and "color" in text and "each object must be an object" in text


@pytest.mark.parametrize("bad", [
    {"objects": []}, {"objects": "box"}, {}, [], 5, "not json",
    {"objects": [{"type": "sphere", "radius": float("nan")}]},
    {"objects": [{"type": "sphere", "radius": True}]},
    {"objects": [{"type": "sphere", "radius": "big"}]},
    {"objects": [{"type": "box", "material": {"kind": "glass"}}]},
    {"objects": [{"type": "box", "color": "<script>"}]},
    {"objects": [{"type": "box"}], "lights": [{"type": "laser"}]},
])
def test_malformed_scenes_are_refused(bad):
    assert problems(bad)


def test_limits_on_object_count_nesting_and_size():
    assert "objects" in " ".join(problems({"objects": [{"type": "box"}] * (scene3d.MAX_OBJECTS + 1)}))
    deep = {"type": "box"}
    for _ in range(scene3d.MAX_DEPTH + 2):
        deep = {"type": "group", "children": [deep]}
    assert "nested" in " ".join(problems({"objects": [deep]}))
    big = {"type": "mesh", "vertices": [[0, 0, 0]] * (scene3d.MAX_VERTICES + 1), "faces": [[0, 0, 0]]}
    assert "mesh points" in " ".join(problems({"objects": [big]}))


def test_a_mesh_must_index_real_vertices():
    ok = normalize({"objects": [{"type": "mesh", "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "faces": [[0, 1, 2]]}]})
    assert ok["objects"][0]["faces"] == [[0, 1, 2]]
    assert "faces[0]" in " ".join(problems({"objects": [{"type": "mesh", "vertices": [[0, 0, 0]] * 3, "faces": [[0, 1, 3]]}]}))


def test_groups_lathe_and_extrude():
    out = normalize({"objects": [
        {"type": "group", "position": [1, 0, 0], "children": [{"type": "box"}, {"type": "torus"}]},
        {"type": "lathe", "points": [[0.1, 0], [0.5, 0.5], [0.2, 1]]},
        {"type": "extrude", "shape": [[0, 0], [1, 0], [0, 1]], "depth": 0.2},
    ]})
    assert [o["type"] for o in out["objects"]] == ["group", "lathe", "extrude"] and len(out["objects"][0]["children"]) == 2
    assert "points" in " ".join(problems({"objects": [{"type": "lathe", "points": [[1, 1]]}]}))


def test_unknown_fields_are_dropped_so_nothing_extra_reaches_the_viewer():
    (box,) = normalize({"objects": [{"type": "box", "onclick": "alert(1)", "__proto__": {"x": 1}}], "script": "x"})["objects"]
    assert "onclick" not in box and "__proto__" not in box


def test_the_tool_saves_a_scene_and_returns_its_path(tmp_vault):
    out = render_3d.invoke({"scene": SNOWMAN})
    path = out.rsplit(": ", 1)[1]
    assert path.startswith("/scenes/snowman-") and "3 objects" in out and "do not embed" in out
    saved = json.loads((tmp_vault / "hi" / "scenes" / path.split("/")[-1]).read_text())
    assert saved["objects"][0]["type"] == "sphere"


def test_the_tool_says_what_to_fix(tmp_vault):
    out = render_3d.invoke({"scene": {"objects": [{"type": "dragon"}]}})
    assert out.startswith("Not rendered") and "dragon" in out and not (tmp_vault / "hi" / "scenes").exists()


def test_the_tool_takes_a_title_and_a_string_scene(tmp_vault):
    out = render_3d.invoke({"scene": json.dumps({"objects": [{"type": "box"}]}), "title": "My box"})
    assert "/scenes/" in out
    assert "/scenes/my-box-" in render_3d.invoke({"scene": {"objects": [{"type": "box"}]}, "title": "My box"})


def test_scenes_are_served_and_only_by_a_safe_name(tmp_vault):
    client = TestClient(create_app())
    path = render_3d.invoke({"scene": SNOWMAN}).rsplit(": ", 1)[1]
    r = client.get(path)
    assert r.status_code == 200 and r.json()["title"] == "Snowman" and r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/scenes/nope.json").status_code == 404
    assert client.get("/scenes/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert client.get("/scenes/x.html").status_code == 404


def test_the_tool_is_offered_to_term_and_matches_3d_requests():
    import re

    from hi.agents.term import term

    assert "render_3d" in {t.name for t in term.TOOLS} and "render3d" in term.TERM_GROUPS
    group = next(g for g in toolkit.GROUPS if g.name == "render3d")
    assert "render_3d" in group.tools and re.search(group.keywords, "show me a 3D model of a molecule", re.IGNORECASE)


def test_the_visualise_svg_tool_stays_unoffered():
    from hi.agents.term import term

    assert "visualise" not in term.TERM_GROUPS


def test_the_sandbox_returns_mesh_files_and_has_trimesh():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "sandbox"
    assert "trimesh" in (root / "Dockerfile").read_text()
    server = (root / "server.py").read_text()
    assert all(ext in server for ext in (".glb", ".obj", ".stl", ".gltf", ".ply"))
