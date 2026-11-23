import base64
import importlib.util
import io
import json
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

import hi.config as config
from hi import imagegen, probes, toolkit
from hi.core import health

PNG = b"\x89PNG\r\n\x1a\n" + b"fake image bytes"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    health.reset()
    monkeypatch.setattr(config, "IMAGE_BACKEND", "service")
    monkeypatch.setattr(config, "IMAGE_URL", "http://images.test:8793")
    monkeypatch.setattr(config, "IMAGE_MODEL", "Tongyi-MAI/Z-Image-Turbo")
    monkeypatch.setattr(config, "IMAGE_API_KEY", "")


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def ok(request):
    return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})


# --- the client ---------------------------------------------------------------------------------------------------

def test_a_request_goes_to_the_images_endpoint_in_the_openai_shape():
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), body=json.loads(request.content), auth=request.headers.get("authorization"))
        return ok(request)

    assert imagegen.generate("a red fox  in snow", "1024x768", seed=7, client=client_for(handler)) == PNG
    assert seen["url"] == "http://images.test:8793/v1/images/generations" and seen["auth"] is None
    assert seen["body"] == {"model": "Tongyi-MAI/Z-Image-Turbo", "prompt": "a red fox in snow", "size": "1024x768", "n": 1,
                            "response_format": "b64_json", "seed": 7}


def test_an_unknown_size_falls_back_and_a_key_is_sent_as_a_bearer_token(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_API_KEY", "sk-test-key-1234567890")
    seen = {}
    imagegen.generate("x", "99x99", client=client_for(lambda r: seen.update(b=json.loads(r.content), a=r.headers["authorization"]) or ok(r)))
    assert seen["b"]["size"] == "1024x1024" and seen["a"] == "Bearer sk-test-key-1234567890" and "seed" not in seen["b"]


@pytest.mark.parametrize("prompt", ["", "   ", "x" * 4001])
def test_bad_prompts_are_refused_before_any_request(prompt):
    with pytest.raises(imagegen.ImageError):
        imagegen.generate(prompt, client=client_for(lambda r: pytest.fail("made a request")))


def test_switched_off_means_no_request_and_a_clear_reason(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_BACKEND", "off")
    with pytest.raises(imagegen.ImageError, match="switched off"):
        imagegen.generate("x", client=client_for(lambda r: pytest.fail("made a request")))


def test_an_unreachable_service_marks_it_down_and_says_how_to_start_it():
    def refuse(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(imagegen.ImageError, match="docker compose --profile gpu up -d imagegen"):
        imagegen.generate("x", client=client_for(refuse))
    assert not health.snapshot()["imagegen"]["ok"]


def test_an_error_from_the_service_is_reported_with_its_message():
    with pytest.raises(imagegen.ImageError, match="400.*each side must be"):
        imagegen.generate("x", client=client_for(lambda r: httpx.Response(400, json={"error": {"message": "each side must be between 256 and 1536"}})))
    assert health.is_up("imagegen")  # a bad request is the caller's fault, not an outage
    with pytest.raises(imagegen.ImageError):
        imagegen.generate("x", client=client_for(lambda r: httpx.Response(500, text="boom")))
    assert not health.snapshot()["imagegen"]["ok"]


@pytest.mark.parametrize("payload", [{}, {"data": []}, {"data": [{"b64_json": "!!!"}]}, {"data": [{"b64_json": base64.b64encode(b"not a png").decode()}]}])
def test_an_answer_that_is_not_a_png_is_refused(payload):
    with pytest.raises(imagegen.ImageError):
        imagegen.generate("x", client=client_for(lambda r: httpx.Response(200, json=payload)))


def test_success_marks_the_service_up():
    health.mark_down("imagegen", "x", cooldown_s=0)
    imagegen.generate("x", client=client_for(ok))
    assert health.snapshot()["imagegen"]["ok"]


# --- the tool ------------------------------------------------------------------------------------------------------

def test_the_tool_saves_the_png_next_to_the_charts_and_returns_its_path(tmp_vault, monkeypatch):
    monkeypatch.setattr(imagegen, "generate", lambda prompt, size, seed: PNG)
    out = imagegen.generate_image.invoke({"prompt": "A lighthouse at dawn!", "size": "1024x768"})
    path = out.rsplit(": ", 1)[1]
    assert path.startswith("/plots/image-a-lighthouse-at-dawn-") and path.endswith(".png") and "do not embed" in out
    assert (tmp_vault / "hi" / "plots" / path.split("/")[-1]).read_bytes() == PNG
    assert TestClient(__import__("hi.server.app", fromlist=["create_app"]).create_app()).get(path).status_code == 200  # the chart route serves it


def test_the_tool_tells_the_model_what_went_wrong(tmp_vault, monkeypatch):
    def fail(prompt, size, seed):
        raise imagegen.ImageError("the image service is not reachable")

    monkeypatch.setattr(imagegen, "generate", fail)
    out = imagegen.generate_image.invoke({"prompt": "x"})
    assert out.startswith("No image was made") and "not reachable" in out and not (tmp_vault / "hi" / "plots").exists()


# --- being offered -------------------------------------------------------------------------------------------------

def test_the_tool_is_offered_only_when_enabled_and_the_service_is_up(monkeypatch):
    assert toolkit.dependency_is_up("generate_image")
    health.mark_down("imagegen", "refused")
    assert not toolkit.dependency_is_up("generate_image")
    health.reset()
    monkeypatch.setattr(config, "IMAGE_BACKEND", "off")
    assert not toolkit.dependency_is_up("generate_image")


def test_term_has_the_tool_and_it_is_not_read_only():
    from hi.agents.term import term

    assert "generate_image" in {t.name for t in term.TOOLS} and "imagegen" in term.TERM_GROUPS
    assert "generate_image" not in toolkit.READ_ONLY  # a background run asks first: it costs time and GPU


def test_the_group_matches_requests_for_pictures_but_not_for_existing_photos():
    import re

    keywords = next(g for g in toolkit.GROUPS if g.name == "imagegen").keywords
    for hit in ("draw me a logo for my cafe", "generate an image of a dragon", "make a poster for the hackathon", "concept art of a city"):
        assert re.search(keywords, hit, re.IGNORECASE), hit
    assert not re.search(keywords, "what is the capital of france", re.IGNORECASE)


# --- health and settings ---------------------------------------------------------------------------------------------

def test_the_probe_is_quiet_when_switched_off_and_reports_a_dead_service(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_BACKEND", "off")
    probes._imagegen()
    assert health.snapshot()["imagegen"]["ok"]
    monkeypatch.setattr(config, "IMAGE_BACKEND", "service")
    monkeypatch.setattr(config, "IMAGE_URL", "http://127.0.0.1:1")
    with pytest.raises(OSError):
        probes._imagegen()


def test_the_backend_setting_is_validated_and_the_key_stays_out_of_the_settings_payload(monkeypatch):
    with pytest.raises(ValueError, match="service, openai or off"):
        config.coerce("IMAGE_BACKEND", "midjourney")
    assert config.coerce("IMAGE_BACKEND", "OFF") == "off"
    monkeypatch.setattr(config, "IMAGE_API_KEY", "sk-image-key-12345678")
    from hi.server.app import create_app

    body = TestClient(create_app()).get("/config").json()
    assert body["IMAGE_BACKEND"] == "service" and "IMAGE_API_KEY" not in body and "sk-image-key" not in json.dumps(body)
    assert "sk-image-key-12345678" in config.secret_values()  # and it is masked everywhere else


# --- the service (no GPU: a stub pipeline) ---------------------------------------------------------------------------

def load_server():
    spec = importlib.util.spec_from_file_location("imagegen_server", Path(__file__).resolve().parents[2] / "imagegen" / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeImage:
    def save(self, out, format):
        out.write(PNG)


@pytest.fixture
def server():
    mod = load_server()
    calls = []
    gen = mod.Generator("Tongyi-MAI/Z-Image-Turbo", loader=lambda model, device: calls.append(("load", model, device)) or "pipe",
                        device=lambda: "cuda", runner=lambda *a: calls.append(("run",) + a[1:]) or FakeImage())
    return mod, gen, calls


def post(mod, gen, **body):
    return mod.handle(gen, "POST", "/v1/images/generations", json.dumps(body).encode())


def test_the_service_loads_once_on_the_first_request_and_returns_a_png(server):
    mod, gen, calls = server
    assert mod.handle(gen, "GET", "/health", b"")[1]["loaded"] is False
    status, body = post(mod, gen, prompt="a cat", size="1024x768", seed=3)
    assert status == 200 and base64.b64decode(body["data"][0]["b64_json"]) == PNG
    post(mod, gen, prompt="a dog")
    assert [c[0] for c in calls] == ["load", "run", "run"]  # loaded once, run twice
    assert calls[1] == ("run", "cuda", {"pipeline": "ZImagePipeline", "steps": 9, "guidance": 0.0}, "a cat", 1024, 768, 3)
    assert mod.handle(gen, "GET", "/health", b"")[1] == {"ok": True, "model": "Tongyi-MAI/Z-Image-Turbo", "loaded": True, "device": "cuda"}


@pytest.mark.parametrize("body", [{"prompt": ""}, {"prompt": "x", "size": "huge"}, {"prompt": "x", "size": "64x64"},
                                  {"prompt": "x", "size": "4096x4096"}, {"prompt": "x", "seed": "7"}, {"prompt": "x" * 5000}])
def test_the_service_refuses_bad_requests_without_loading_the_model(server, body):
    mod, gen, calls = server
    assert post(mod, gen, **body)[0] == 400 and calls == []


def test_sizes_are_rounded_down_to_what_the_model_needs(server):
    mod, _, _ = server
    assert mod.parse_size("1000x770") == (992, 768) and mod.parse_size(None) == (1024, 1024)


def test_a_failing_pipeline_is_a_500_with_a_reason_not_a_crash(server):
    mod, _, _ = server

    def boom(*a):
        raise RuntimeError("CUDA out of memory")

    gen = mod.Generator("m", loader=lambda *a: "pipe", device=lambda: "cuda", runner=boom)
    status, body = post(mod, gen, prompt="x")
    assert status == 500 and "CUDA out of memory" in body["error"]["message"]


def test_the_model_family_picks_the_right_settings(monkeypatch):
    mod = load_server()
    assert mod.family("black-forest-labs/FLUX.2-klein-4B") == {"pipeline": "Flux2KleinPipeline", "steps": 4, "guidance": 1.0}
    assert mod.family("someone/unknown-model")["pipeline"] == "AutoPipelineForText2Image"
    monkeypatch.setenv("IMAGE_STEPS", "12")
    assert mod.family("Tongyi-MAI/Z-Image-Turbo")["steps"] == 12


def test_routes_and_models_listing(server):
    mod, gen, _ = server
    assert mod.handle(gen, "GET", "/v1/models", b"")[1]["data"][0]["id"] == "Tongyi-MAI/Z-Image-Turbo"
    assert mod.handle(gen, "GET", "/nope", b"")[0] == 404 and mod.handle(gen, "POST", "/health", b"")[0] == 404


def test_the_compose_service_and_dockerfile_exist():
    root = Path(__file__).resolve().parents[2]
    compose = (root / "docker-compose.yml").read_text()
    assert "imagegen:" in compose and "IMAGE_URL_DEFAULT: http://imagegen:8793" in compose and "hi-image-models" in compose
    assert "diffusers" in (root / "imagegen" / "Dockerfile").read_text()


def test_zero_guidance_for_zimage_turbo_is_kept_and_can_be_overridden(monkeypatch):
    mod = load_server()
    assert mod.family("Tongyi-MAI/Z-Image-Turbo")["guidance"] == 0.0  # `0.0 or default` would silently make this 4.0
    monkeypatch.setenv("IMAGE_GUIDANCE", "0")
    assert mod.family("someone/unknown-model")["guidance"] == 0.0
    monkeypatch.setenv("IMAGE_GUIDANCE", "2.5")
    assert mod.family("Tongyi-MAI/Z-Image-Turbo")["guidance"] == 2.5


def test_image_url_follows_the_tailscale_box(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_URL", "")
    monkeypatch.setattr(config, "AI_MODE", "tailscale")
    monkeypatch.setattr(config, "TAILSCALE_OLLAMA_URL", "http://gpu-box.tail1234.ts.net:11434")
    assert config.image_url() == "http://gpu-box.tail1234.ts.net:8793"
    monkeypatch.setattr(config, "TAILSCALE_OLLAMA_URL", "100.64.0.5:11434")
    assert config.image_url() == "http://100.64.0.5:8793"
    monkeypatch.setattr(config, "IMAGE_URL", "http://other:9000/")
    assert config.image_url() == "http://other:9000"  # an explicit setting wins
    monkeypatch.setattr(config, "IMAGE_URL", "")
    monkeypatch.setattr(config, "AI_MODE", "local")
    assert config.image_url().endswith(":8793")
