---
title: Configuration & files
description: Where Tau stores state, and the shape of its config files.
---

Tau keeps durable state in your home directory (`~/.tau/`) and reads
project-local resources from your working directory. This page is a reference for
those locations and file formats.

## Tau home

Tau keeps durable state in your home directory (`~/.tau/`), reads
project-local resources from your working directory, and keeps all provider
configuration in the packaged catalog. This page is a reference for those
locations and file formats.

```text
~/.tau/
├── credentials.json    # saved API keys / OAuth tokens (0600, atomic writes)
├── settings.json       # general settings (trust default, shell prefix)
├── trust.json          # versioned project-input trust decisions
├── sessions/           # saved sessions, per project
├── logs/               # diagnostics
└── (optional user resources: prompts/, themes/, SYSTEM.md,
    APPEND_SYSTEM.md, AGENTS.md)
```

There is **no user-level provider configuration** in Tau home: provider
definitions, display labels, the default provider/model, and per-provider
runtime preferences all live in the single packaged catalog file
`src/tau_coding/data/catalog.toml`. Tau never reads or writes `providers.json`,
`tui.json`, or a user-level `catalog.toml`; you can delete any leftover files.

User skills are shared with Claude Code from `~/.claude/skills/` instead of
`~/.tau/skills/`.

Tau also reads user-level `.agents` resources: `~/.agents/skills/`,
`~/.agents/prompts/`, `~/.agents/AGENTS.md`.

`settings.json` may contain `"defaultProjectTrust": "ask" | "always" |
"never"`. It is user-global only; a project cannot choose its own trust
policy. The default is `ask`. Interactive `ask` opens the trust modal; headless
`ask` safely declines. `trust.json` is managed atomically by Tau; do not add
relative paths or unknown fields. See [Project trust]({{< relref
"../guides/project-trust.md" >}}).

Tau does not check for updates or contact a package index at startup. The local
`~/.tau/logs/release-notes-state.json` file records which bundled release notes
the TUI has shown.

`~/.tau/logs/agent-calls.jsonl` contains structured failure diagnostics. Each
JSONL entry identifies the provider, model, session, working directory, and
failure phase. Remote OpenAI Codex compaction failures use phase
`remote_compaction`. Tau does not write provider request content or credentials
to this log

## System prompt files

Tau can replace or extend its generated system prompt with Tau-native Markdown
files:

```text
~/.tau/SYSTEM.md                 # user replacement
~/.tau/APPEND_SYSTEM.md          # user append
<project>/.tau/SYSTEM.md         # project replacement
<project>/.tau/APPEND_SYSTEM.md  # project append
```

For each kind, precedence is explicit CLI input, then the project file, then the
user file. A higher-precedence append file replaces the lower-precedence append
file; Tau does not concatenate project and user files. Replacement content still
receives the selected append text, project instructions, eligible skills, the
current date, and the working directory. Empty files are valid explicit values.

Run `/reload` after adding, changing, or removing a file. Tau rebuilds the prompt
for the next model request without adding it to session history. `/session`
resource diagnostics identify selected, shadowed, or CLI-overridden files. A
selected file that cannot be inspected or decoded as UTF-8 stops startup or
reload rather than silently falling back.

System prompt files are Tau-specific and are not discovered from `.agents`.
Project files load only after the destination cwd is trusted. User files and
explicit CLI values remain available when project inputs are declined. Trust is
an input-loading guard, not a sandbox; inspect trusted prompt files because they
can replace or extend the model's highest-priority instructions.

## Network proxies

Tau uses `httpx` for provider requests and OAuth token refreshes, so it honors
standard proxy environment variables such as `HTTP_PROXY`,
`HTTPS_PROXY`, `ALL_PROXY`, and `NO_PROXY`.

SOCKS proxies are supported by the base installation. Use explicit schemes when
you can:

```bash
export ALL_PROXY=socks5://127.0.0.1:1080
# or, when proxy-side DNS resolution is required:
export ALL_PROXY=socks5h://127.0.0.1:1080
```

Tau also accepts the generic `socks://` form that some systems and tools set in
the environment. Before creating its own HTTP clients, Tau normalizes
`socks://...` to `socks5://...` because `httpx` does not recognize the generic
scheme directly.

This matters for users behind corporate proxies, VPNs, local tunnels, or
privacy/network-routing setups: without SOCKS support and normalization, Tau can
fail before making a model API request with an error like
`Unknown scheme for proxy URL URL('socks://...')`.

## Providers

All provider configuration lives in the single packaged catalog file
`src/tau_coding/data/catalog.toml`. Tau only **reads** the catalog; edit the
file directly to change providers, the default provider, or preferences.
Runtime model or thinking changes apply to the active session only, and
`/login` writes credentials to `~/.tau/credentials.json` without touching the
catalog, so the catalog cannot be overridden from inside Tau. To point Tau at a
different catalog file (for example when the package directory is not
writable), set the `TAU_CATALOG_PATH` environment variable.

There is intentionally **no project-level** catalog: cloning a repository
cannot silently redirect a provider's `base_url` or credentials to an
unexpected service.

### Editing the catalog

Add or edit a provider directly in `src/tau_coding/data/catalog.toml`:

```toml
schema_version = 1

[provider_labels]
openai-codex = "codex"

[[providers]]
name = "local-gateway"
display_name = "Local Gateway"
kind = "openai-compatible"
base_url = "http://localhost:11434/v1"
api_key_env = "LOCAL_GATEWAY_API_KEY"
credential_name = "local-gateway"
models = ["qwen-coder"]
default_model = "qwen-coder"
docs_url = "https://example.test/local-gateway"

[providers.context_windows]
qwen-coder = 64000
```

`provider_labels` is an optional mapping from a canonical provider ID to the
short label shown in the TUI status block and model picker. For example,
`openai-codex = "codex"` displays `codex:<model>` but keeps `openai-codex` for
routing, credentials, CLI arguments, and saved session metadata. Labels must
refer to providers in the catalog, must be non-empty and unique, and must not
equal another provider's canonical ID.

The `default_provider` root key names the provider used when no explicit
selection is given. A `[[providers]]` entry's `default_model` selects that
provider's starting model.

Catalog entries support `kind` values of `openai-compatible` and
`openai-codex`. For most custom services, start with `openai-compatible`.

`removed_models` is an additive provider-scoped tombstone list. Tau applies it
last and removes matching model-list, metadata, context-window, thinking, and
default references. Bundled tombstones therefore prevent stale models from
being advertised for the wrong provider. They do not affect the same model ID
on another provider.

### OpenAI prompt-cache compat keys

Tau enables OpenAI cache affinity automatically only for `api.openai.com` and the
dedicated Codex OAuth provider. OpenAI-compatible gateways can opt in per provider
or model:

| Key | Effect |
| --- | --- |
| `supportsPromptCacheKey` | Sends the stable session-derived `prompt_cache_key` body field |
| `sendSessionAffinityHeaders` | Sends headers using `sessionAffinityFormat` |
| `sessionAffinityFormat` | `openai` sends `session_id`; `openrouter` sends `x-session-id` |

Unknown gateways retain their existing request shape by default. Enable only fields
documented by the target service. Codex uses its dedicated `session-id` header
mapping and does not read these OpenAI-compatible settings.

### Anthropic prompt-cache compat keys

Providers using the `anthropic-messages` API accept three `compat` booleans
controlling prompt caching. All default to enabled, except that `cache_control` is
detected as unsupported for any base URL that is not `api.anthropic.com`, since
several providers speak the Anthropic protocol through a gateway.

| Key | Effect when `false` |
| --- | --- |
| `supportsCacheControl` | No cache breakpoints at all; the request is byte-identical to an uncached one |
| `supportsLongCacheRetention` | Clamps the 1 hour TTL to the 5 minute default |
| `supportsCacheControlOnTools` | Drops only the tool-schema breakpoint |

Set them per provider or per model. For example, to stop requesting the one-hour
cache on a Claude subscription:

```toml
schema_version = 1
[[providers]]
name = "anthropic"
compat = { supportsLongCacheRetention = false }
```

Thinking support is declared strictly in model metadata. A `[[providers]]` entry
may set `thinking_parameter` (the request field used to change effort:
`"reasoning_effort"`, `"reasoning.effort"`, or `"anthropic.thinking"`); it must
not set provider-level `thinking_levels`, `thinking_models`, or
`thinking_default`. Every `[providers.model_metadata.<model>]` entry declares
exactly two thinking fields: `thinking_levels` (the Tau levels the model
accepts, sent verbatim as the parameter value) and `thinking_default` (a member
of that list used when no preference is remembered).

`catalog.toml` also stores runtime preferences directly on the matching
`[[providers]]` entry: `headers`, `thinking_defaults`, `timeout_seconds`,
`stream_idle_timeout_seconds`, `max_retries`, `max_retry_delay_seconds` (and
`inference_providers` for the Hugging Face provider). See
[Provider preferences](#provider-preferences) below.

Invalid catalog files fail loudly. Tau rejects unknown keys, empty required
strings, empty model names, unsupported provider kinds, default models that are
not listed in `models`, `context_windows` entries for unknown models, and
non-positive or non-integer context-window values.

Model metadata can retain a backward-compatible flat `cost` and optionally
provide ordered `cost_tiers` for rates that depend on input size:

```toml
[providers.model_metadata."long-context-model"]
cost = { input = 0.3, output = 1.2, cacheRead = 0.06, cacheWrite = 0 }
cost_tiers = [
  { max_input_tokens = 512000, input = 0.3, output = 1.2, cacheRead = 0.06, cacheWrite = 0 },
  { input = 0.6, output = 2.4, cacheRead = 0.12, cacheWrite = 0 },
]
```

Limits are inclusive, must increase strictly, and the final tier must omit
`max_input_tokens` so every valid input size has a rate. Callers that understand
tiers should select the first tier whose limit includes the input-token count;
older callers continue to see `cost` as the base rate.

All rates are per million tokens. `cacheWrite` is the 5-minute cache-write
rate; entries may add an optional `cacheWrite1h` rate for Anthropic's 1-hour
TTL cache writes, which Anthropic bills higher. When `cacheWrite1h` is absent,
1-hour writes fall back to the `cacheWrite` rate.

### Provider preferences

Per-provider runtime preferences live directly in
`src/tau_coding/data/catalog.toml` on the matching `[[providers]]` entry:

```toml
default_provider = "local-gateway"

[[providers]]
name = "local-gateway"
display_name = "Local Gateway"
kind = "openai-compatible"
base_url = "http://localhost:11434/v1"
api_key_env = "LOCAL_GATEWAY_API_KEY"
credential_name = "local-gateway"
models = ["qwen-coder"]
default_model = "qwen-coder"
docs_url = "https://example.test/local-gateway"
timeout_seconds = 120.0
stream_idle_timeout_seconds = 600.0
max_retries = 2
max_retry_delay_seconds = 0.5
headers = { "X-Provider-Header" = "value" }
thinking_defaults = { qwen-coder = "low" }
```

- `default_provider` (a root key) names the provider Tau starts with when
  nothing else is selected. `default_model` on a provider entry selects that
  provider's starting model. Preference keys that are absent keep their
  defaults. Tau never rewrites this file: model or thinking changes made at
  runtime apply to the active session only, and you update defaults by editing
  the catalog directly.
- `headers` is optional (string→string). For example, Hugging Face organization
  billing can be configured with `headers = { "X-HF-Bill-To" = "my-org" }` on
  the `huggingface` provider entry. `thinking_defaults` remembers the preferred
  thinking level per model for new sessions; resumed sessions still use their
  session history. The `huggingface` provider also accepts
  `inference_providers = { "zai-org/GLM-5.2" = "deepinfra" }`. Each key must be
  a configured model and each value an explicit provider suffix advertised by
  Hugging Face—not the `fastest`, `cheapest`, or `preferred` routing policies.
  Tau snapshots the selected suffix into new session metadata, retains it on
  resume, and sends only the suffixed wire model; ordinary model identity and
  catalog metadata remain unsuffixed. Without a preference, Tau starts with
  automatic routing and pins the `x-inference-provider` reported by the first
  successful response. `/session` reports the route; `/route <provider>` selects
  one and `/route automatic` resets automatic resolution for the active session.
- `timeout_seconds` defaults to `60` (> 0) for connection, request-write, and
  connection-pool inactivity. `stream_idle_timeout_seconds` defaults to `600`
  (> 0) and limits the interval between chunks on an established response
  stream; it is not a total turn deadline, and heartbeat chunks reset it.
  `max_retries` defaults to `2`; `max_retry_delay_seconds` defaults to `1`
  (both ≥ 0). The maximum delay is a cap, not a fixed wait: backoff starts at
  `0.25` seconds and doubles until it reaches the cap. Retries cover transient
  HTTP statuses (`408`, `409`, `425`, `429`, `5xx`), transport errors, and
  transient in-stream SSE errors that arrive on an otherwise successful HTTP
  200 response. Anthropic retries `api_error`, `overloaded_error`, and
  `rate_limit_error`; OpenAI Codex retries transient events such as
  `server_is_overloaded`. In-stream errors remain terminal after partial visible
  content to prevent duplicate output or tool calls. Tau also validates terminal
  OpenAI-compatible finish reasons and retries a request-level
  `insufficient_system_resource` or missing finish reason when no output has
  started. If any model ends after reasoning without text or a tool call, the
  agent sends one bounded continuation instead of requiring a manual `continue`
- API keys and OAuth credentials are **not** stored in the catalog — they live
  in `~/.tau/credentials.json` (private but not encrypted). OAuth objects may
  contain provider metadata such as a GitHub Enterprise domain and are refreshed
  automatically. Resolution order: stored credential, then the env
  var named by `api_key_env`.
- The selected model must be present in that provider's `models` list. Add
  custom or local model names to `models` before using them as defaults or
  CLI/TUI selections.
- **Ctrl+P** quick-cycles every model across all providers with usable
  credentials: the default provider leads with its `default_model`, then its
  remaining models, then each other provider's `default_model` and models.
  There are no scoped-model favorites; the cycle list is derived from the
  catalog.
- Custom models declare thinking support in `catalog.toml` model metadata with
  `thinking_levels` and `thinking_default`, and set the wire parameter
  (`"reasoning_effort"`, `"reasoning.effort"`, or `"anthropic.thinking"`) with
  the provider-level `thinking_parameter`.

Tau never writes the catalog. `/login` stores credentials in
`~/.tau/credentials.json`; all provider configuration changes are made by
editing `src/tau_coding/data/catalog.toml` by hand.

See the [Providers & models guide]({{< relref "../guides/providers-and-models.md" >}}) for usage.

## Shell settings

Tau runs shell commands in a **non-interactive** shell — both terminal-input
commands (`! gst`, `!! ll`) and the agent's `bash` tool. Non-interactive shells
don't load your aliases from `~/.zshrc` or `~/.bashrc`, and Tau deliberately
never reads those files (they can hold tokens and side effects).

To make your own aliases available, opt in with a `shellCommandPrefix` in
`~/.tau/settings.json` that loads a small Tau-specific alias file:

```bash
# ~/.tau/shell-aliases.bash
alias gst='git status'
alias ga='git add'
alias gc='git commit'
```

```json
{
  "shellCommandPrefix": "shopt -s expand_aliases\nsource ~/.tau/shell-aliases.bash"
}
```

Then start a new session and try `! gst`. Notes:

- Commands run through bash-style non-interactive execution, so keep aliases
  POSIX/bash-compatible (zsh-only syntax, functions, or interactive startup
  logic may not work).
- Changing `settings.json` affects **new** sessions; an already-running session
  keeps the prefix it started with.
- The snake_case key `shell_command_prefix` is also accepted.
- Unrecognized fields are ignored for compatibility with newer Tau versions;
  recognized fields remain strictly validated.

## Web search

Tau can register an optional `search` tool backed by a configurable web-search
provider. It is disabled by default and enabled only when the selected
provider's API key is present in the process environment. The default provider
is [Parallel Search](https://docs.parallel.ai/api-reference/search/search),
running in Fast mode; [Brave Search](https://brave.com/search/api/) remains
available as a migration alternative.

| Variable | Required | Description |
| --- | --- | --- |
| `TAU_SEARCH_PROVIDER` | no | Provider name: `parallel` (default) or `brave`. |
| `PARALLEL_SEARCH_API_KEY` | no | Parallel Search API key (enables the `search` tool). |
| `PARALLEL_SEARCH_API_URL` | no | Parallel endpoint override, intended for tests. |
| `PARALLEL_SEARCH_TIMEOUT_SECONDS` | no | Parallel request timeout, > 0 (default `20`). |
| `PARALLEL_SEARCH_MODE` | no | Parallel search mode: `turbo`, `fast` (default), `basic`, `advanced`. |
| `BRAVE_SEARCH_API_KEY` | no | Brave Search API subscription key. |
| `BRAVE_SEARCH_TIMEOUT_SECONDS` | no | Brave request timeout, > 0 (default `20`). |
| `BRAVE_SEARCH_API_URL` | no | Brave endpoint override, intended for tests. |

`PARALLEL_API_KEY` (the name used in Parallel's own docs and SDKs) is accepted
as a fallback for `PARALLEL_SEARCH_API_KEY`. For a smooth migration, when
`TAU_SEARCH_PROVIDER` is unset and only a Brave key is configured, Tau falls
back to the Brave provider so existing setups keep searching.

Tau does **not** read `.env` files. Export the variables in your shell profile
(`~/.zshrc`, `~/.bashrc`), set them inline
(`TAU_SEARCH_PROVIDER=parallel PARALLEL_SEARCH_API_KEY=... tau`), or use a tool
like `direnv` that injects real environment variables. Restart Tau after
changing them; new sessions pick up the values. A malformed timeout or an
unknown provider/mode fails loudly at startup.

The key is sent to the provider (in `x-api-key` for Parallel, in
`X-Subscription-Token` for Brave). It is never a model-visible tool argument,
never written to session history, and is redacted from error output. Do not
commit it to Git or put it in project files. See
[Built-in tools]({{< relref "./tools.md" >}}) for tool behavior.

## TUI settings

The built-in frontend uses built-in defaults only; there is no `tui.json` file
and no other TUI settings file. Keybindings:

```text
cancel: escape        command_palette: ctrl+k   session_picker: ctrl+r
open_context: ctrl+l  queue_follow_up: alt+enter  accept_completion: tab
completion_next: down completion_previous: up    thinking_cycle: ctrl+f
model_cycle: ctrl+p   toggle_thinking: ctrl+t    toggle_tool_results: ctrl+o
clear_prompt: ctrl+u  quit: ctrl+d
```

Built-in themes: `codeyellow` (default), `tau-light`, `tau-dark`,
`high-contrast`. Custom themes are JSON files in `~/.tau/themes/` or a
project's `.tau/themes/` — see [Themes]({{< relref "../guides/themes.md" >}}).
Set one with `/theme`; the choice applies to the current session (it is not
persisted). `Ctrl+C` is reserved as the hard stop key and is not remappable.

- `turn_notification`: `"desktop"` (default), `"bell"`, or `"off"`. When Tau's
  terminal surface is unfocused and the agent becomes fully idle, `"desktop"`
  selects OSC 9 for Ghostty, iTerm2, and MinTTY, or Kitty's OSC 99 protocol for
  Kitty. Unknown terminals receive no sequence rather than an incompatible one.
  `"bell"` explicitly emits the standard terminal bell so the terminal can mark
  the tab or request attention instead; depending on terminal settings, BEL may
  play a sound. Desktop notifications can also use the operating system's
  configured notification sound. No notification is emitted while Tau has focus.

Full list in [Keyboard shortcuts]({{< relref "./keybindings.md" >}}).

## Sessions

```text
~/.tau/sessions/<cleaned-path>-<short-hash>/
```

Each working directory gets its own subdirectory; transcripts are append-only
JSONL preserving messages, model changes, and the active leaf of the session
tree. Metadata is indexed per project. See the
[Sessions guide]({{< relref "../guides/sessions.md" >}}).

## Skills, prompts & project context

Resource discovery order (later overrides earlier) is documented in
[Skills & prompt templates]({{< relref "../guides/skills-and-prompts.md" >}}) and
[Project instructions]({{< relref "../guides/project-instructions.md" >}}). In short: user-level
`~/.tau` and `~/.agents`, then project-level `.tau` and `.agents`, with
`AGENTS.md` discovered from the project root down to your current directory.

## Context

`/session` reports a rough context estimate and breakdown. Auto-compaction
triggers near the model's context window minus a reserve; override per run with
`--auto-compact-threshold`. Details in [Managing context]({{< relref "../guides/context.md" >}}).
