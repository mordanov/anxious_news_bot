# Contract: Telegram `/tune`

## Command

`/tune` starts or resumes the verified Telegram user's one active questionnaire.

- If generation is needed, show a concise processing message.
- If an unanswered question exists, show its ordinal, text, and exactly four
  inline buttons.
- If all answers exist but interpretation is pending, show a processing/retry
  status without creating another questionnaire.
- If already applied, show a clear completion message.
- A restart followed by `/tune` MUST render the durable current state.

## Question presentation

Each question message contains:

```text
Question {ordinal} of 10
{question text}
```

The inline keyboard contains exactly four options in configured layout order. Each
button label is the persisted option label. Callback data is `t:<opaque-token>`,
fits Telegram's 64-byte limit, and contains no authoritative user, questionnaire,
question, or option identifier.

## Callback handling

For every callback:

1. Acknowledge the callback promptly, even when it is stale or invalid.
2. Reject callback data outside the versioned `t:<token>` shape.
3. Resolve the token digest and verify ownership, active questionnaire, and current
   unanswered question in persistent state.
4. Record the answer once.
5. Remove or disable the old keyboard when possible.
6. Render the next durable state.

Repeated delivery of the same token returns the already-persisted next state.
Racing different options for one question records only one answer; the loser is
treated as stale and cannot advance the questionnaire.

## User-visible outcomes

| State | Required behavior |
|---|---|
| Generating | Explain briefly that questions are being prepared |
| Question | Show ordinal, text, and four buttons |
| Processing | Explain that the completed answers are being interpreted |
| Completed | Confirm that preferences were updated |
| Retryable failure | Explain that the profile was not changed and `/tune` can resume |
| Invalid/stale callback | Show a short stale-option notice and render current state |
| Terminal failure | Explain that the profile was not changed |

Messages must not reveal model output, internal identifiers, other users' state, or
diagnostic details.

## Adapter constraints

- Telegram handlers call only application services and render returned states.
- No prompt construction, preference arithmetic, semantic duplicate logic, or
  persistence operation may exist in the handler.
- Missing message/callback/user objects produce classified diagnostics and no
  state change.
