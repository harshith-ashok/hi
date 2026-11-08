# WhatsApp for hi: the open-source whatsapp-mcp project (a Go bridge that links to your WhatsApp as a
# "linked device", plus a Python MCP server), pinned to a reviewed commit and served to the backend
# over HTTP. Unofficial: WhatsApp's terms do not allow it and the number can be banned.
FROM golang:1.26-bookworm AS bridge
ARG REF=7d6a06dcdce1f01dfb24f60e1030d5efba9f3b88
RUN git clone https://github.com/lharries/whatsapp-mcp.git /src && git -C /src checkout $REF
WORKDIR /src/whatsapp-bridge
# the pinned whatsmeow is old; WhatsApp rejects outdated clients, so take the current release
# whatsmeow now takes a context first in these calls; patch the five call sites (each must match)
RUN go get go.mau.fi/whatsmeow@latest \
 && sed -i \
    -e 's/client\.Download(downloader)/client.Download(context.Background(), downloader)/' \
    -e 's/sqlstore\.New("sqlite3", /sqlstore.New(context.Background(), "sqlite3", /' \
    -e 's/container\.GetFirstDevice()/container.GetFirstDevice(context.Background())/' \
    -e 's/client\.GetGroupInfo(jid)/client.GetGroupInfo(context.Background(), jid)/' \
    -e 's/Contacts\.GetContact(jid)/Contacts.GetContact(context.Background(), jid)/' main.go \
 && [ "$(grep -c 'context.Background()' main.go)" -ge 5 ] \
 && go mod tidy && CGO_ENABLED=1 go build -o /bridge .

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
COPY --from=bridge /src/whatsapp-mcp-server /app/whatsapp-mcp-server
COPY --from=bridge /bridge /app/whatsapp-bridge/bridge
WORKDIR /app/whatsapp-mcp-server
RUN uv sync --frozen && uv pip install --python .venv/bin/python -U "mcp[cli]>=1.12,<2" # the locked mcp predates HTTP serving
COPY run.py start.sh ./
# session + message history live here (the hi-whatsapp volume)
VOLUME /app/whatsapp-bridge/store
CMD ["bash", "start.sh"]
