from pathlib import Path

DATA_DIR = Path("data")


def create_persona(name: str, files: dict[str, str]) -> str:
    persona_dir = DATA_DIR / name
    persona_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in files.items():
        (persona_dir / filename).write_text(content)

    return f"Created persona '{name}'."
