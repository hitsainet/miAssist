# miAssist

miAssist is one MCP server that guides a person through the miStudio suite of mechanistic
interpretability apps: miWorkbench, miServer, miDataworks and miForge.

**Any combination, without complaint.** miAssist works with whichever of the four apps an
installation has. It offers only what is installed, and it never tells you to install something else.

**Only ever an agent.** miAssist calls each app's REST API as an agent. Anything that costs money,
uses the GPU(s) available, publishes, arms or activates waits for the app's own operator, in that app.
miAssist cannot approve anything.

## Connect

Add miAssist to your MCP client as a remote server at your installation's address ending in `/mcp`.
No token is needed. For a link that remembers your guidance level, open `/p/new`.

## Run it

```bash
cp .env.example .env     # set POSTGRES_PASSWORD, MIASSIST_APPS and each listed app's URL
docker compose up -d
```

Or for development: `pip install -e ".[dev]"`, then `pytest`.

## Manual

The manual is published at https://hitsainet.github.io/miAssist/.

## License

MIT. See `LICENSE`.
