import assert from 'node:assert/strict';
import {test} from 'node:test';
import {providerFailure} from '../teobench/pi_failure.mjs';

test('classifies blockers without retaining provider text, tokens or paths', () => {
  for (const [text,category] of [
    ['429 Rate limit exceeded','quota_limit'],
    ['Maximum concurrent sessions exceeded','session_limit'],
    ['403 Model not allowed','access_denied'],
    ['401 Unauthorized','authentication'],
    ['Model is not supported','model_unavailable'],
    ['fetch failed','network'],
    ['504 Gateway timeout','timeout'],
    ['502 Bad gateway','upstream_server'],
    ['unrecognized provider error','unknown'],
  ]) {
    const value=providerFailure({stopReason:'error',errorMessage:text+' sk-secret /Users/private me@example.com'});
    assert.deepEqual(value,{stop_reason:'error',category});
    assert(!JSON.stringify(value).includes('secret'));
  }
});

test('provider-controlled fields cannot escape the fixed schema', () => {
  assert.deepEqual(providerFailure({stopReason:'sk-private',errorMessage:{secret:1}}),
    {stop_reason:'unknown',category:'unknown'});
  assert.deepEqual(providerFailure(null),{stop_reason:'unknown',category:'unknown'});
});
