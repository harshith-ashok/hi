#!/bin/bash
# The bridge keeps the WhatsApp connection (first run prints a QR code to scan); the MCP server
# gives the agent its tools. If either stops, the container exits and Docker restarts it.
cd /app/whatsapp-bridge && ./bridge &
cd /app/whatsapp-mcp-server && .venv/bin/python run.py &
wait -n
