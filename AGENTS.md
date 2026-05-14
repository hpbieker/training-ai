# Project Instructions

- When the user asks for analyses or comparisons, answer in chat by default.
- Do not create standalone report files for analyses or comparisons unless the user explicitly asks for a file.
- Treat `data/` as temporary local cache/output. It is ignored by git and can contain downloaded activities, streams, scratch outputs and generated reports when explicitly requested.
- For workout analyses, exclude warm-up and cooldown from interval metrics. The user typically warms up for about 12 minutes and cools down for about 3 minutes. Prefer detecting the actual work segment from the power trace rather than using the full stream: look for the point where power rises into a stable target such as 195 W, 200 W, 205 W or the relevant interval target. There is usually a small step up in watts when the work interval starts.
