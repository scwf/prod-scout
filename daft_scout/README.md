# Daft Scout Pipeline

Daft-based reimplementation of the crawler, organized as a pipeline with clear stages.

## Entry Point

```bash
python daft_scout/pipeline.py
```

## Pipeline Stages

- Source fetch: RSS sources (Weixin / YouTube / X) with Daft concurrency
- Content enrich: embedded links + YouTube subtitles
- LLM organize: structure content with LLM
- Result write: write Markdown + stats + manifest

## Project Layout

```
daft_scout/
  pipeline.py                # Main pipeline entry
  common.py                  # Shared helpers (logger, constants)
  stages/
    source_fetcher.py        # RSS fetching stage
    content_enricher.py      # Content enrichment stage
    llm_organizer.py         # LLM organizing stage
    result_writer.py         # Output writing + stats/manifest
  utils/
    content_fetcher.py       # Web fetch + embedded content utilities
```

## Configuration

- Reads `config-test.ini` from repo root by default.
- LLM settings are taken from the `llm` section in the config file.
- X rate limiting uses `crawler.x_request_delay_min/max`.

## Notes

- Requires `daft` plus existing crawler dependencies (feedparser, requests, selenium, webdriver-manager, beautifulsoup4).
- Output is written under `data/` with a batch timestamp.
- Manifest filename: `latest_batch_daft.json`.
