// Talks to hi/ipc/server.py (`hi --voice-daemon`) over loopback HTTP —
// the "Local IPC layer" TODO.md's Backend integration section asks for.
// One POST per query, streamed as AG-UI's own SSE event framing
// (TODO.md Phase 18 — `hi/agui_adapter.py`'s real, typed event stream,
// not this app's own hand-rolled `{event: persona/token/done}` NDJSON
// shape from before) read back via URLSession's async bytes API (no
// WebSockets needed for a strictly one-request/one-streamed-response
// protocol).
//
// `BackendEvent` only names the subset of AG-UI's real event types this
// panel actually renders something for today — text content, tool
// calls, subagent progress, the two custom events this project's own
// backend adds (persona_selected, spoken_summary), and an mcp-ui
// widget. Every other real AG-UI event type (STATE_DELTA, STEP_*,
// REASONING_*, ...) is parsed but intentionally dropped rather than
// forcing this enum to model AG-UI's entire schema up front — a
// future feature that wants one just adds a case, it doesn't need this
// file's parsing loop restructured.

import Foundation

enum BackendEvent {
    case personaSelected(name: String, tier: String, plan: Bool)
    case runStarted
    /// `subagentID` is set only for a Phase 16 orchestrated run's own
    /// per-task text (`hi/orchestrator/graph.py` delivers a subagent's
    /// whole result as one delta, not token-by-token — see
    /// `hi/agui_adapter.py`'s own docstring for why that's deliberate).
    /// nil for the normal single-agent flow's real per-token streaming.
    /// The distinction matters to the caller: only the nil case is the
    /// actual growing answer to show live — a subagent's own text is
    /// background progress, not the final answer, and mixing it into
    /// the visible turn would show a confusing jumble before
    /// `runFinished` corrects it to the real synthesized answer.
    case textDelta(String, subagentID: String?)
    case toolCallStart(name: String)
    case toolCallResult(content: String)
    case subagentStarted(id: String, name: String)
    case subagentFinished(id: String, result: String)
    case subagentError(id: String, message: String)
    case runFinished(result: String)
    case runError(message: String)
    case spokenSummary(text: String)
    case mcpUIWidget(uri: String, html: String)
    /// TODO.md Phase 20 ("approvals as generative UI"): a destructive
    /// action an orchestrated subagent is waiting on human approval for,
    /// arriving through the SAME SSE stream as everything else in this
    /// turn — not a separate poll, unlike PendingActionsMonitor.swift's
    /// existing menu-bar indicator (which still exists and still works;
    /// this is an additional, inline surface for the run that's actually
    /// producing it right now).
    case pendingAction(id: String, description: String)
    case pendingActionResolved(id: String, approved: Bool)
    /// The model's own real reasoning content, streamed live
    /// (`THINKING_START`/`THINKING_TEXT_MESSAGE_CONTENT`/`THINKING_END`
    /// — added to `hi/agui_adapter.py` alongside the web frontend's own
    /// support for this; this app just hadn't been updated to match
    /// yet). `thinkingStart`/`thinkingEnd` bracket a block; `.delta`
    /// carries each chunk of the actual text in between.
    case thinkingStart
    case thinkingDelta(String)
    case thinkingEnd
    case decodeError(String)
}

enum BackendClientError: Error {
    case notRunning
    case badResponse
}

/// TODO.md Phase 17: a destructive action an orchestrated subagent is
/// waiting on human approval for. Was always an empty list before
/// TODO.md Phase 18 — `hi/orchestrator/graph.py`'s DAG executor only
/// ran inside the terminal REPL's own process, never this app's
/// backend. Now that Phase 18 wires the orchestrator into
/// `hi/ipc/server.py`'s own `/query`, a plan triggered THROUGH THIS
/// APP can genuinely have a real pending action here — see
/// `hi/orchestrator/pending_server.py`'s docstring for why the
/// terminal REPL still needs its own separate copy of this queue too
/// (each process only ever holds actions from runs it triggered
/// itself, there's no single shared queue to expose from one place).
struct PendingActionInfo: Identifiable, Equatable {
    let id: String
    let description: String
    let createdAt: Double
}

struct BackendClient {
    var baseURL = URL(string: "http://127.0.0.1:8765")!

    /// True if hi --voice-daemon is up and answering at all — a real
    /// HTTP response (even a 400 for this empty-text ping) means the
    /// process is alive; a connection failure means it isn't. Used by
    /// BackendHealthMonitor for the menu bar status icon, not by query()
    /// itself, which surfaces its own connection failures per-request.
    func ping() async -> Bool {
        var request = URLRequest(url: baseURL.appendingPathComponent("query"))
        request.httpMethod = "POST"
        request.timeoutInterval = 2
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["text": ""])
        guard let (_, response) = try? await URLSession.shared.data(for: request) else {
            return false
        }
        return (response as? HTTPURLResponse) != nil
    }

    /// GET /briefing — the same pending-tasks/idle-repos/deadlines
    /// snapshot hi/repl.py's run_router_repl() shows once at session
    /// start, for the panel's briefing strip. Returns nil if there's
    /// nothing to surface, or on any failure (an unreachable backend
    /// shouldn't crash panel startup — the menu bar icon/error turn
    /// already covers "backend not running" for actual queries).
    func fetchBriefing() async -> BriefingInfo? {
        var request = URLRequest(url: baseURL.appendingPathComponent("briefing"))
        request.httpMethod = "GET"
        request.timeoutInterval = 15  // gathering + one haiku-tier call

        guard
            let (data, response) = try? await URLSession.shared.data(for: request),
            let http = response as? HTTPURLResponse, http.statusCode == 200,
            let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return nil
        }
        guard
            let context = obj["context"] as? String,
            let suggestion = obj["suggestion"] as? String,
            let action = obj["action"] as? String
        else {
            return nil  // the endpoint returns a bare `null` body when there's nothing to show
        }
        return BriefingInfo(context: context, suggestion: suggestion, action: action)
    }

    /// GET /pending — every destructive action currently awaiting
    /// approval (TODO.md Phase 17). Empty (not nil) on any failure —
    /// an unreachable backend or a decode miss both just mean "show
    /// nothing pending" for what's a nice-to-have indicator, not a
    /// required one.
    func fetchPendingActions() async -> [PendingActionInfo] {
        var request = URLRequest(url: baseURL.appendingPathComponent("pending"))
        request.httpMethod = "GET"
        request.timeoutInterval = 5

        guard
            let (data, response) = try? await URLSession.shared.data(for: request),
            let http = response as? HTTPURLResponse, http.statusCode == 200,
            let raw = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]]
        else {
            return []
        }
        return raw.compactMap { entry in
            guard
                let id = entry["id"] as? String,
                let description = entry["description"] as? String,
                let createdAt = entry["created_at"] as? Double
            else { return nil }
            return PendingActionInfo(id: id, description: description, createdAt: createdAt)
        }
    }

    /// GET /conversations — every logged conversation date, newest
    /// first (TODO.md "proper native app": a sidebar history list, the
    /// same dated logs hi/vault.py's log_conversation() already writes
    /// for every persona turn, on every surface — nothing new to store).
    /// Empty on any failure, same "nice-to-have indicator" posture as
    /// fetchPendingActions().
    func fetchConversationDates() async -> [String] {
        var request = URLRequest(url: baseURL.appendingPathComponent("conversations"))
        request.httpMethod = "GET"
        request.timeoutInterval = 5
        guard
            let (data, response) = try? await URLSession.shared.data(for: request),
            let http = response as? HTTPURLResponse, http.statusCode == 200,
            let dates = try? JSONSerialization.jsonObject(with: data) as? [String]
        else {
            return []
        }
        return dates
    }

    /// GET /conversations/{date} — that day's full logged conversation,
    /// raw Markdown (nil on any failure, including a genuinely missing
    /// date — the sidebar only ever offers dates fetchConversationDates()
    /// itself returned, so a miss here means the backend's vault changed
    /// out from under this session, not a normal case to recover from).
    func fetchConversation(date: String) async -> String? {
        var request = URLRequest(url: baseURL.appendingPathComponent("conversations/\(date)"))
        request.httpMethod = "GET"
        request.timeoutInterval = 5
        guard
            let (data, response) = try? await URLSession.shared.data(for: request),
            let http = response as? HTTPURLResponse, http.statusCode == 200,
            let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return nil
        }
        return obj["content"] as? String
    }

    /// GET /config — current model/vault-path settings for the Settings
    /// screen (TODO.md "proper native app"). MCP credentials are
    /// deliberately never included here — see hi/ipc/server.py's own
    /// _CONFIG_FIELDS comment; those stay write-only.
    func fetchConfig() async -> [String: String] {
        var request = URLRequest(url: baseURL.appendingPathComponent("config"))
        request.httpMethod = "GET"
        request.timeoutInterval = 5
        guard
            let (data, response) = try? await URLSession.shared.data(for: request),
            let http = response as? HTTPURLResponse, http.statusCode == 200,
            let obj = try? JSONSerialization.jsonObject(with: data) as? [String: String]
        else {
            return [:]
        }
        return obj
    }

    /// POST /config — writes the given fields to ~/.hi/.env. Returns a
    /// human-readable note from the backend (including its own "restart
    /// to take effect" caveat) on success, or nil on failure.
    func updateConfig(_ fields: [String: String]) async -> String? {
        var request = URLRequest(url: baseURL.appendingPathComponent("config"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: fields)
        guard
            let (data, response) = try? await URLSession.shared.data(for: request),
            let http = response as? HTTPURLResponse, http.statusCode == 200,
            let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return nil
        }
        return obj["note"] as? String
    }

    /// POST /tts — synthesizes `text` via Kokoro (hi/tts_kokoro.py) and
    /// returns real WAV audio bytes, or nil on failure (SpeechOutput
    /// falls back to silence rather than crashing on a synthesis
    /// hiccup). Replaces the on-device AVSpeechSynthesizer voice, per
    /// explicit request for TTS that "sounds actually like a human."
    func synthesizeSpeech(text: String) async -> Data? {
        var request = URLRequest(url: baseURL.appendingPathComponent("tts"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["text": text])
        request.timeoutInterval = 30
        guard
            let (data, response) = try? await URLSession.shared.data(for: request),
            let http = response as? HTTPURLResponse, http.statusCode == 200
        else {
            return nil
        }
        return data
    }

    /// POST /pending/{id}/approve|deny. Returns whether the server
    /// accepted it (a 204) — false for an already-resolved/unknown id,
    /// or any connection failure.
    func resolvePendingAction(id: String, approve: Bool) async -> Bool {
        let path = "pending/\(id)/\(approve ? "approve" : "deny")"
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.timeoutInterval = 5
        guard let (_, response) = try? await URLSession.shared.data(for: request) else {
            return false
        }
        return (response as? HTTPURLResponse)?.statusCode == 204
    }

    /// Streams events for one query. The backend daemon (hi --voice-daemon)
    /// must already be running — this client never launches it itself,
    /// same "nothing runs unless something explicit starts it" discipline
    /// as hi/perception/'s tools.
    ///
    /// - persona: forces a specific persona (the panel's tab row) instead
    ///   of letting the backend's own classify() pick one — nil for auto.
    func query(_ text: String, persona: String? = nil) -> AsyncThrowingStream<BackendEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var request = URLRequest(url: baseURL.appendingPathComponent("query"))
                    request.httpMethod = "POST"
                    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    var body: [String: Any] = ["text": text]
                    if let persona { body["persona"] = persona }
                    request.httpBody = try JSONSerialization.data(withJSONObject: body)

                    let (bytes, response) = try await URLSession.shared.bytes(for: request)
                    guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                        continuation.finish(throwing: BackendClientError.badResponse)
                        return
                    }

                    // AG-UI's own SSE framing: "data: <json>\n\n" — one
                    // event per non-blank "data: " line (the JSON body
                    // itself is always compact, single-line — no need
                    // to buffer across the blank separator line).
                    for try await line in bytes.lines {
                        guard line.hasPrefix("data: ") else { continue }
                        let jsonString = String(line.dropFirst(6))
                        if let event = Self.parse(jsonString) {
                            continuation.yield(event)
                        }
                    }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: BackendClientError.notRunning)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// Returns nil for a real, known AG-UI event type this panel just
    /// doesn't render anything for yet (STATE_DELTA, STEP_*,
    /// REASONING_*, ...) — not an error; `.decodeError` is reserved for
    /// a genuine parse failure (malformed JSON, or a `type` this SDK
    /// version doesn't even define).
    private static func parse(_ jsonString: String) -> BackendEvent? {
        guard
            let data = jsonString.data(using: .utf8),
            let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let type = obj["type"] as? String
        else {
            return .decodeError(jsonString)
        }

        switch type {
        case "CUSTOM":
            return Self.parseCustomEvent(obj)
        case "RUN_STARTED":
            return .runStarted
        case "THINKING_START":
            return .thinkingStart
        case "THINKING_TEXT_MESSAGE_CONTENT":
            return .thinkingDelta(obj["delta"] as? String ?? "")
        case "THINKING_END":
            return .thinkingEnd
        case "TEXT_MESSAGE_CONTENT":
            return .textDelta(obj["delta"] as? String ?? "", subagentID: obj["subagentRunId"] as? String)
        case "TOOL_CALL_START":
            return .toolCallStart(name: obj["toolCallName"] as? String ?? "?")
        case "TOOL_CALL_RESULT":
            return .toolCallResult(content: obj["content"] as? String ?? "")
        case "SUBAGENT_STARTED":
            return .subagentStarted(id: obj["subagentRunId"] as? String ?? "?", name: obj["name"] as? String ?? "?")
        case "SUBAGENT_FINISHED":
            return .subagentFinished(id: obj["subagentRunId"] as? String ?? "?", result: obj["result"] as? String ?? "")
        case "SUBAGENT_ERROR":
            return .subagentError(id: obj["subagentRunId"] as? String ?? "?", message: obj["message"] as? String ?? "")
        case "RUN_FINISHED":
            return .runFinished(result: obj["result"] as? String ?? "")
        case "RUN_ERROR":
            return .runError(message: obj["message"] as? String ?? "")
        default:
            return nil
        }
    }

    private static func parseCustomEvent(_ obj: [String: Any]) -> BackendEvent? {
        guard let name = obj["name"] as? String, let value = obj["value"] as? [String: Any] else {
            return nil
        }
        switch name {
        case "persona_selected":
            return .personaSelected(
                name: value["name"] as? String ?? "?",
                tier: value["tier"] as? String ?? "?",
                plan: value["plan"] as? Bool ?? false
            )
        case "spoken_summary":
            return .spokenSummary(text: value["text"] as? String ?? "")
        case "mcp_ui_widget":
            guard let uri = value["uri"] as? String, let text = value["text"] as? String else { return nil }
            return .mcpUIWidget(uri: uri, html: text)
        case "pending_action":
            guard let id = value["id"] as? String, let description = value["description"] as? String else { return nil }
            return .pendingAction(id: id, description: description)
        case "pending_action_resolved":
            guard let id = value["id"] as? String else { return nil }
            return .pendingActionResolved(id: id, approved: value["approved"] as? Bool ?? false)
        default:
            return nil
        }
    }
}
