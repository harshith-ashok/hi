# 0004: Animated 3D scenes, image generation, generated UI

## Animation
Scenes stay data, never code. Motion is a pure function of time: `update(t)` in `tinyui/src/lib/scene3d.ts` places
everything at time `t`, so the viewer can play, pause, scrub, loop and record (WebM via `captureStream`) by changing `t`.
Formulas (surfaces, parametric shapes, curves) use a small expression language with no `eval`: `hi/expr.py` validates
it on the backend, `tinyui/src/lib/expr.ts` runs it in the browser. Both share one grammar and function list.
`hi/scene3d.py` bounds everything (instances, grid size, particles, tracks, keys, duration) and probes expressions for
finite results before saving. Particles use a seeded generator, so a scene looks the same every time.

## Image generation
A separate `imagegen/` service speaks the OpenAI `/v1/images/generations` shape. `hi/imagegen.py` is the client and the
`generate_image` tool is hidden when `IMAGE_BACKEND=off` or the service is down (`hi/probes.py`). Pictures are saved as
PNG in `<vault>/hi/plots/` and served by the existing `/plots/` route.

## Generated UI
`show_ui` takes a spec checked against a whitelist (`hi/ui_spec.py`: layout, display, input and action components),
saves it to `<vault>/hi/ui/`, and tinyui renders it. The user's answer returns as the next message; the turn ends at the
tool's wait marker, and the form locks once a later turn exists. Background runs refuse `show_ui` and `ask_user`.
