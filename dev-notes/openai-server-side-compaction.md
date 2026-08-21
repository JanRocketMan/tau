# OpenAI Codex server-side compaction (Path A prototype)

## What was added

A provider-native sidecar artifact for compactions, mirroring the protocol
used by OpenAI Codex (`compaction_trigger` + opaque `compaction` item on the
Codex subscription Responses backend) and studied from the reference
extension `algal/pi-openai-server-compaction`.

The portable text summary stays the source of truth. The remote artifact is
best-effort: during any compaction (manual `/compact`, auto threshold, or
overflow retry), `CodingSession` runs the text-summary generation and the
remote compaction call in parallel. If the remote call fails, is skipped
(provider not eligible or no credentials), or the provider is not the
`openai-codex` subscription provider, the compaction behaves exactly as
before - just a text summary.

## Key decision: codex-only scope

The new behavior activates **only** for the `openai-codex` subscription
provider (the `OpenAICodexProviderConfig` config behind `chatgpt.com/backend-api`).
Every other setup - direct OpenAI-compatible providers, Chat Completions
models, Anthropic, Hugging Face, OAuth-backed providers - keeps the old
text-summary-only behavior. The reference extension also supports direct
`api.openai.com` Responses models; that scope is deliberately deferred here.

## Where the pieces live

- `tau_ai/openai_remote_compaction.py` - the wire protocol: message-to-items
  conversion, Codex compaction headers (`chatgpt-account-id`, `originator`,
  `OpenAI-Beta`, `x-codex-installation-id`/`x-codex-window-id`, and the
  `remote_compaction_v2` beta-feature flag that enables the v2 protocol),
  payload build with the trailing `compaction_trigger`, SSE parsing, usage
  normalization, retained-user-message replacement history, and the async
  `call_remote_compaction_v2` HTTP call (with a `transport` test seam).
- `tau_agent/session/entries.py` - `CompactionEntry.details` (optional).
  Replay folds the summary text and never reads details; the schema is
  backward compatible (new optional field).
- `tau_coding/session.py` - eligibility resolution
  (`default_remote_compaction_params`, async, requires
  `OpenAICodexProviderConfig` and resolves credentials through the exact
  production flow `OpenAICodexCredentialResolver`), the parallel
  `_generate_compaction_summary_and_details`, the never-raising
  `_maybe_remote_compact`, and `_sync_remote_replay_from_state` which
  reconstructs the active replay items from `SessionState.compaction_entries`
  (active path only, newest matching-model entry wins, cleared on model
  change or branch without a match).
- `tau_ai/openai_codex.py` - the Codex transport now accepts
  `remote_input_items` and prepends the persisted artifact to `input` on the
  next request.

## How it maps to the reference Pi extension

The Palg extension stores the artifact in `CompactionEntry.details.remoteCompaction`
and replays it via response-id continuation over WebSocket. Tau's prototype
keeps the same persistence shape (`details` + `replacement_history`) but only
replays the artifact as prepended input items on the next Codex Responses
request. Deliberately out of scope: `previous_response_id` live continuation
and the WebSocket transport - the fragile parts, not needed for the
continuity benefit.

## How to test

- Unit: `tests/test_openai_remote_compaction.py` - Codex header shape, SSE
  parsing, payload shape, replacement-history truncation, and an offline
  HTTP round trip via `httpx.MockTransport` against the Codex backend URL.
- Session: `tests/test_coding_session.py` - manual compact stores details and
  replays items on the next prompt; remote failure falls back to the summary
  with no details; reload reconstructs replay from the persisted journal, and
  a foreign-model artifact does not leak into the request. The default
  eligibility resolver is unit-tested: Codex + env JWT resolves, non-Codex
  providers always return `None`, and Codex without credentials returns
  `None`.
- Schema: `tests/test_session.py` - `CompactionEntry.details` round-trips
  through JSONL and replay ignores it.

Run: `uv run pytest tests/test_openai_remote_compaction.py tests/test_coding_session.py tests/test_session.py`

## Known limitations of this prototype

- Codex-subscription only. The token resolution reuses
  `OpenAICodexCredentialResolver` (OAuth store first, `OPENAI_CODEX_ACCESS_TOKEN`
  JWT fallback); no other provider qualifies.
- The artifact is provider-native and unreadable in exports; do not rely on
  it for portability. Cross-model turns filter the replay by the model that
  produced the artifact.
- Usage/cost is captured in `details.usage` but not folded into session
  stats yet.

## Kill switch and failure notice

Set `TAU_REMOTE_COMPACTION_ENABLED` to `0`, `false`, `no`, or `off` to disable
remote compaction entirely (eligibility AND replay, so a persisted artifact
stays inert). Unset or any other value means enabled. `session.remote_compaction_status`
("Remote compaction failed; used text summary") is a short notice that becomes
non-None whenever the remote call was expected to run (Codex provider active,
kill switch on) but could not, and clears on the next successful attempt. The
TUI renders it persistently in the run-status bar above the prompt, bold red,
alongside the running/finished timer. Deliberate skips stay silent: kill
switch off, or a provider that is not the codex subscription provider.

A failed remote attempt writes a structured exception with phase
`remote_compaction` to `~/.tau/logs/agent-calls.jsonl`. The session journal
cannot explain the failure because a fallback compaction entry contains only
the successful portable summary

## Duplicate content-type repair

The first live Tau sessions failed every remote request with HTTP 400 and
`Unsupported content type`. The request builder combined title-case defaults
with lower-case Codex headers in a plain Python dictionary. HTTP field names
are case-insensitive, but dictionary keys are not, so `httpx` sent two
content-type fields. The Codex backend rejected the request before compaction
started

`call_remote_compaction_v2` now normalizes all outgoing header names before it
applies defaults. Tests inspect the actual `httpx.Request` and require exactly
one content-type and one accept field. Installation IDs also use the canonical
hyphenated UUID form used by the reference extension
