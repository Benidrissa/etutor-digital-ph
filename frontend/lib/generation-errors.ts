/**
 * True when a failed generation task's error indicates the AI provider
 * rejected the call for quota/rate reasons (e.g. OpenAI
 * `429 insufficient_quota` on the embeddings call). The raw payload is
 * long and technical — well over the 200-char passthrough limit the
 * viewers apply — so callers should show the `providerUnavailable`
 * i18n copy instead (#2554).
 */
export function isProviderQuotaError(rawError?: string): boolean {
  if (!rawError) return false;
  const lowered = rawError.toLowerCase();
  return (
    lowered.includes('insufficient_quota') ||
    lowered.includes('exceeded your current quota') ||
    lowered.includes('error code: 429') ||
    lowered.includes('rate_limit_exceeded')
  );
}
