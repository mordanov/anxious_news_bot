# Feature Specification: News Aggregator and Article Analysis

## Goal

Implement the general news ingestion pipeline independently from user personalization.

The output is a clean, normalized, enriched pool of news that can later be consumed by the Personal Ranking Engine.

## 1. News Sources

Support configurable sources grouped initially into:

- World
- Russia
- Spain

A source contains:

- id;
- name;
- type;
- URL/endpoint;
- country/region;
- language;
- enabled flag;
- quality metadata;
- polling configuration.

The architecture must allow new sources and regions without changing core aggregation logic.

## 2. Article

A normalized article contains:

- id;
- title;
- description/summary;
- canonical URL;
- source;
- publication timestamp;
- ingestion timestamp;
- language;
- normalized text;
- geographic relevance;
- topic metadata;
- event/cluster identifier where applicable.

Retain original source data where useful for debugging.

## 3. Aggregation Pipeline

The aggregator must:

1. fetch enabled sources;
2. parse source-specific formats;
3. normalize articles;
4. validate required fields;
5. reject malformed records without stopping the whole pipeline;
6. detect duplicates;
7. persist normalized articles;
8. return newly available articles.

Failure of one source must not prevent other sources from being processed.

## 4. Deduplication

Support:

- exact URL duplicates;
- near-duplicate titles/content;
- semantic duplicates representing the same underlying event.

Multiple sources may point to one event. Preserve source URLs while allowing the digest to select one representative article.

## 5. Article Analysis

Before personalization, enrich articles with structured information such as:

- topics;
- countries;
- cities/locations;
- people;
- organizations;
- event type;
- importance;
- novelty;
- source quality;
- semantic representation if needed.

LLM may perform semantic enrichment, but its output must be structured and validated.

## 6. Importance

Article importance is independent from personal interest.

An article can be:

- important and irrelevant;
- unimportant and interesting;
- both;
- neither.

Store importance separately so Personal Ranking can combine it with user preference.

## 7. News Aggregator Boundary

The aggregator must NOT:

- load a user's preference profile;
- decide whether a story is personally interesting;
- rank articles for a user;
- modify user preference weights.

It produces general article-level metadata only.

## 8. Interfaces

Define replaceable application interfaces for:

- `NewsSource`;
- `NewsFetcher`;
- `ArticleNormalizer`;
- `ArticleDeduplicator`;
- `ArticleEnricher`;
- `NewsAggregator`.

## 9. Acceptance Criteria

- One unavailable source does not stop other sources.
- Same canonical URL is not stored twice.
- Semantically identical stories can be grouped.
- An article can survive partial enrichment failure.
- Adding a new country/source does not require changing the domain model.
- No user-specific ranking occurs in this module.
