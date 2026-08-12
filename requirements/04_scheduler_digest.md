# Feature Specification: Digest Scheduler

## Goal

Generate and deliver scheduled personalized news digests.

Telegram is only the delivery adapter.

## 1. Digest Configuration

Each user has:

- enabled/disabled;
- digest count;
- schedule;
- timezone;
- last successful execution;
- last failure.

Digest count is configurable and limited to `5..20`.

## 2. /count

`/count 10` changes the user's persisted digest size.

Reject values below 5 or above 20.

## 3. Scheduler Flow

For every due user:

1. load user preferences;
2. determine digest count;
3. obtain recent normalized news from the News Aggregator;
4. obtain/enforce article analysis;
5. invoke Personal Ranking;
6. apply diversity and delivery-history rules;
7. select top N;
8. create structured digest;
9. deliver through the messaging adapter;
10. persist execution result.

The scheduler orchestrates modules; it does not implement ranking mathematics.

## 4. User Isolation

Failure for one user must not prevent other users' digests.

## 5. Insufficient News

If fewer than N suitable articles exist, send fewer.

Never fill the digest with irrelevant articles only to reach N.

## 6. Delivery History

Avoid repeatedly delivering the same article to the same user unless:

- the story materially changed;
- a new development occurred;
- configured policy allows repetition;
- user explicitly requests it.

Persist sufficient history for this decision.

## 7. Structured Digest

The application returns structured items containing:

- title;
- summary;
- source;
- publication time;
- URL.

Telegram-specific formatting belongs to the Telegram adapter.

## 8. Scheduler Interface

Define an application-level scheduler interface independent from the scheduling technology.

It must support:

- finding due users;
- executing a digest;
- recording success;
- recording failure;
- retrying transient failures.

## 9. Idempotency

Every digest execution has a unique execution identifier.

Retries must not accidentally create duplicate deliveries.

The system must distinguish scheduled execution, retry and completed execution.

## 10. Acceptance Criteria

- `/count 5` produces at most 5 selected articles.
- `/count 20` produces at most 20.
- If only 3 suitable articles exist for count 10, only 3 are sent.
- Failure for user A does not stop user B.
- Retries are idempotent.
- Scheduling respects the user's timezone.
- Scheduler does not contain ranking business logic.
