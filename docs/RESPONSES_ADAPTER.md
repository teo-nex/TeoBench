# Client-independent Responses adapter

`responses-clean-v1` runs with Python 3.9+ and the standard library. It does not
install, discover or execute Codex CLI, Pi, Node, an app-server or a personal
agent. `study create --execution-profile auto` now selects this adapter. Legacy
`pi-clean-v1` and `codex-clean-v1` remain explicit, separate historical cohorts;
their version pins and receipts are unchanged.

## Explicit gateway and subscription routing

Configure an existing Responses gateway. Authentication is read only from the
`TEOBENCH_GATEWAY_KEY` environment variable (or a name supplied with `--key-env`).
No credential file, shell command, personal settings or account token is loaded.
For subscription access the gateway must already route to the participant's
subscription provider. A gateway key authenticates to that gateway; it is not an
OpenAI paid API key. The adapter never switches providers, enables API billing,
refreshes credentials, edits the gateway or falls back to another model.

Example routing-only `transport.json` for an existing local OmniRoute:

```json
{
  "base_url": "http://127.0.0.1:20128/v1",
  "models": {
    "gpt-5.6-luna": "codex/gpt-5.6-luna",
    "gpt-6-luna": "codex/gpt-6-luna",
    "gpt-5.6-terra": "codex/gpt-5.6-terra",
    "gpt-6.1-terra": "codex/gpt-6.1-terra",
    "gpt-5.6-sol": "codex/gpt-5.6-sol",
    "gpt-6.1-sol": "codex/gpt-6.1-sol",
    "gpt-6-astra": "codex/gpt-6-astra"
  }
}
```

Other providers may use exact unprefixed IDs. Mapping is explicit and bound by a
hash in the checkpoint. Both campaign ID and routing ID are saved in each private
receipt. Distinct mappings and methods must not be pooled as one cohort. The
adapter cannot attest gateway-internal model identity, billing or hidden retries;
verify gateway configuration/logs separately. HTTP is limited to loopback; other
gateways need HTTPS. Redirects are rejected, and ambient proxy settings ignored.

## Execution

Supply the existing gateway key to the environment through the participant's
normal secret mechanism; never put it into task prompts, routing JSON or logs.
Run OS `doctor` before inference, then:

```sh
python3 -m teobench study create --id responses-study --file local-runs/responses-study.json --execution-profile auto --access-route 'explicit subscription gateway' --environment 'OS; Python version'
python3 -m teobench responses-trial --preflight --task R01 --model gpt-5.6-luna --effort high --transport transport.json --output local-runs/responses-preflight
python3 -m teobench campaign next --file local-runs/responses-study.json
python3 -m teobench responses-trial --study local-runs/responses-study.json --task R01 --model gpt-5.6-luna --effort high --replicate 1 --transport transport.json --output local-runs/responses-trial-0001
```

Preflight all 35 exact model/effort conditions in distinct output directories. It
checks local construction and authentication availability without network calls;
it does not prove server access. Follow the campaign's exact next slot through
all 1127 trials. Never reuse an old Pi/Codex checkpoint with this adapter. The
existing study lock, duplicate guard and receipt-before-grading behavior apply.

Each trial sends only the fixed system instructions, unchanged public task and
its declared lookup tool. No personal context or previous response ID is used.
Continuation inputs contain only this trial's own output and trusted lookup
receipts. References are never sent. The executor enforces lookup IDs/budgets.
Effort is sent unchanged, with a 16384 output-token cap, four-second request gap,
240-second total deadline and no adapter retries. Only a validated
`response.completed` event completes a response; EOF, failed/incomplete events,
HTTP errors and cancellation preserve partial output and become transport errors.
Receipts are persisted throughout the stream and before grading. Resume/recover
original receipts after interruption; never silently replace an attempt.

Run offline tests with `python3 -m unittest discover -s tests -v`. Synthetic HTTP
integration tests require no external model access and no optional clients.
The protocol follows the official [Responses streaming events](https://developers.openai.com/api/reference/resources/responses/streaming-events).
