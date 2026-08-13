# `cast()` usage audit

Audit date: 2026-08-13

## Purpose

`typing.cast` tells a static type checker to trust the annotated type without
any runtime proof. Every cast is a place where the checker cannot derive the
type itself, or where the code asserts a type that the checker would reject.

This audit lists every `cast()` call in the repository, groups them by root
cause, and suggests how to remove them. The goal is to reduce the number of
casts so `mypy` and `ty` can catch real type errors instead of being silenced.

## Summary

- Total `cast()` calls: 103
- In `src/`: 31 (12 files)
- In `tests/`: 72 (7 files)
- `# type: ignore` comments in the whole repo: 3

Casts are the dominant type-checker suppression mechanism in this codebase.
The repo runs both `mypy` (see `pyproject.toml` `[tool.mypy]`) and `ty`
(dev dependency `ty>=0.0.67`).

## How to reproduce this audit

```bash
rg -n "cast\(" --glob '*.py'
rg -n "cast\(" --glob '*.py' | wc -l
```

## Inventory

### Source code (`src/`, 31 casts)

| File | Lines | Expression | Why it exists |
| --- | --- | --- | --- |
| `src/tau_ai/openai_compatible.py` | 516, 527 | `cast(Mapping[str, Any], chunk_usage / choice_usage)` | `isinstance(x, Mapping)` does not narrow to `Mapping[str, Any]`; `Mapping` type params are invariant |
| `src/tau_ai/openai_compatible.py` | 1038 | `cast(Mapping[str, Any], item)` | Same pattern in `_register_reasoning_item` after an `isinstance(item, Mapping)` guard |
| `src/tau_ai/openai_codex.py` | 570, 573, 631, 641, 651, 666 | `cast(Mapping[str, Any], item)` | Same pattern in the Codex Responses SSE stream: reasoning items, function-call items, done messages |
| `src/tau_agent/session/memory.py` | 50 | `cast(str \| None, leaf_id)` | Sentinel `_UNSET_LEAF_ID` is typed as `object` in the union `str \| None \| object`, so the `is _UNSET_LEAF_ID` check cannot narrow the other branch |
| `src/tau_coding/brave_search.py` | 405 | `cast(list[JSONValue], results)` | `list` is invariant; `results` elements are `dict[str, Any]`, not `JSONValue` (the code carries a comment explaining this) |
| `src/tau_coding/credentials.py` | 184 | `cast(StoredCredentialKind, credential_type)` | Set membership check `value in {"api_key", "oauth"}` does not narrow a string to the Literal union |
| `src/tau_coding/credentials.py` | 204 | `cast(dict[str, JSONValue], metadata)` | `isinstance(metadata, dict)` does not narrow to `dict[str, JSONValue]`; `dict` type params are invariant |
| `src/tau_coding/provider_config.py` | 1883 | `cast(list[str], value)` | `isinstance(value, list)` does not narrow the element type; `list` is invariant |
| `src/tau_coding/provider_config.py` | 1907 | `cast(ProviderApi, value)` | Set membership check does not narrow a string to the Literal union `"openai-completions" \| "openai-responses" \| "openai-codex-responses"` |
| `src/tau_coding/extensions/api.py` | 740 | `cast("ComponentBridge", self._runtime.ui)` | `_runtime.ui` is typed by a broader interface; the `components` property needs the narrower bridge type |
| `src/tau_coding/tui/terminal_title.py` | 87 | `cast(TextIO, sys.__stdout__)` | `sys.__stdout__` is typed `TextIO \| None` in typeshed |
| `src/tau_coding/tui/terminal_notification.py` | 86 | `cast(TextIO, sys.__stdout__)` | Same pattern |
| `src/tau_coding/tui/themes/__init__.py` | 161, 200, 232, 269 | `cast(dict[str, object], value)` | `isinstance(value, dict)` does not narrow to `dict[str, object]`; `dict` type params are invariant |
| `src/tau_coding/tui/themes/__init__.py` | 284 | `cast(dict[str, object], raw)` | Same pattern for the nested role entry |
| `src/tau_coding/tui/config.py` | 174 | `cast(TurnNotificationMode, raw_notification)` | Set membership check does not narrow a string to the Literal union `"off" \| "bell" \| "desktop"` |
| `src/tau_coding/tui/app.py` | 814 | `cast(CompletionActionTarget, self.app)` | Textual types `self.app` as the generic `App`; the prompt widget needs its host app type |
| `src/tau_coding/tui/app.py` | 1011, 1191, 1437, 1926, 2313 | `cast(XxxScreen, self.screen)` | Textual types `self.screen` as the generic `Screen`; each search-input widget downcasts to the modal screen that hosts it (`ToolsReferenceScreen`, `SessionPickerScreen`, `SkillPickerScreen`, `LoginProviderPickerScreen`, `ModelPickerScreen`) |
| `src/tau_coding/tui/app.py` | 4268 | `cast(SlotWidgetFactory, cast(object, content))` | `content` is `SlotWidgetContent = Sequence[str] \| SlotWidgetFactory`; after `callable(content)` the checker still cannot prove the narrower callable signature, so the code casts through `object` |

### Tests (`tests/`, 72 casts)

| File | Lines | Pattern |
| --- | --- | --- |
| `tests/test_cli.py` | 157, 200, 201, 283, 284, 285 | `cast(str \| None, args[-2] / args[-1] / args[2])` on captured mock-call positional args |
| `tests/test_cli.py` | 430, 431, 432 | `cast(tuple[str, ...], kwargs["startup_notices"])`, `cast(str \| None, kwargs["custom_system_prompt"] / kwargs["append_system_prompt"])` on captured mock kwargs |
| `tests/test_coding_session.py` | 2889, 2890 | `cast(tuple[Skill, ...], session.skills)`, `cast(tuple[ProjectContextFile, ...], session.context_files)` after a session reload |
| `tests/test_coding_session.py` | 4615, 4616, 4632, 4633 | `cast(SessionState, object())`, `cast(AgentHarness, object())` as constructor stubs |
| `tests/test_tui_components.py` | 31 | `cast(CodingSession, FakeSession())` |
| `tests/test_tui_file_drop.py` | 184, 203 | `cast(CodingSession, FakeSession())` |
| `tests/test_project_trust.py` | 377, 476, 513, 524, 548, 883, 923, 988, 1054, 1071, 1108, 1159, 1208, 1263, 1284 | `cast(ModelProvider, object())` as provider stubs in `_CommonConfig` dicts and `CodingSession.load` kwargs |
| `tests/test_extensions.py` | 686 | `cast(CommandSession, None)` as a session stub |
| `tests/test_extensions.py` | 728, 888, 894, 949, 1038 | `cast(ToolCallHookEvent / InputEvent / TurnStartEvent, event)` to narrow a generic event in hook handlers |
| `tests/test_extensions.py` | 936 | `cast(ExtensionHandler, _hook)` to satisfy an `on(...)` subscription |
| `tests/test_extensions.py` | 1386, 1389, 1412 | `cast(SlotWidgetFactory, lambda theme: None)`, `cast(MainViewFactory, lambda h, theme: None)` for lambda stubs |
| `tests/test_extensions.py` | 2001, 2012, 2097, 2102 | `cast(ExtensionAPI, _module_values(module, "APIS")[-1])` for runtime module introspection |
| `tests/test_extensions.py` | 2285, 2349, 2383 | `cast(ToolCallRenderer / ToolResultRenderer / MessageRenderer, lambda ...)` for renderer lambda stubs |
| `tests/test_tui_app.py` | 173, 9684 | `cast(CodingSession, session)` for a fake session |
| `tests/test_tui_app.py` | 8194, 8274, 8356, 8461, 8574, 8673, 8768, 8777, 8850, 8948, 9045 | `cast(SessionManager, FakeManager())` as a session-manager stub |
| `tests/test_tui_app.py` | 8363, 8823 | `cast(tuple[str, ...], kwargs["startup_notices"])` on captured mock kwargs |
| `tests/test_tui_app.py` | 1698 | `cast(Callable[..., None], transcript.scroll_end)` for a monkeypatched method |
| `tests/test_tui_app.py` | 1864, 1885, 1909, 1928 | `cast(dict[Widget, Selection], ...)` to assign `app.screen.selections` in selection tests |
| `tests/test_tui_app.py` | 4810 | `cast(tuple[PromptTemplate, ...], app.screen.visible_templates)` |
| `tests/test_tui_app.py` | 5785 | `cast(object, app.screen.focused)` for an identity assertion |

## Root-cause patterns

### Pattern A: narrowing after `isinstance(x, Mapping)` or `isinstance(x, dict)`

15 casts in `src/` (openai_compatible.py 3, openai_codex.py 6, themes 5,
credentials.py 1).

`isinstance` narrows `object` to `Mapping[Any, Any]` or `dict[Any, Any]`, but
not to a parameterized mapping such as `Mapping[str, Any]`. Generic type
parameters are invariant, so the checker refuses the implicit conversion.

Suggested fix: a `TypeGuard` helper that checks the runtime contract. For
values that must have string keys, check the keys:

```python
def is_string_mapping(value: object) -> TypeGuard[Mapping[str, Any]]:
    return isinstance(value, Mapping) and all(isinstance(k, str) for k in value)
```

For `dict[str, JSONValue]`, the honest check is recursive and expensive; a
`TypeGuard` that only checks `isinstance(value, dict)` documents the same
assumption the cast makes, with the benefit that the narrowing is reusable and
checkable:

```python
def is_json_object(value: object) -> TypeGuard[dict[str, JSONValue]]:
    return isinstance(value, dict)
```

In `openai_codex.py`, the repeated `isinstance(item, Mapping) and item.get("type") == ...`
guards could move into one helper per item kind, for example
`reasoning_item_from(value: object) -> ReasoningItem | None`, which removes
both the cast and the repeated guard.

### Pattern B: narrowing a string to a Literal union by set membership

3 casts in `src/` (credentials.py 184, provider_config.py 1907, tui/config.py
174).

Checkers do not narrow `value in {"a", "b"}` to the corresponding
`Literal["a", "b"]` union.

Suggested fix: a `TypeGuard` per Literal union:

```python
def is_stored_credential_kind(value: object) -> TypeGuard[StoredCredentialKind]:
    return value in {"api_key", "oauth"}
```

The `match` statement narrows to Literals in both mypy and ty and is an
alternative when the branches already differ:

```python
match credential_type:
    case "api_key":
        ...
    case "oauth":
        ...
    case _:
        raise CredentialStoreError(...)
```

### Pattern C: `list` invariance

2 casts in `src/` (brave_search.py 405, provider_config.py 1883).

`isinstance(value, list)` does not narrow the element type.

Suggested fix: validate the elements where the contract requires them and
build a fresh typed list:

```python
def is_string_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)
```

In `_optional_thinking_levels`, the elements are validated later by
`normalize_thinking_levels`, so a guard that checks `isinstance(item, str)`
for each element is accurate and cheap.

### Pattern D: sentinel narrowing

1 cast in `src/` (memory.py 50).

`leaf_id: str | None | object` cannot be narrowed after
`leaf_id is _UNSET_LEAF_ID` because the sentinel member is plain `object`.

Suggested fix: give the sentinel a distinct final type and narrow by identity:

```python
class _UnsetLeafId: ...

_UNSET_LEAF_ID: Final = _UnsetLeafId()

def from_entries(cls, entries, *, leaf_id: str | None | _UnsetLeafId = _UNSET_LEAF_ID) -> SessionState:
    if leaf_id is _UNSET_LEAF_ID:
        resolved_leaf_id = None
        replay_all = True
    else:
        resolved_leaf_id = leaf_id
        replay_all = False
```

If the sentinel class is `@final`, both mypy and ty narrow the `else` branch
to `str | None`.

### Pattern E: `sys.__stdout__` is optional

2 casts in `src/` (terminal_title.py 87, terminal_notification.py 86).

typeshed types `sys.__stdout__` as `TextIO | None`.

Suggested fix: use `sys.stdout`, which typeshed types as `TextIO`, or assert:

```python
stream = sys.stdout if stream is None else stream
```

```python
if stream is None:
    stream = sys.__stdout__
    assert stream is not None
```

### Pattern F: framework downcasts (Textual screen/app, UI bridge)

8 casts in `src/` (tui/app.py 814, 1011, 1191, 1437, 1926, 2313, 4268;
extensions/api.py 740).

Textual types `self.screen` as `Screen` and `self.app` as `App`, so widgets
that live inside a specific modal screen must downcast. The extension bridge
has the same shape: `_runtime.ui` is typed by a broader interface and the
`components` property needs the narrower `ComponentBridge`.

Suggested fix: replace the cast with a runtime-checked assertion, which
narrows the type and validates the assumption at the same time:

```python
def _picker(self) -> SessionPickerScreen:
    screen = self.screen
    assert isinstance(screen, SessionPickerScreen)
    return screen
```

One small helper per widget keeps the assertion local. A shared generic mixin
with `assert isinstance(x, TypeVar)` is not possible, because that syntax is
invalid; keep one helper per concrete screen class. The point is that the
assertion form turns each silent cast into a checked invariant, and the
helpers can move to the base class when the screens share a common base.

For extensions/api.py 740, the same assertion form works:

```python
ui = self._runtime.ui
assert isinstance(ui, ComponentBridge)
return ui
```

For app.py 4268, replace the double cast with a `TypeGuard`:

```python
def is_slot_widget_factory(value: object) -> TypeGuard[SlotWidgetFactory]:
    return callable(value)
```

### Pattern G: test stubs built from `object()` or `None`

31 casts in `tests/` (test_project_trust.py 15, test_coding_session.py 4,
test_extensions.py 1, test_tui_app.py 11).

`cast(ModelProvider, object())` and friends pass a bare `object()` where a
real instance is required.

Suggested fix: define one small fake class per protocol in a shared test
helper (for example `tests/conftest.py` or a `tests/fakes.py`) and reuse it:

```python
class FakeModelProvider:
    """Minimal ModelProvider implementation for config-level tests."""

    def __init__(self) -> None:
        self.name = "fake"
        ...
```

If `ModelProvider` is a Protocol, a class with the right members satisfies it
structurally and needs no cast. `unittest.mock.Mock(spec=ModelProvider)` is a
lighter alternative that keeps attribute access checked.

### Pattern H: structural fakes for concrete classes

5 casts in `tests/` (test_tui_components.py 31, test_tui_file_drop.py 184 and
203, test_tui_app.py 173 and 9684).

`FakeSession` is not a `CodingSession` subclass, so each use needs a cast.

Suggested fix: make the fake satisfy the interface nominally. If
`TauTuiApp.__init__` accepts `CodingSession`, either subclass
`CodingSession` in the fake (heavier) or introduce a small `SessionLike`
Protocol for the parts the app actually uses and accept that in
`TauTuiApp`. The Protocol approach removes the cast and documents the real
dependency.

### Pattern I: captured mock call args and kwargs

11 casts in `tests/` (test_cli.py 9, test_tui_app.py 2).

Fake functions declared as `*args: object` / `**kwargs: object` force casts
when reading captured values.

Suggested fix: declare the fake with the precise signature of the real
function:

```python
async def fake_run_openai_tui(system_prompt: str | None, append_system_prompt: str | None) -> None:
    calls.append((system_prompt, append_system_prompt))
```

For kwargs, read the value through a typed helper or unpack into a TypedDict
instead of indexing a dict of `object`.

### Pattern J: runtime introspection in extension tests

4 casts in `tests/` (test_extensions.py 2001, 2012, 2097, 2102).

`_module_values(module, "APIS")[-1]` returns `object`, so the extension API
instance needs a cast.

Suggested fix: give the helper a type parameter or add an
`assert isinstance(api, ExtensionAPI)` at the call site.

### Pattern K: event narrowing in hook handlers

5 casts in `tests/` (test_extensions.py 728, 888, 894, 949, 1038).

Handlers receive a generic `Event`; tests narrow to the concrete event type.

Suggested fix: `assert isinstance(event, InputEvent)` inside the handler. This
is the same fix as Pattern F and also fails the test loudly if the runtime
event type is wrong.

### Pattern L: lambda stubs for callable types

7 casts in `tests/` (test_extensions.py 936, 1386, 1389, 1412, 2285, 2349,
2383).

Lambdas with compatible signatures do not structurally match callable
Protocol types with keyword-only parameters (for example
`ToolResultRenderer`).

Suggested fix: define tiny named functions with the exact signature, or add
`assert isinstance` style guards in the test helper that consumes them.

### Pattern M: attribute narrowing in tests

9 casts in `tests/` (test_tui_app.py 1698, 1864, 1885, 1909, 1928, 4810,
5785; test_coding_session.py 2889, 2890).

Assignments to `app.screen.selections` and reads of `visible_templates` need
typed containers. The `session.skills` and `session.context_files` reads in
test_coding_session.py are the same shape: attributes whose declared type is
broader than what the test asserts.

Suggested fix: type the helper that builds the selection dict so it returns
`dict[Widget, Selection]`, and use `assert isinstance` for the screen-attribute
reads. The 5785 case (`cast(object, app.screen.focused)`) is only needed for
an identity assertion and can be dropped by asserting on a narrower value.

## Recommended order of work

1. Patterns A, B, C, D, E in `src/` (23 casts). These are small, local, and
   the `TypeGuard` / match / assert fixes keep the same runtime behavior.
2. Pattern F in `src/` (8 casts). The assertion form adds real runtime
   validation of the screen/app/bridge invariants.
3. Patterns G and H in `tests/` (36 casts). Shared fakes remove the largest
   test-side cluster.
4. Pattern I in `tests/` (11 casts). Typed fake signatures.
5. Patterns J, K, L, M in `tests/` (25 casts). Mostly mechanical conversions
   from cast to assert or typed helpers.

## Verification

After each change, run the checkers and the test suite. The CI commands are
`uv run ty check` and `uv run mypy` (see `.github/workflows/ci.yml`); mypy is
configured for the `src/` packages only (`[tool.mypy]` in `pyproject.toml`):

```bash
uv run ty check
uv run mypy
uv run pytest
```

Track progress with the counts from the reproduction commands at the top of
this document. A residual count in the low tens is acceptable; the remaining
casts should be the intentional test stubs (Patterns G, H, L) where a cast
documents "this is a deliberate fake".
