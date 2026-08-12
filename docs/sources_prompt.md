# News Source Research Prompt

```text
You are working in the anxious-news-bot repository. Research current RSS or Atom news feeds and create `sources.json` in the repository root.

Find 5–8 reliable, active sources for each group:

1. World news — broad international coverage from geographically diverse publishers.
2. Russia news — primarily Russian-language reporting about Russia, using a mix of reputable independent and established sources.
3. Spain news — primarily Spanish-language reporting about Spain, including major national publishers.

Requirements:

- Use web research; do not invent feed URLs.
- Include only direct RSS or Atom endpoints accessible without authentication.
- Verify every endpoint returns a successful response and parseable RSS/Atom content.
- Prefer actively updated general-news feeds over narrow topic feeds.
- Avoid duplicate feeds, abandoned feeds, aggregators that merely republish one source, and feeds containing only promotional content.
- Use a diverse source set rather than multiple nearly identical feeds from one publisher.
- Generate a unique UUID v4 for every source.
- Set `source_type` to `rss` or `atom` according to the verified format.
- Use regions exactly `World`, `Russia`, or `Spain`.
- Use ISO 3166-1 alpha-2 uppercase `country_code`; use the publisher's home country for World sources.
- Use an appropriate BCP 47 language code such as `en`, `ru`, or `es`.
- Set `enabled` to `true`.
- Assign `quality_score` from 0.00 to 1.00 based on editorial reputation, transparency, original reporting, and reliability. Do not treat viewpoint agreement as quality.
- Set `polling_interval_seconds` between 900 and 3600 based on update frequency.
- Set `credential_ref` to `null`.
- Do not modify any other files.

The file must match this exact structure and contain no additional fields:

{
  "schema_version": "1.0",
  "sources": [
    {
      "id": "UUID-V4",
      "name": "Publisher or feed name",
      "source_type": "rss",
      "endpoint_url": "https://example.com/feed.xml",
      "region": "World",
      "country_code": "US",
      "language_code": "en",
      "enabled": true,
      "quality_score": 0.85,
      "polling_interval_seconds": 1800,
      "credential_ref": null
    }
  ]
}

Before finishing:

1. Validate that `sources.json` is valid JSON.
2. Confirm all IDs and endpoint URLs are unique.
3. Re-fetch every endpoint and remove any unavailable or non-feed URL.
4. If the repository CLI is available, run:
   `anxious-news-sources validate sources.json`
5. Fix all validation errors.

Return a concise summary listing the number of verified sources per region, any candidates rejected during verification, and the path to `sources.json`.
```
