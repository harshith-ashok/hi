"""Work `hi` does without being asked: scheduled tasks, the heartbeat, the drop folder, and how their results reach you.

Layering: this package imports core, config, llm, memory and the Mac bridge client. It never imports hi.server:
the server hands it a `run_turn` function when the background jobs start (hi/startup.py), so automation can run
agent turns without knowing how they are served.
"""
