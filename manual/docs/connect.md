---
title: Connect
---

# Connect

miAssist speaks the Model Context Protocol over streamable HTTP. Add it to your client as a remote
MCP server at your installation's address. No login and no token are needed: if your client asks
for one, leave it empty.

## Two address forms

- `https://<your installation>/mcp`: works at once. miAssist explains things at the beginner level
  and remembers nothing for you.
- `https://<your installation>/p/<your-key>/mcp`: a personal link. miAssist remembers your guidance
  level and playbook progress for this key. Open `https://<your installation>/p/new` in a browser to
  get one; the page shows the full address to paste.

The key only selects your settings. It is not a password, every key sees the same tools, and
anyone with your link sees your settings, so treat it like a bookmark rather than a secret.

## Clients

### Claude (claude.ai and Claude Desktop)

Add a custom connector and paste the address (either form) as its URL. Leave any authentication
settings empty.

### Claude Code

Add an HTTP MCP server with the address, for example
`claude mcp add --transport http miassist https://<your installation>/p/<your-key>/mcp`.

### Open WebUI

An administrator adds miAssist once, as an MCP tool server using streamable HTTP, with the address.
Each person then turns it on in their chat. A personal link added by the administrator is shared
by everyone who uses that server entry, so most installations add the plain `/mcp` form.

### Other MCP clients

Any client that supports remote MCP servers over streamable HTTP can connect with the same
address. Some web interfaces need an administrator to add the server.

## Check the connection

Ask your assistant to call `miassist_guide`. It answers with the apps this installation has and
the playbooks on offer.
