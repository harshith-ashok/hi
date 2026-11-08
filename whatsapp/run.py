"""Serve the whatsapp-mcp tools over HTTP (the project itself only speaks stdio)."""

from mcp.server.transport_security import TransportSecuritySettings

from main import mcp

mcp.settings.host = "0.0.0.0"
mcp.settings.port = 8778
# Only the backend reaches this container (no published ports); allow its name for the Host check.
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["whatsapp:8778", "whatsapp", "localhost:8778", "127.0.0.1:8778"],
    allowed_origins=[],
)
mcp.run(transport="streamable-http")
