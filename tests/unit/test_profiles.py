from hi.automation import profiles


def test_the_island_is_fast_and_short_and_never_above_sonnet():
    p = profiles.profile("island")
    assert p.max_tier == "sonnet" and not p.reasoning and "three short sentences" in p.style and p.timeout_s == 30
    assert profiles.cap_tier("opus", p.max_tier) == "sonnet"
    assert profiles.cap_tier("haiku", p.max_tier) == "haiku"


def test_chat_turns_are_left_to_the_router():
    for name in ("ui", "voice"):
        p = profiles.profile(name)
        assert p.tier is None and p.max_tier is None and p.style == ""
    assert profiles.cap_tier("opus", None) == "opus"


def test_background_origins_ask_for_a_report_and_have_a_timeout():
    for name in ("schedule", "heartbeat.prepare", "drop.file"):
        p = profiles.profile(name)
        assert "Markdown" in p.style and p.timeout_s > 0 and "question" in p.style


def test_triage_is_cheap_json():
    p = profiles.profile("heartbeat.triage")
    assert p.tier == "haiku" and "JSON" in p.style and not p.reasoning


def test_a_role_falls_back_to_its_origin_and_an_unknown_name_to_ui():
    assert profiles.profile("schedule.whatever") == profiles.profile("schedule")
    assert profiles.profile("nonsense") == profiles.profile("ui")
