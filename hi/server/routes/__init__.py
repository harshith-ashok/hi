"""One module per area; each exports `routes`. Order matters only where paths overlap
(/agents/presets and /agents/mcp-servers must be listed before /agents/{run_id})."""

from hi.server.routes import agents, approvals, artifacts, config, dashboard, files, inbox, mcp, memory, projects, query, sessions, skills, suggest, voice

# mcp's /agents/mcp-servers comes before agents' /agents/{run_id}
ALL = [*query.routes, *config.routes, *memory.routes, *dashboard.routes, *voice.routes,
       *mcp.routes, *agents.routes, *files.routes, *approvals.routes, *inbox.routes, *sessions.routes, *skills.routes, *suggest.routes, *artifacts.routes, *projects.routes]
