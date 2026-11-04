# Streaming transport for external inference adapters

TeoBench does not bundle a universal model/API runner. The participant's agent
owns authentication, HTTP/SSE decoding, model selection and request scheduling.
`teobench.response_stream` is an **opt-in, provider-independent event collector**
for adapters that already receive decoded Responses-style event dictionaries.
It performs no network requests, credential access, logging, file writes,
retries, grading or submission. Existing CLI behaviour is unchanged.

## Why a completed response can become a false timeout

An external adapter can receive `response.completed` and still wait for the HTTP
connection to close. If that connection stays open, an EOF-driven reader can
reach the trial deadline after the answer has already arrived. Returning from
the terminal-event handler avoids that particular false timeout.

This failure mode was reproduced in a participant's external adapter, not in
TeoBench's grader. It does not establish the cause of every timeout in a past
study, and the helper does not fix a model that genuinely exceeds its deadline.

## Completion contract

- Return immediately after `response.completed` **and** nested
  `response.status == "completed"`, including an empty completed output.
- Treat `response.failed`, `response.incomplete`, an `error` event, contradictory
  event/status pairs and EOF without a terminal event as transport failures.
- Preserve a nested error code, with the outer code as a fallback when the
  nested object contains only a message. Keep incomplete reasons separately.
- Prefer authoritative terminal output. When a gateway omits it, reconstruct
  only received items/deltas; never guess missing tool IDs or tool results.
- Retain partial text, function calls and argument fragments on failure.
  `partial_output` prefers terminal output; `received_output` also preserves
  what arrived before it. Both are copies, not mutable views of internal state.
- Preserve iterator exceptions and cancellation. No retry or route substitution
  is performed. A finalized state cannot be reused for another request.

The synchronous `collect_response(events)` and asynchronous
`collect_response_async(events)` consume decoded events only until completion.
They do not decode raw SSE lines and do not own the underlying HTTP response.
The caller must close that response when the collector returns or raises.

## Deadline and response ownership

With Python 3.11+ an adapter can wrap its own HTTP client as follows:

```python
import asyncio
from teobench.response_stream import ResponseStream, collect_response_async


async def read_response(open_response, decode_events, state, deadline):
    async with asyncio.timeout_at(deadline):
        async with open_response() as response:
            return await collect_response_async(decode_events(response), state=state)
```

`open_response` and `decode_events` above are supplied by the participant's
existing client, not by this module. Create a fresh `ResponseStream()` in the
caller for every physical response and retain it outside the timeout context.
On a timeout, cancellation or read error its `partial_output` and
`received_output` remain available for private evidence. A received fragment is
not a completed answer or a trusted lookup-execution receipt.

Use the original **240-second trial deadline across all per-trial queueing,
requests and tool rounds**, not a new 240-second budget for each response.
Complete credential preparation before starting a measured attempt, or bound it
without leaving refresh work running after cancellation. Give response/resource
cleanup its own explicit bounded policy; cancelling an await does not prove an
owned subprocess or worker thread has stopped.

Keep the existing global request gap, worker/per-model limits, exact model and
effort settings, tool/token budgets and
[full campaign order](RUN_FULL_STUDY.md). This helper neither verifies model
identity nor enforces scheduling; the adapter must still check its route and
response metadata. Do not add best-of retries to make a condition pass.

## Evidence and published studies

`ResponseStreamError.kind` is a stable classification; its default error text
does not echo provider messages or account metadata. Its `code`, partial output
and received output still contain provider/model data: inspect and redact them
before logging or sharing. Do not dump full response objects, authorization,
cookies, account IDs, `safety_identifier` or local paths into a public report.
The collector does not write any of these fields itself.

A private-evidence write failure must not hide the original request outcome or
turn a completed answer into a model error. Report that persistence failure as
an infrastructure warning and preserve any already received result.

Record transport failures using the existing study format, separately from
wrong answers. Follow [CONTRIBUTING.md](../CONTRIBUTING.md) for the empty scored
answer on an unfinished request; keep fragments as private evidence rather than
claiming they are a final solution. A new diagnostic request is a new
observation, not permission to replace the original failed slot. This helper
changes no frozen tasks, scores, grader digest, schema or accepted study.

## Offline regression coverage

```sh
python -m unittest discover -s tests -p test_response_stream.py -v
```

The tests use synthetic decoded streams, including a connection that stays open
after completion, terminal failures, nested/outer error codes, missing terminal
events, cancellation/timeouts and interrupted function-call arguments. They
make no model calls and do not execute generated code. Sandbox/CLI verification
continues to run in the repository's existing test suite.
