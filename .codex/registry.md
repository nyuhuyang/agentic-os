# Skill Registry

Generated: 2026-05-11 03:25 UTC · 20 skills

| Skill | Stack | Risk | Confirm? | Exec mode | Schedulable | Entrypoint |
| --- | --- | --- | --- | --- | --- | --- |
| `critique` | uncategorized | read | — | local_only | — | — |
| `dashboard` | uncategorized | read | — | local_only | — | — |
| `docs-page` | uncategorized | read | — | local_only | — | — |
| `llm-wiki-ingest` | knowledge | write | — | local_only | — | — |
| `llm-wiki-lint` | knowledge | read | — | local_only | yes | `.codex/skills/llm-wiki-lint/lint.py` |
| `llm-wiki-research` | knowledge | write | — | local_only | yes | — |
| `llm-wiki-save` | knowledge | write | — | local_only | — | — |
| `mobile-app` | uncategorized | read | — | local_only | — | — |
| `mobile-onboarding` | uncategorized | read | — | local_only | — | — |
| `notebooklm` | research | external | **yes** | local_only | — | — |
| `pricing-page` | uncategorized | read | — | local_only | — | — |
| `saas-landing` | uncategorized | read | — | local_only | — | — |
| `skill-creator` | admin | write | — | local_only | — | — |
| `skill-registry` | admin | write | — | local_only | yes | `.codex/skills/skill-registry/scripts/build_registry.py` |
| `waitlist-page` | uncategorized | read | — | local_only | — | — |
| `web-prototype` | uncategorized | read | — | local_only | — | — |
| `wireframe-sketch` | uncategorized | read | — | local_only | — | — |
| `youtube-search` | research | external | — | remote_ok | yes | `.codex/skills/youtube-search/scripts/search.py` |
| `yt-pipeline` | research | external | **yes** | local_only | yes | `.codex/skills/yt-pipeline/scripts/pipeline.py` |
| `yt-transcript` | research | external | — | local_only | yes | `.codex/skills/yt-transcript/scripts/fetch_transcript.py` |

## Stack summary

| Stack | Skills |
| --- | --- |
| admin | `skill-creator`, `skill-registry` |
| knowledge | `llm-wiki-ingest`, `llm-wiki-lint`, `llm-wiki-research`, `llm-wiki-save` |
| research | `notebooklm`, `youtube-search`, `yt-pipeline`, `yt-transcript` |
| uncategorized | `critique`, `dashboard`, `docs-page`, `mobile-app`, `mobile-onboarding`, `pricing-page`, `saas-landing`, `waitlist-page`, `web-prototype`, `wireframe-sketch` |

## Schedulable skills

- **`llm-wiki-lint`** (local_only) — .codex/skills/llm-wiki-lint/lint.py
- **`llm-wiki-research`** (local_only) — no script (AI-only)
- **`skill-registry`** (local_only) — .codex/skills/skill-registry/scripts/build_registry.py
- **`youtube-search`** (remote_ok) — .codex/skills/youtube-search/scripts/search.py
- **`yt-pipeline`** (local_only) — .codex/skills/yt-pipeline/scripts/pipeline.py
- **`yt-transcript`** (local_only) — .codex/skills/yt-transcript/scripts/fetch_transcript.py
