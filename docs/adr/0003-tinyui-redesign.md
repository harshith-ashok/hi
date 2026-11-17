# 0003: The tinyui redesign and chat sessions (2026-11-17)

Context: tinyui was one long chat with a hand-drawn terminal look, a single global conversation, a "routing" and
"thinking" pill for progress, and no way to keep, name or revisit chats. The goals: a visual interface (diagrams, images),
real progress while the assistant works, and proper chat management.

Decisions:

1. **shadcn-vue on Tailwind v4, staying in Vue.** shadcn is a React-first library; its Vue port keeps the whole app (the
   streaming, voice and attachment code) in one framework. Components are copied into `src/components/ui/`.
2. **Sessions are notes in the vault** (`hi/sessions/<id>.md`), and every turn in the transcript carries its session id.
   History, titles, pin, archive, delete and search all derive from those files. A session's title is the first words of
   its first question, replaced by a model-written one (never over a title you set).
3. **Each session has its own agent** (the agent cache is bounded, LRU): `term` remembers its conversation, so sessions
   must not share one. History for a session is filtered by its id.
4. **Progress is derived in the browser from event times**, not from new server events. Every block records when it
   started and ended; the timeline is a function of those. The server adds only the events it alone knows about (drawing
   a diagram). A restored session shows the total, not step times, because those were not saved.
5. **Diagrams are Mermaid, drawn client-side, loaded on demand.** A model's own ` ```mermaid ` block is drawn in place
   (an unfinished fence shows a skeleton while it streams). With Visualize on, the backend asks a small model for one
   diagram after the answer (skipped when the answer already has one), checks it is a known diagram type, and saves it
   with the turn. A diagram that fails to parse shows the error and the code, never breaks the reply.
6. **A stopped reply is kept.** Closing the stream records the turn with what was said and `error="stopped"`, so the
   question and partial answer survive in the session. Untitled sessions that stay empty are hidden after ten minutes.
7. **The clarifying form (`ask_user`) is part of the chat**, answered by sending the answers as the next message.

Consequences: the tinyui bundle is about 160 KB gzipped plus Mermaid on demand; `hi/server/routes/sessions.py` adds
`/sessions` and `/visual`; the destructive routes need the `X-Hi-Client` header (ADR 0002).
