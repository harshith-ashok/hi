"""3D scenes: the model describes objects as data, the chat draws them with three.js.

`render_3d` takes a scene as JSON (shapes, positions, materials, lights, a camera), checks it against the limits below,
saves it under <vault>/hi/scenes/ and returns its /scenes/<name>.json path, which the UI shows as an interactive viewer
(drag to rotate, wheel to zoom). A scene is data, never code: the viewer builds only the shapes listed here, so a scene
cannot run anything in your browser. Python in the sandbox can write the same JSON to a `*.scene.json` file, or export a
mesh (`.glb`, `.obj`, `.stl`) that the viewer opens too.

A bad scene is refused with every problem listed, so the model can fix it and try again.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any

from langchain_core.tools import tool

import hi.config as config

URL_PREFIX = "/scenes/"
MAX_BYTES = 400_000
MAX_OBJECTS = 400
MAX_DEPTH = 6
MAX_VERTICES = 60_000
MAX_ERRORS = 8
COORD_LIMIT = 10_000.0

# shape -> {parameter: default}. Numbers are clamped to a sensible range; lists are checked for length.
SHAPES: dict[str, dict[str, Any]] = {
    "box": {"size": [1, 1, 1]},
    "sphere": {"radius": 0.5},
    "cylinder": {"radius": 0.5, "height": 1},
    "cone": {"radius": 0.5, "height": 1},
    "capsule": {"radius": 0.3, "length": 0.8},
    "torus": {"radius": 0.5, "tube": 0.15},
    "torusknot": {"radius": 0.5, "tube": 0.15},
    "plane": {"size": [1, 1]},
    "circle": {"radius": 0.5},
    "ring": {"inner": 0.3, "outer": 0.5},
    "tetrahedron": {"radius": 0.5},
    "octahedron": {"radius": 0.5},
    "dodecahedron": {"radius": 0.5},
    "icosahedron": {"radius": 0.5},
    "lathe": {"points": None},  # [[radius, y], ...] revolved around the y axis
    "extrude": {"shape": None, "depth": 0.3},  # [[x, y], ...] outline, pushed along z
    "mesh": {"vertices": None, "faces": None},  # triangles as indices into vertices
    "group": {"children": None},
}
MATERIALS = ("standard", "basic", "phong", "toon", "wireframe")
LIGHTS = ("ambient", "directional", "point", "hemisphere")
_COLOR = re.compile(r"#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}|[a-zA-Z]{3,20}")


class SceneError(ValueError):
    """The scene broke a rule. `problems` lists them all (up to MAX_ERRORS)."""

    def __init__(self, problems: list[str]):
        self.problems = problems[:MAX_ERRORS]
        super().__init__("; ".join(self.problems))


class _Check:
    """Collects problems while normalising, so one pass reports everything."""

    def __init__(self) -> None:
        self.problems: list[str] = []
        self.objects = 0
        self.vertices = 0

    def bad(self, where: str, why: str) -> None:
        if len(self.problems) < MAX_ERRORS:
            self.problems.append(f"{where}: {why}")

    def number(self, value: Any, where: str, low: float = -COORD_LIMIT, high: float = COORD_LIMIT, default: float = 0.0) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            self.bad(where, f"expected a number, got {value!r}")
            return default
        return float(min(max(value, low), high))

    def vector(self, value: Any, where: str, size: int, default: list[float], low: float = -COORD_LIMIT, high: float = COORD_LIMIT) -> list[float]:
        if value is None:
            return list(default)
        if not isinstance(value, (list, tuple)) or len(value) != size:
            self.bad(where, f"expected a list of {size} numbers")
            return list(default)
        return [self.number(v, f"{where}[{i}]", low, high) for i, v in enumerate(value)]

    def color(self, value: Any, where: str, default: str | None = None) -> str | None:
        if value is None:
            return default
        if not isinstance(value, str) or not _COLOR.fullmatch(value):
            self.bad(where, f"expected a color like \"#ff8800\" or \"red\", got {value!r}")
            return default
        return value


def _material(raw: Any, check: _Check, where: str) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    kind = raw.get("kind", "standard")
    if kind not in MATERIALS:
        check.bad(f"{where}.kind", f"must be one of {', '.join(MATERIALS)}")
        kind = "standard"
    out: dict[str, Any] = {"kind": kind}
    for key, low, high in (("metalness", 0, 1), ("roughness", 0, 1), ("opacity", 0, 1)):
        if key in raw:
            out[key] = check.number(raw[key], f"{where}.{key}", low, high, 0.5)
    if (emissive := check.color(raw.get("emissive"), f"{where}.emissive")) is not None:
        out["emissive"] = emissive
    for flag in ("flatShading", "doubleSide"):
        if raw.get(flag):
            out[flag] = True
    return out


def _points(raw: Any, check: _Check, where: str, width: int, minimum: int) -> list[list[float]]:
    if not isinstance(raw, list) or len(raw) < minimum:
        check.bad(where, f"expected a list of at least {minimum} points of {width} numbers")
        return []
    check.vertices += len(raw)
    return [check.vector(p, f"{where}[{i}]", width, [0.0] * width) for i, p in enumerate(raw)]


def _object(raw: Any, check: _Check, where: str, depth: int) -> dict | None:
    check.objects += 1
    if check.objects > MAX_OBJECTS:
        check.bad("scene", f"more than {MAX_OBJECTS} objects")
        return None
    if depth > MAX_DEPTH:
        check.bad(where, f"groups are nested more than {MAX_DEPTH} deep")
        return None
    if not isinstance(raw, dict):
        check.bad(where, "each object must be an object")
        return None
    shape = raw.get("type")
    if shape not in SHAPES:
        check.bad(f"{where}.type", f"unknown shape {shape!r}; use one of {', '.join(SHAPES)}")
        return None
    out: dict[str, Any] = {"type": shape}
    for key, default in SHAPES[shape].items():
        value = raw.get(key)
        if shape == "group" and key == "children":
            kids = value if isinstance(value, list) else []
            out["children"] = [c for i, k in enumerate(kids) if (c := _object(k, check, f"{where}.children[{i}]", depth + 1))]
        elif shape == "lathe":
            out["points"] = _points(value, check, f"{where}.points", 2, 2)
        elif shape == "extrude":
            if key == "shape":
                out["shape"] = _points(value, check, f"{where}.shape", 2, 3)
            else:
                out["depth"] = check.number(value if value is not None else default, f"{where}.depth", 0.001, COORD_LIMIT, default)
        elif shape == "mesh":
            if key == "vertices":
                out["vertices"] = _points(value, check, f"{where}.vertices", 3, 3)
            else:
                faces = value if isinstance(value, list) else []
                count = len(out.get("vertices", []))
                if not faces:
                    check.bad(f"{where}.faces", "expected a list of triangles, each three vertex indices")
                for i, face in enumerate(faces):
                    if not (isinstance(face, list) and len(face) == 3 and all(isinstance(n, int) and not isinstance(n, bool) and 0 <= n < count for n in face)):
                        check.bad(f"{where}.faces[{i}]", f"expected three indices below {count}")
                        break
                out["faces"] = faces
        elif isinstance(default, list):
            out[key] = check.vector(value, f"{where}.{key}", len(default), default, 0.0001, COORD_LIMIT)
        else:
            out[key] = check.number(value if value is not None else default, f"{where}.{key}", 0.0001, COORD_LIMIT, default)
    out["position"] = check.vector(raw.get("position"), f"{where}.position", 3, [0, 0, 0])
    out["rotation"] = check.vector(raw.get("rotation"), f"{where}.rotation", 3, [0, 0, 0], -3600, 3600)  # degrees
    scale = raw.get("scale")
    out["scale"] = check.vector([scale] * 3 if isinstance(scale, (int, float)) and not isinstance(scale, bool) else scale,
                                f"{where}.scale", 3, [1, 1, 1], 0.0001, COORD_LIMIT)
    if (color := check.color(raw.get("color"), f"{where}.color", "#8899aa")) is not None:
        out["color"] = color
    out["material"] = _material(raw.get("material"), check, f"{where}.material")
    if isinstance(raw.get("name"), str):
        out["name"] = raw["name"][:60]
    anim = raw.get("animate")
    if isinstance(anim, dict):
        out["animate"] = {}
        if "rotate" in anim:  # radians per second around each axis
            out["animate"]["rotate"] = check.vector(anim["rotate"], f"{where}.animate.rotate", 3, [0, 0, 0], -20, 20)
        if "bob" in anim:
            out["animate"]["bob"] = check.number(anim["bob"], f"{where}.animate.bob", 0, 100, 0)
    return out


def normalize(scene: Any) -> dict:
    """The scene with defaults filled in and every value clamped, or SceneError listing what is wrong."""
    if isinstance(scene, str):
        try:
            scene = json.loads(scene)
        except json.JSONDecodeError as e:
            raise SceneError([f"scene: not valid JSON ({e.msg} at position {e.pos})"]) from None
    if not isinstance(scene, dict):
        raise SceneError(["scene: expected a JSON object with an \"objects\" list"])
    check = _Check()
    raw_objects = scene.get("objects")
    if not isinstance(raw_objects, list) or not raw_objects:
        raise SceneError(["objects: expected a non-empty list of shapes"])
    out: dict[str, Any] = {"title": str(scene.get("title", "3D scene"))[:80]}
    out["objects"] = [o for i, raw in enumerate(raw_objects) if (o := _object(raw, check, f"objects[{i}]", 1))]
    if (bg := check.color(scene.get("background"), "background")) is not None:
        out["background"] = bg
    cam = scene.get("camera")
    if isinstance(cam, dict):
        out["camera"] = {"position": check.vector(cam.get("position"), "camera.position", 3, [3, 2, 4]),
                         "target": check.vector(cam.get("target"), "camera.target", 3, [0, 0, 0]),
                         "fov": check.number(cam.get("fov", 50), "camera.fov", 10, 120, 50)}
    lights = []
    for i, raw in enumerate(scene.get("lights") or []):
        if not isinstance(raw, dict) or raw.get("type") not in LIGHTS:
            check.bad(f"lights[{i}].type", f"must be one of {', '.join(LIGHTS)}")
            continue
        lights.append({"type": raw["type"], "color": check.color(raw.get("color"), f"lights[{i}].color", "#ffffff"),
                       "intensity": check.number(raw.get("intensity", 1), f"lights[{i}].intensity", 0, 100, 1),
                       "position": check.vector(raw.get("position"), f"lights[{i}].position", 3, [3, 5, 4])})
    if lights:
        out["lights"] = lights
    for flag, default in (("grid", True), ("axes", False), ("autoRotate", False)):
        out[flag] = bool(scene.get(flag, default))
    if check.vertices > MAX_VERTICES:
        check.bad("scene", f"{check.vertices} mesh points; the limit is {MAX_VERTICES}")
    if check.problems:
        raise SceneError(check.problems)
    if len(json.dumps(out)) > MAX_BYTES:
        raise SceneError([f"scene: larger than {MAX_BYTES // 1000} KB; use fewer or simpler shapes"])
    return out


def scenes_dir():
    return config.VAULT_PATH / "hi" / "scenes"


def save(scene: dict) -> str:
    """Write a normalised scene and return its URL path, /scenes/<name>.json."""
    slug = re.sub(r"[^\w-]+", "-", scene["title"].lower()).strip("-")[:40] or "scene"
    name = f"{slug}-{datetime.now():%H%M%S}.json"
    scenes_dir().mkdir(parents=True, exist_ok=True)
    (scenes_dir() / name).write_text(json.dumps(scene))
    return URL_PREFIX + name


@tool
def render_3d(scene: dict | str, title: str = "") -> str:
    """Show 3D objects to the user as an interactive viewer (drag to rotate, scroll to zoom). Use it for "show me a
    3D model of X", shapes, molecules, solar systems, floor plans, product concepts, data in 3D.

    The scene is JSON data, not code. Shapes (type): box, sphere, cylinder, cone, capsule, torus, torusknot, plane,
    circle, ring, tetrahedron, octahedron, dodecahedron, icosahedron, lathe (points [[radius, y], ...]), extrude (shape
    [[x, y], ...], depth), mesh (vertices [[x, y, z], ...], faces [[i, j, k], ...]) and group (children). Every shape takes
    position [x, y, z], rotation [x, y, z] in degrees, scale, color ("#ff8800" or "red") and material {kind: standard |
    basic | phong | toon | wireframe, metalness, roughness, opacity, emissive}; animate {rotate: [x, y, z]} spins it.
    Sizes: box size [w, h, d]; sphere/cone/cylinder radius (+height); torus radius and tube. Units are free but keep the
    whole scene within a few units of the origin. Optional: camera {position, target, fov}, lights [{type, color,
    intensity, position}], background, grid, axes, autoRotate.

    Example: {"title": "Snowman", "objects": [{"type": "sphere", "radius": 0.6, "color": "white"},
    {"type": "sphere", "radius": 0.4, "position": [0, 0.8, 0], "color": "white"},
    {"type": "cone", "radius": 0.06, "height": 0.3, "position": [0, 0.8, 0.4], "rotation": [90, 0, 0], "color": "orange"}]}

    Args:
        scene: The scene as a JSON object (or a JSON string) with an "objects" list.
        title: Short name shown above the viewer.
    """
    try:
        data = {**scene, "title": scene.get("title") or title} if isinstance(scene, dict) and title else scene
        clean = normalize(data)
    except SceneError as e:
        return "Not rendered. Fix these and call render_3d again:\n- " + "\n- ".join(e.problems)
    return f"3D scene '{clean['title']}' ({len(clean['objects'])} objects) is already displayed to the user in the UI (do not embed or link it): {save(clean)}"
