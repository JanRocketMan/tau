# Project trust and security

Tau resolves trust for the canonical destination cwd before reading ambient
project Markdown/JSON or importing project extensions. Protected inputs include
project skills, prompts, themes, system-prompt files, AGENTS.md context,
extension candidates, and reserved future project settings/package metadata.
User/global and explicit CLI resources remain eligible.

Interactive users can save exact or displayed-parent decisions or choose a
run-only result. `~/.tau/trust.json` is a locked, atomically replaced version-1
store. `defaultProjectTrust` in user `~/.tau/settings.json` is `ask`, `always`,
or `never`; headless `ask`/`never` decline. `--approve` and `--no-approve` are
run-only. Cancelling the interactive startup decision exits Tau; continuing
without project inputs requires selecting a decline option. Trusted project
extensions additionally require `--project-extensions`.

Project trust is only an input-loading guard. It is not a filesystem, process,
shell, network, tool, credential, provider, model, package-install,
prompt-injection, or exfiltration sandbox. Use OS/container/VM isolation and
restricted credentials/network when isolation is required.

## Web search

When a search-provider API key is set (`PARALLEL_SEARCH_API_KEY` by default,
or `BRAVE_SEARCH_API_KEY` for migrated setups), Tau registers a `search` tool
that lets the model send search queries to the configured provider's web-search
API. Queries may contain text derived from your prompt or repository, and
returned snippets enter the agent's context as untrusted external content that
may carry prompt-injection attempts. The tool description and prompt guidelines
tell the model never to search for secrets, credentials, or private source
code.

The API key is read from the process environment at startup. It is never a
model-visible tool argument, never written to session history, and is redacted
from tool error output. The optional `PARALLEL_SEARCH_API_URL` and
`BRAVE_SEARCH_API_URL` overrides are process configuration intended for tests;
remove them where strict egress control is required.

Published details: `website/content/guides/project-trust.md`.
