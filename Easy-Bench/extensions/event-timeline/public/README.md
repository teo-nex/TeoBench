# Reconstruct request attempts

Use `logs.json` to reconstruct the attempts for trace `tr-52`. A retry reuses the trace ID, so the trace ID alone does not identify an attempt.

1. Convert timestamps to UTC using their explicit offsets. Then add the signed correction in `clock_corrections_seconds` for the event's service. Corrections apply to both gateway starts and responses.
2. Keep only this trace's `start` and `response` rows. For a repeated response `event_id`, retain only the row with the highest `revision`. A newer revision supersedes the older row even if it changes the corrected time or code.
3. Each gateway start opens an attempt. Assign responses to the latest start at or before their corrected time. A response exactly on a retry boundary belongs to the retry. Discard responses before the first start.
4. Return one JSON object with the sole key `attempts`. Each attempt has exactly `attempt_id`, `started_at_utc`, and `responses`. Include starts in chronological order, including those without responses. Each response has exactly `event_id`, `at_utc`, and integer `code`. Sort responses by corrected time and then by event ID in ascending order. Format all UTC timestamps as `YYYY-MM-DDTHH:MM:SSZ`.
