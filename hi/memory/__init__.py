"""Everything `hi` remembers, as Markdown/JSONL files in the vault (the filesystem is the source of truth).

    vault.py        paths inside the vault, the knowledge-note tools, the conversation log
    records.py      record_turn(): the one call that writes a finished turn to every log
    journal.py      the day's activity journal      transcript.py   the full raw turn log
    extraction.py   durable facts learned per turn  reflection.py   daily reflection notes
    context.py      vault context injected into prompts (+ tree_cache, note_preview)
    skills.py       vault skills                    widgets.py      recallable UI widgets
    frontmatter.py  YAML frontmatter helpers
"""
