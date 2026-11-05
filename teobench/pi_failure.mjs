// Public receipts contain fixed categories, never provider text or credentials.
export function providerFailure(message) {
  const reason = ['stop','length','toolUse','error','aborted'].includes(message?.stopReason)
    ? message.stopReason : 'unknown';
  const text = typeof message?.errorMessage === 'string' ? message.errorMessage : '';
  const rules = [
    ['session_limit', /(?:too many|maximum|max|limit).{0,60}(?:sessions|concurrent)|session.{0,40}limit/i],
    ['quota_limit', /rate.?limit|quota|usage.?limit|\b429\b/i],
    ['authentication', /unauthorized|authentication|\b401\b/i],
    ['access_denied', /forbidden|access denied|not allowed|\b403\b/i],
    ['model_unavailable', /model.{0,80}(?:not found|not supported|unavailable)|unsupported.{0,30}model|\b404\b/i],
    ['timeout', /timed? out|timeout/i],
    ['upstream_server', /internal server|bad gateway|service unavailable|\b50[0234]\b/i],
    ['network', /ECONNRESET|ECONNREFUSED|fetch failed|network error/i],
  ];
  return {stop_reason: reason, category: rules.find(([,pattern]) => pattern.test(text))?.[0] || 'unknown'};
}
