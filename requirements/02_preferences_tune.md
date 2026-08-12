# Feature Specification: User Preferences and /tune

## Goal

Learn and maintain a user-specific news preference model through adaptive 10-question questionnaires.

Telegram is only the interface.

## 1. Preference Parameter

Each parameter contains:

- stable id;
- user id;
- name;
- description;
- evaluation instructions;
- weight;
- origin;
- active flag;
- timestamps.

Origins include:

- questionnaire;
- explicit;
- inference;
- system.

Weight:

- minimum `-1.00`;
- maximum `+1.00`;
- step `0.01`;
- default `0.00`.

## 2. Weight Meaning

`+1.00`: extremely desirable.

`+0.50`: moderately desirable.

`0.00`: neutral.

`-0.50`: moderately undesirable.

`-1.00`: strongly undesirable.

Negative does not mean "the opposite topic is interesting"; it means matching articles should receive a negative contribution.

## 3. /tune

Each `/tune` session generates exactly 10 questions.

Every question has exactly four answer options.

Questions must be:

- short;
- concrete;
- focused on one semantic dimension;
- relevant to news ranking;
- non-leading;
- non-vague;
- non-double-barreled.

Avoid questions like:

"Вы хотите знать новости о новостройках Малаги?"

with merely reordered yes/no answers.

Prefer questions such as:

"Какая область изучения космоса вас интересует?"

1. Галактики
2. Внеземные цивилизации
3. Новости SpaceX
4. Новости России о космосе

## 4. Adaptive Question Generation

Persist:

- questionnaire;
- questions;
- four options;
- selected answers;
- timestamps.

When generating a new questionnaire, provide the LLM with relevant previous questions, answers and current preference parameters.

The LLM should prefer:

- unexplored preference dimensions;
- deeper questions about strong interests;
- clarification of ambiguous preferences.

It should avoid substantial repetition.

## 5. Preference Update

After 10 answers:

current profile + questionnaire + answers -> LLM proposed changes -> validation -> deterministic update.

The LLM may propose:

- increase existing parameter;
- decrease existing parameter;
- create parameter;
- deactivate parameter;
- refine parameter description/instructions.

It must not directly write to the database.

## 6. Parameter Reuse

Before creating a parameter, the LLM must compare the intended parameter against existing user parameters.

Reuse or refine an existing parameter when semantically appropriate.

The application must reject obvious duplicate parameters.

## 7. Incremental Updates

Questionnaires should normally modify the current profile rather than replace it.

Example:

`space_exploration = +0.40`

may become:

`space_exploration = +0.65`

after strong evidence of increased interest.

The update mechanism must be deterministic once the LLM has proposed a change.

## 8. Strict LLM Contract

Define structured schemas for:

- question generation;
- questionnaire interpretation;
- parameter changes.

Validate:

- exactly 10 questions;
- exactly 4 options per question;
- valid parameter IDs;
- valid actions;
- weight range;
- 0.01 precision;
- required fields;
- semantic uniqueness.

## 9. Preference History

Record:

- previous state;
- new state;
- source;
- questionnaire id where applicable;
- reason;
- timestamp.

## 10. Acceptance Criteria

- `/tune` produces exactly 10 valid questions.
- A second `/tune` uses prior context and avoids substantial repetition.
- All weights remain in `[-1.00, +1.00]`.
- Weights use 0.01 precision.
- Failed validation leaves the previous profile unchanged.
- Every change is auditable.
- Existing parameters are reused where appropriate.
