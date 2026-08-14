# User Guide

## Scheduled digest behavior

A scheduled digest is a personalized, ordered list of recent suitable articles.
Each item contains:

- localized title;
- concise localized summary;
- source;
- publication date;
- original URL.

The bot uses your current language and preference profile. It may send fewer
articles than requested when fewer suitable articles exist. It never adds
irrelevant filler.

## Set digest size

Use exactly one decimal integer from 5 through 20:

```text
/count 5
/count 10
/count 20
```

Confirmation:

| Language | Message |
|---|---|
| Russian | `Размер дайджеста: 10.` |
| English | `Digest size: 10.` |
| Spanish | `Tamano del resumen: 10.` |

These forms are rejected without changing the saved count:

```text
/count
/count 4
/count 21
/count abc
/count +5
/count 5 extra
```

Guidance:

| Language | Message |
|---|---|
| Russian | `Используйте /count с числом от 5 до 20.` |
| English | `Use /count with a number from 5 to 20.` |
| Spanish | `Usa /count con un numero del 5 al 20.` |

Changing the count does not enable scheduled delivery. An execution already in
progress keeps the count it captured; later executions use the new value.

## Schedule and timezone

This release supports persisted daily local schedules and IANA timezones, but
does not expose end-user enable/time/timezone commands. An operator must provision
those settings. New users remain disabled by default.

Daylight-saving policy is deterministic:

- repeated local time: use the earlier occurrence;
- missing local time: use the first valid local minute after the gap;
- one user/local occurrence can create only one execution.

## Repetition policy

Previously delivered unchanged articles are removed before personal evaluation.
The same article remains excluded even if delivery acknowledgement was uncertain.
A later article in the same story can return only when persisted evidence shows a
material development through accepted novelty or a deterministic content delta
without duplicate/review evidence.

On-demand `/news` remains separate and keeps its existing behavior.

## Delivery and failures

A digest may contain multiple Telegram messages. Splits occur only between whole
article blocks.

- Acknowledged parts are not sent again.
- A definite temporary failure may retry the pending part.
- A permanent rejection stops automatic retries.
- If Telegram may have accepted a message but acknowledgement was lost, the
  execution becomes `delivery_unknown` and is not resent automatically.

This conservative rule favors avoiding duplicates over blind redelivery.

## Privacy

Digest records retain identifiers, structured item snapshots, safe failure codes,
delivery acknowledgements, and deterministic evidence needed for reliability.
Logs do not contain prompts, provider responses, article bodies, rendered
messages, Telegram tokens, or credentials.

## Troubleshooting

### `/count` returns guidance

Send exactly one ASCII decimal integer in `5..20`.

### No scheduled digest arrives

Ask an operator to verify:

1. the digest configuration is enabled;
2. `next_due_at` is populated;
3. timezone is a valid IANA name;
4. migrations are at `005_scheduler_digest`;
5. model and Telegram credentials are configured;
6. suitable recent analyzed articles exist.

### A digest contains fewer articles

This is expected when quality, freshness, history, preference, or diversity rules
leave fewer eligible articles. The system does not fill the gap with irrelevant
content.

### Delivery status is unknown

Do not manually reset the part to pending. An operator must reconcile provider
evidence first; otherwise resending can create a duplicate.
