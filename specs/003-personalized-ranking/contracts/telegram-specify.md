# Telegram `/specify` Contract

## Command

```text
/specify <free-form preference statement>
```

The adapter passes:

- authenticated Telegram user identity;
- Telegram update/message identity used for idempotency;
- normalized language code when available;
- command text after `/specify`.

The adapter never interprets preference meaning or mutates a profile.

## Input behavior

- Missing or whitespace-only text returns:
  `Tell me what news you want, for example: /specify News from Kirov`
- Text over the configured limit returns a controlled length message.
- The adapter acknowledges processing before a potentially slow interpretation.
- Replayed updates return the persisted result and do not create another change.

## Result states

| State | User-visible behavior |
|---|---|
| `processing` | Explicit preference is being interpreted |
| `applied` | Confirm the specific accepted preference change in bounded language |
| `no_change` | Explain that the request already matches current preferences |
| `invalid` | Explain that the statement could not be converted into a safe preference change |
| `stale_retry` | Processing continues against the latest profile |
| `failed` | Controlled retry-later message; prior profile remains unchanged |

User-visible confirmation may contain parameter names and action summaries. It
must not expose model prompts, raw proposals, internal scores, stack traces, or
other users' data.

## Failure and privacy

- Missing user/message objects are ignored with a sanitized diagnostic.
- Provider, validation, persistence, and stale-limit errors become controlled
  states.
- Raw statement text is not written to structured logs.
- Telegram handlers contain no duplicate classification, authority policy,
  profile application, or ranking calculation.
