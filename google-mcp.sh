#!/bin/sh
# Starts the Google Workspace MCP server with the OAuth client from your ~/.hi/.env
# (docker-compose.yml mounts that file at /run/hi-host.env), so the credentials live in one place.
FILE=/run/hi-host.env
for key in GOOGLE_OAUTH_CLIENT_ID GOOGLE_OAUTH_CLIENT_SECRET; do
  value=$(sed -n "s/^${key}=//p" "$FILE" 2>/dev/null | tail -n 1 | sed -e "s/^[\"']//" -e "s/[\"']\$//")
  if [ -n "$value" ]; then
    export "${key}=${value}"
  fi
done
exec workspace-mcp --single-user --transport streamable-http
