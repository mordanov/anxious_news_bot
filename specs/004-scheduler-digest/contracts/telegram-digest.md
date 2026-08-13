# Contract: Telegram Digest Commands and Delivery

## `/count`

### Accepted input

```text
/count <integer>
```

- Exactly one argument.
- Decimal integer notation only.
- Accepted range: 5 through 20 inclusive.
- Telegram command suffixes such as `/count@BotName` are handled by the framework.

### Success behavior

1. Resolve the current Telegram user.
2. Pass the integer to the digest configuration application service.
3. Reply in the user's persisted supported language.
4. Confirm the persisted value.

Messages:

| Language | Confirmation |
|----------|--------------|
| Russian | `Размер дайджеста: {count}.` |
| English | `Digest size: {count}.` |
| Spanish | `Tamano del resumen: {count}.` |

### Invalid behavior

Missing, extra, non-integer, below-5, or above-20 input does not mutate state.

| Language | Guidance |
|----------|----------|
| Russian | `Используйте /count с числом от 5 до 20.` |
| English | `Use /count with a number from 5 to 20.` |
| Spanish | `Usa /count con un numero del 5 al 20.` |

If no effective user or message exists, log a safe warning and do not mutate
state. Persistence failure uses the existing localized generic failure pattern
and logs only safe structured context.

## Scheduled Digest Rendering

Input is a complete `StructuredDigest`; Telegram does not rank, filter, translate,
summarize, or query news.

Each item renders:

```text
{position}. {title}
{summary}
{source} - {YYYY-MM-DD}
{url}
```

Rules:

- Preserve item order.
- Normalize whitespace and apply documented maximum display lengths without
  changing URLs.
- Split only between complete item blocks.
- Each message is at most 3900 characters, leaving provider safety margin.
- The first part begins with the localized digest header; subsequent parts do
  not repeat already delivered items.
- Rendering returns deterministic part ranges and SHA-256 content hashes.
- Empty digests are not sent.

Localized headers:

| Language | Header |
|----------|--------|
| Russian | `Ваш новостной дайджест` |
| English | `Your news digest` |
| Spanish | `Tu resumen de noticias` |

## Delivery Outcome

- A successful send returns Telegram `message_id` and acknowledgement time.
- A definite rate-limit or temporary connectivity rejection before acceptance is
  transient and may retry that pending part after the configured delay.
- Invalid chat, blocked bot, forbidden, or malformed content is permanent.
- Timeout/disconnect after request transmission without a response is ambiguous.
  Mark the part and execution unknown; never resend automatically.
- Provider error text, tokens, chat content, and rendered digest content are not
  logged. Logs use execution ID, part ordinal, status, safe error code, attempt,
  item count, and duration.

