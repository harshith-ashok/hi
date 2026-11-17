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
from hi import expr

URL_PREFIX = "/scenes/"
MAX_BYTES = 400_000
MAX_OBJECTS = 400
MAX_INSTANCES = 2000  # objects after `repeat` is expanded
MAX_DEPTH = 6
MAX_VERTICES = 60_000
MAX_GRID = 128  # per side of a surface or parametric shape
MAX_CURVE = 1000
MAX_PARTICLES = 5000
MAX_TRACKS = 8
MAX_KEYS = 64
MAX_DURATION = 600.0
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
    # generated geometry, from math expressions (hi/expr.py) that may use the time `t`
    "surface": {"expr": None, "x": None, "y": None},  # z = expr(x, y, t) over x:[min, max, n], y:[min, max, n]
    "parametric": {"fx": None, "fy": None, "fz": None, "u": None, "v": None},  # (fx, fy, fz)(u, v, t)
    "curve": {"fx": None, "fy": None, "fz": None, "u": None, "radius": 0.0},  # a line or tube through (fx, fy, fz)(u, t)
    "points": {"count": 200},  # a particle emitter
    "line": {"points": None},  # a polyline through [[x, y, z], ...]
    "label": {"text": None},  # floating text
    "arrow": {"from": None, "to": None},
}
MATERIALS = ("standard", "basic", "phong", "toon", "wireframe", "physical")
TEXTURES = ("checker", "stripes", "gradient", "noise", "grid", "dots")
PALETTES = ("viridis", "plasma", "cool", "warm", "rainbow", "gray")
EASES = ("linear", "easeIn", "easeOut", "easeInOut", "bounce", "elastic", "back")
LOOPS = ("loop", "pingpong", "once")
TRACK_PROPERTIES = {"position": "vec3", "rotation": "vec3", "scale": "vec3", "color": "color", "opacity": "number", "emissive": "color"}
EMITTERS = ("sphere", "box", "ring", "spiral", "burst", "rain", "fountain")
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
        self.instances = 0
        self.vertices = 0

    def bad(self, where: str, why: str) -> None:
        if len(self.problems) < MAX_ERRORS:
            self.problems.append(f"{where}: {why}")

    def number(self, value: Any, where: str, low: float = -COORD_LIMIT, high: float = COORD_LIMIT, default: float = 0.0) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            self.bad(where, f"expected a number, got {value!r}")
            return default
        return float(min(max(value, low), high))

    def points(self, raw: Any, where: str, width: int, minimum: int) -> list[list[float]]:
        if not isinstance(raw, list) or len(raw) < minimum:
            self.bad(where, f"expected a list of at least {minimum} points of {width} numbers")
            return []
        self.vertices += len(raw)
        return [self.vector(p, f"{where}[{i}]", width, [0.0] * width) for i, p in enumerate(raw[:MAX_VERTICES])]

    def vector(self, value: Any, where: str, size: int, default: list[float], low: float = -COORD_LIMIT, high: float = COORD_LIMIT) -> list[float]:
        if value is None:
            return list(default)
        if not isinstance(value, (list, tuple)) or len(value) != size:
            self.bad(where, f"expected a list of {size} numbers")
            return list(default)
        return [self.number(v, f"{where}[{i}]", low, high) for i, v in enumerate(value)]

    def choice(self, value: Any, where: str, allowed: tuple[str, ...], default: str) -> str:
        if value is None:
            return default
        if value not in allowed:
            self.bad(where, f"must be one of {', '.join(allowed)}")
            return default
        return value

    def text(self, value: Any, where: str, default: str = "", limit: int = 200) -> str:
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            self.bad(where, f"expected text, got {type(value).__name__}")
            return default
        return str(value)[:limit]

    def expression(self, value: Any, where: str, names: set[str]) -> str:
        """A math expression over the allowed variable names, checked and probed so a mistake comes back as an error."""
        try:
            parsed = expr.parse(value, names)
        except expr.ExprError as e:
            self.bad(where, str(e))
            return "0"
        probe = {n: 0.5 for n in names}
        samples = [expr.evaluate(parsed, {**probe, **{n: v for n in names}}) for v in (-1.3, 0.0, 0.7, 2.1)]
        if all(x != x or x in (float("inf"), float("-inf")) for x in samples):
            self.bad(where, "the expression never gives a finite number")
        return str(value).strip()

    def span(self, value: Any, where: str, limit: int, default_n: int) -> list[float]:
        """[min, max, n]: a range and how many steps."""
        if not isinstance(value, (list, tuple)) or len(value) not in (2, 3):
            self.bad(where, "expected [min, max] or [min, max, steps]")
            return [0.0, 1.0, float(default_n)]
        low = self.number(value[0], f"{where}[0]", -COORD_LIMIT, COORD_LIMIT, 0.0)
        high = self.number(value[1], f"{where}[1]", -COORD_LIMIT, COORD_LIMIT, 1.0)
        steps = self.number(value[2] if len(value) == 3 else default_n, f"{where}[2]", 2, limit, default_n)
        if high <= low:
            self.bad(where, "max must be above min")
        return [low, high, float(int(steps))]

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
    for key, low, high in (("metalness", 0, 1), ("roughness", 0, 1), ("opacity", 0, 1), ("clearcoat", 0, 1),
                           ("transmission", 0, 1), ("ior", 1, 2.5), ("emissiveIntensity", 0, 10)):
        if key in raw:
            out[key] = check.number(raw[key], f"{where}.{key}", low, high, 0.5)
    if (emissive := check.color(raw.get("emissive"), f"{where}.emissive")) is not None:
        out["emissive"] = emissive
    for flag in ("flatShading", "doubleSide"):
        if raw.get(flag):
            out[flag] = True
    tex = raw.get("texture")
    if tex is not None:
        tex = {"kind": tex} if isinstance(tex, str) else tex
        if not isinstance(tex, dict) or tex.get("kind") not in TEXTURES:
            check.bad(f"{where}.texture", f"must be one of {', '.join(TEXTURES)}")
        else:
            colors = tex.get("colors") if isinstance(tex.get("colors"), list) else ["#ffffff", "#334155"]
            out["texture"] = {"kind": tex["kind"], "colors": [check.color(c, f"{where}.texture.colors", "#ffffff") for c in colors[:2]] or ["#ffffff", "#334155"],
                              "repeat": check.vector(tex.get("repeat"), f"{where}.texture.repeat", 2, [1, 1], 0.01, 64)}
    return out


def _points(raw: Any, check: _Check, where: str, width: int, minimum: int) -> list[list[float]]:
    if not isinstance(raw, list) or len(raw) < minimum:
        check.bad(where, f"expected a list of at least {minimum} points of {width} numbers")
        return []
    check.vertices += len(raw)
    return [check.vector(p, f"{where}[{i}]", width, [0.0] * width) for i, p in enumerate(raw)]


def _color_or_default(check: _Check, value: Any, where: str, default: str) -> str:
    return check.color(value, where, default) or default


def _animate(raw: Any, check: _Check, where: str) -> dict:
    """Motion: continuous (rotate, bob, orbit, pulse), a path to follow, and keyframe tracks."""
    if not isinstance(raw, dict):
        check.bad(where, "expected an object like {\"rotate\": [0, 1, 0]}")
        return {}
    out: dict[str, Any] = {}
    if "rotate" in raw:  # radians per second around each axis
        out["rotate"] = check.vector(raw["rotate"], f"{where}.rotate", 3, [0, 0, 0], -20, 20)
    if "bob" in raw:
        out["bob"] = check.number(raw["bob"], f"{where}.bob", 0, 100, 0)
        out["bobSpeed"] = check.number(raw.get("bobSpeed", 1.6), f"{where}.bobSpeed", 0, 50, 1.6)
    if isinstance(raw.get("orbit"), dict):
        o = raw["orbit"]
        out["orbit"] = {"center": check.vector(o.get("center"), f"{where}.orbit.center", 3, [0, 0, 0]),
                        "radius": check.number(o.get("radius", 2), f"{where}.orbit.radius", 0, COORD_LIMIT, 2),
                        "speed": check.number(o.get("speed", 1), f"{where}.orbit.speed", -20, 20, 1),
                        "axis": check.choice(o.get("axis"), f"{where}.orbit.axis", ("x", "y", "z"), "y"),
                        "phase": check.number(o.get("phase", 0), f"{where}.orbit.phase", -100, 100, 0),
                        "tilt": check.number(o.get("tilt", 0), f"{where}.orbit.tilt", -180, 180, 0)}
    if isinstance(raw.get("pulse"), dict):
        pu = raw["pulse"]
        out["pulse"] = {"amount": check.number(pu.get("amount", 0.2), f"{where}.pulse.amount", 0, 5, 0.2),
                        "speed": check.number(pu.get("speed", 2), f"{where}.pulse.speed", 0, 50, 2)}
    if isinstance(raw.get("path"), dict):
        pa = raw["path"]
        pts = check.points(pa.get("points"), f"{where}.path.points", 3, 2)
        out["path"] = {"points": pts, "duration": check.number(pa.get("duration", 5), f"{where}.path.duration", 0.1, MAX_DURATION, 5),
                       "loop": check.choice(pa.get("loop"), f"{where}.path.loop", LOOPS, "loop"), "orient": bool(pa.get("orient")),
                       "closed": bool(pa.get("closed"))}
    if raw.get("tracks") is not None:
        tracks = raw["tracks"]
        if not isinstance(tracks, list) or not tracks:
            check.bad(f"{where}.tracks", "expected a list of keyframe tracks")
            tracks = []
        out["tracks"] = [t for i, tr in enumerate(tracks[:MAX_TRACKS]) if (t := _track(tr, check, f"{where}.tracks[{i}]"))]
    return out


def _track(raw: Any, check: _Check, where: str) -> dict | None:
    if not isinstance(raw, dict) or raw.get("property") not in TRACK_PROPERTIES:
        check.bad(f"{where}.property", f"must be one of {', '.join(TRACK_PROPERTIES)}")
        return None
    kind = TRACK_PROPERTIES[raw["property"]]
    keys = raw.get("keys")
    if not isinstance(keys, list) or not keys:
        check.bad(f"{where}.keys", "expected a list of {t, value, ease} keyframes")
        return None
    out_keys = []
    for i, key in enumerate(keys[:MAX_KEYS]):
        if not isinstance(key, dict):
            check.bad(f"{where}.keys[{i}]", "expected {t, value}")
            continue
        value = key.get("value")
        if kind == "vec3":
            value = check.vector(value, f"{where}.keys[{i}].value", 3, [0, 0, 0], -COORD_LIMIT if raw["property"] != "scale" else 0, COORD_LIMIT)
        elif kind == "color":
            value = _color_or_default(check, value, f"{where}.keys[{i}].value", "#ffffff")
        else:
            value = check.number(value, f"{where}.keys[{i}].value", 0, 1, 1.0)
        out_keys.append({"t": check.number(key.get("t"), f"{where}.keys[{i}].t", 0, MAX_DURATION, 0.0), "value": value,
                         "ease": check.choice(key.get("ease"), f"{where}.keys[{i}].ease", EASES, "easeInOut")})
    out_keys.sort(key=lambda k: k["t"])
    return {"property": raw["property"], "keys": out_keys, "loop": check.choice(raw.get("loop"), f"{where}.loop", LOOPS, "loop")}


def _repeat(raw: Any, check: _Check, where: str) -> dict | None:
    """Copies of one object: along a line, over a grid or around a ring. Returns the cleaned spec with its `total`."""
    if not isinstance(raw, dict):
        check.bad(where, "expected an object like {\"mode\": \"ring\", \"count\": 12, \"radius\": 2}")
        return None
    mode = check.choice(raw.get("mode"), f"{where}.mode", ("linear", "grid", "ring"), "linear")
    out: dict[str, Any] = {"mode": mode, "stagger": check.number(raw.get("stagger", 0), f"{where}.stagger", 0, 60, 0)}
    if mode == "grid":
        counts = check.vector(raw.get("counts"), f"{where}.counts", 3, [3, 1, 3], 1, 60)
        out["counts"] = [float(int(c)) for c in counts]
        out["spacing"] = check.vector(raw.get("spacing"), f"{where}.spacing", 3, [1, 1, 1], 0, COORD_LIMIT)
        total = int(out["counts"][0] * out["counts"][1] * out["counts"][2])
    else:
        total = int(check.number(raw.get("count"), f"{where}.count", 1, MAX_INSTANCES, 2))
        out["count"] = total
        if mode == "ring":
            out["radius"] = check.number(raw.get("radius", 2), f"{where}.radius", 0, COORD_LIMIT, 2)
            out["axis"] = check.choice(raw.get("axis"), f"{where}.axis", ("x", "y", "z"), "y")
            out["faceCenter"] = bool(raw.get("faceCenter"))
        else:
            out["step"] = check.vector(raw.get("step"), f"{where}.step", 3, [1, 0, 0])
            out["rotateStep"] = check.vector(raw.get("rotateStep"), f"{where}.rotateStep", 3, [0, 0, 0], -3600, 3600)
            out["scaleStep"] = check.number(raw.get("scaleStep", 1), f"{where}.scaleStep", 0.01, 10, 1)
    out["total"] = total
    return out


def _object(raw: Any, check: _Check, where: str, depth: int) -> dict | None:
    check.objects += 1
    start = check.objects
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
    if shape in ("surface", "parametric", "curve", "points", "line", "label", "arrow"):
        _generated(shape, raw, check, where, out)
        shapes_done = True
    else:
        shapes_done = False
    for key, default in ({} if shapes_done else SHAPES[shape]).items():
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
    if raw.get("animate") is not None:
        out["animate"] = _animate(raw["animate"], check, f"{where}.animate")
    if raw.get("repeat") is not None:
        rep = _repeat(raw["repeat"], check, f"{where}.repeat")
        if rep:
            out["repeat"] = rep
            check.instances += (rep["total"] - 1) * (check.objects - start + 1)  # every copy of the whole subtree
    if raw.get("castShadow") is False:
        out["castShadow"] = False
    return out


def _generated(shape: str, raw: dict, check: _Check, where: str, out: dict) -> None:
    """The shapes made from expressions, points or text rather than a fixed geometry."""
    ex = lambda key, names: check.expression(raw.get(key), f"{where}.{key}", names)  # noqa: E731
    if shape == "surface":
        out["expr"] = ex("expr", {"x", "y", "t"})
        out["x"], out["y"] = check.span(raw.get("x"), f"{where}.x", MAX_GRID, 48), check.span(raw.get("y"), f"{where}.y", MAX_GRID, 48)
        check.vertices += int(out["x"][2] * out["y"][2])
    elif shape == "parametric":
        for key in ("fx", "fy", "fz"):
            out[key] = ex(key, {"u", "v", "t"})
        out["u"], out["v"] = check.span(raw.get("u"), f"{where}.u", MAX_GRID, 48), check.span(raw.get("v"), f"{where}.v", MAX_GRID, 24)
        check.vertices += int(out["u"][2] * out["v"][2])
    elif shape == "curve":
        for key in ("fx", "fy", "fz"):
            out[key] = ex(key, {"u", "t"})
        out["u"] = check.span(raw.get("u"), f"{where}.u", MAX_CURVE, 200)
        out["radius"] = check.number(raw.get("radius", 0), f"{where}.radius", 0, COORD_LIMIT, 0)
        check.vertices += int(out["u"][2])
    elif shape == "points":
        out["count"] = int(check.number(raw.get("count", 200), f"{where}.count", 1, MAX_PARTICLES, 200))
        out["emitter"] = check.choice(raw.get("emitter"), f"{where}.emitter", EMITTERS, "sphere")
        for key, low, high, default in (("size", 0.001, 5, 0.05), ("spread", 0, COORD_LIMIT, 1), ("speed", 0, 100, 0.5),
                                        ("life", 0.1, 600, 4), ("gravity", -50, 50, 0)):
            out[key] = check.number(raw.get(key, default), f"{where}.{key}", low, high, default)
        out["seed"] = int(check.number(raw.get("seed", 1), f"{where}.seed", 0, 2**31, 1))
        if raw.get("palette") is not None:
            out["palette"] = check.choice(raw.get("palette"), f"{where}.palette", PALETTES, "viridis")
        check.vertices += out["count"]
    elif shape == "line":
        out["points"] = check.points(raw.get("points"), f"{where}.points", 3, 2)
        out["dashed"] = bool(raw.get("dashed"))
    elif shape == "label":
        out["text"] = check.text(raw.get("text"), f"{where}.text", "", 80) or check.bad(f"{where}.text", "a label needs text") or ""
        out["size"] = check.number(raw.get("size", 0.3), f"{where}.size", 0.01, 100, 0.3)
        if raw.get("background") is not None:
            out["background"] = _color_or_default(check, raw["background"], f"{where}.background", "#000000")
    elif shape == "arrow":
        out["from"] = check.vector(raw.get("from"), f"{where}.from", 3, [0, 0, 0])
        out["to"] = check.vector(raw.get("to"), f"{where}.to", 3, [0, 1, 0])
    if shape == "surface" or shape == "parametric":
        if raw.get("colorBy") is not None:
            out["colorBy"] = check.choice(raw.get("colorBy"), f"{where}.colorBy", ("height", "none"), "none")
        if raw.get("palette") is not None:
            out["palette"] = check.choice(raw.get("palette"), f"{where}.palette", PALETTES, "viridis")


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
    if isinstance(cam, dict) and isinstance(cam.get("orbit"), dict):  # the camera circles the target
        o = cam["orbit"]
        out["camera"]["orbit"] = {"radius": check.number(o.get("radius", 5), "camera.orbit.radius", 0.01, COORD_LIMIT, 5),
                                  "height": check.number(o.get("height", 2), "camera.orbit.height", -COORD_LIMIT, COORD_LIMIT, 2),
                                  "speed": check.number(o.get("speed", 0.3), "camera.orbit.speed", -10, 10, 0.3),
                                  "phase": check.number(o.get("phase", 0), "camera.orbit.phase", -100, 100, 0)}
    if isinstance(cam, dict) and cam.get("tracks") is not None:  # keyframed camera moves
        tracks = cam["tracks"] if isinstance(cam["tracks"], list) else []
        good = []
        for i, tr in enumerate(tracks[:2]):
            if not isinstance(tr, dict) or tr.get("property") not in ("position", "target"):
                check.bad(f"camera.tracks[{i}].property", "must be position or target")
                continue
            clean = _track({**tr, "property": "position"}, check, f"camera.tracks[{i}]")
            if clean:
                clean["property"] = tr["property"]
                good.append(clean)
        out["camera"]["tracks"] = good
    if scene.get("duration") is not None:
        out["duration"] = check.number(scene["duration"], "duration", 0.1, MAX_DURATION, 10)
    out["loop"] = bool(scene.get("loop", True))
    if scene.get("shadows"):
        out["shadows"] = True
    if scene.get("environment"):
        out["environment"] = True
    ground = scene.get("ground")
    if ground:
        g = ground if isinstance(ground, dict) else {}
        out["ground"] = {"color": _color_or_default(check, g.get("color"), "ground.color", "#e4e4e7"), "size": check.number(g.get("size", 30), "ground.size", 1, COORD_LIMIT, 30)}
    if isinstance(scene.get("fog"), dict):
        f = scene["fog"]
        out["fog"] = {"color": _color_or_default(check, f.get("color"), "fog.color", "#f4f4f5"),
                      "near": check.number(f.get("near", 5), "fog.near", 0, COORD_LIMIT, 5), "far": check.number(f.get("far", 40), "fog.far", 1, COORD_LIMIT, 40)}
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
    if check.objects + check.instances > MAX_INSTANCES:
        check.bad("scene", f"{check.objects + check.instances} objects once repeats are expanded; the limit is {MAX_INSTANCES}")
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
    """Show 3D objects and animations to the user in an interactive viewer (drag to rotate, scroll to zoom, a timeline
    to play, pause and scrub). Use it for "show me a 3D model of X", shapes, molecules, solar systems, mechanisms,
    floor plans, product concepts, maths surfaces, particle effects, anything that moves.

    The scene is JSON data, not code. Shapes (`type`): box, sphere, cylinder, cone, capsule, torus, torusknot, plane,
    circle, ring, tetrahedron, octahedron, dodecahedron, icosahedron, lathe, extrude, mesh, group, and generated ones:
    surface (z = expr in x, y, t), parametric (fx, fy, fz in u, v, t), curve (fx, fy, fz in u, t; radius for a tube),
    points (particles), line, label (floating text), arrow. Every shape takes position, rotation (degrees), scale, color,
    material and `animate`; any shape can have `repeat` (linear, grid or ring copies). Scene options: camera, lights,
    background, grid, axes, shadows, ground, fog, environment, duration, loop. The reference with examples is in your
    instructions under "3D objects and animation". Keep the scene within a few units of the origin.

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
