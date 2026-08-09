# Brave Search tool

Tau now ships an optional fifth built-in tool, `brave_search`, that queries the
Brave Web Search API. It gives the agent current, external information
(documentation, error messages, releases) without coupling a third-party search
service to the portable agent harness.

## What was added

- `src/tau_coding/brave_search.py` holds all Brave-specific logic: an immutable
  `BraveSearchConfig` (`api_key`, `endpoint`, `timeout_seconds`) with a
  `from_env()` resolver, argument validation, the transport-injectable HTTP
  request helper, result normalization, and text formatting.
- `src/tau_coding/tools.py` only constructs the `AgentTool`
  (`create_brave_search_tool`) and appends it in `create_coding_tools` when a
  config is passed. `tau_agent` stays free of provider- and service-specific
  code, matching the Pi-style separation: the harness sees an ordinary typed
  tool with a JSON schema and an async executor.
- `CodingSessionConfig.brave_search` threads the config through sessions
  (including `/reload` staging and `resume`), and both entry edges
  (`cli.py` print mode, `tui/app.py` startup) resolve it once via
  `BraveSearchConfig.from_env()`.

## Why it exists

Web search is opt-in because it creates a new outbound data path: the model's
query text is sent to Brave. The tool is therefore registered only when
`BRAVE_SEARCH_API_KEY` is present; without it, sessions keep the original
`read`/`write`/`edit`/`bash` set and no test or offline run changes behavior.

Design choices worth knowing:

- The key is process configuration, never a model-visible tool argument, and is
  defensively redacted from error bodies before they reach the model or session
  history.
- Invalid arguments raise `ValueError` before any network access; the agent
  loop's tool-isolation boundary surfaces the message to the model. Operational
  failures (timeout, transport error, HTTP 401/403/422/429/5xx, malformed JSON)
  return bounded error results instead, so the model can recover. There are no
  automatic retries, so a 429 cannot turn into a quota-burning loop.
- Responses are normalized down to title, URL, description, age, and extra
  snippets, and formatted as provider-neutral text plus structured `details`
  for renderers and tests.

## How to test or use it

```bash
export BRAVE_SEARCH_API_KEY="..."   # required; Tau does not read .env files
tau                                 # or: tau --print "..."
```

Then ask for something current, e.g. "Search the web for the Python 3.14
release notes and summarize the highlights with source URLs."

Automated coverage lives in `tests/test_brave_search.py` and runs entirely
through `httpx.MockTransport` (no network, no quota): config resolution, schema
shape, request headers/params, result formatting, corrected queries, argument
validation, HTTP/transport/timeout errors, and API-key redaction.
