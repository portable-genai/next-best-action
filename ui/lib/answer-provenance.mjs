// Which model answered the console's last request, read off the service's own responses.
//
// The service's model adapters NOTE the model that answered (and whether an online search tool
// was used) as they call, and `hex_service_kit.web.install_answer_provenance` turns that into two
// response headers, exposed to a cross-origin reader. A request that noted nothing carries
// neither, so nothing here ever guesses a model: no header, no answer.
//
// The console reads the headers through ONE `window.fetch` wrapper, installed when the first
// listener subscribes and restored when the last one leaves, so no call site in the console has
// to be edited to report what answered it. Plain JavaScript so `npm test` runs it in bare node.
//
// This console calls its service at the API base `lib/api` resolves (`NEXT_PUBLIC_API_BASE`),
// not through a same-origin proxy, so "the console's own API" is every URL under that base.

/** Every distinct model that answered the request, in call order, comma-separated. */
export const ANSWERED_BY = "x-answered-by";
/** `true` when a call in the request used an online search tool. */
export const SEARCH_USED = "x-search-used";

/**
 * The answer a response carries, or `null` when it named no model.
 *
 * @param {{ get(name: string): string | null }} headers
 * @returns {{ model: string, search: boolean } | null}
 */
export function answerOf(headers) {
  const model = (headers.get(ANSWERED_BY) ?? "").trim();
  if (!model) return null;
  return { model, search: headers.get(SEARCH_USED) === "true" };
}

/**
 * True when `input` addresses this console's own API: the same origin as `apiBase` and a path
 * at or under its path.
 *
 * @param {unknown} input what was handed to `fetch`
 * @param {string} apiBase the API base the console calls, absolute or page-relative
 * @param {string} here the page's own URL
 */
export function isConsoleApi(input, apiBase, here) {
  let raw;
  if (typeof input === "string") raw = input;
  else if (input instanceof URL) raw = input.href;
  else if (input && typeof (/** @type {{ url?: unknown }} */ (input).url) === "string") {
    raw = /** @type {{ url: string }} */ (input).url;
  } else return false;
  try {
    const url = new URL(raw, here);
    const base = new URL(apiBase, here);
    if (url.origin !== base.origin) return false;
    const prefix = base.pathname.replace(/\/+$/, "");
    return prefix === "" || url.pathname === prefix || url.pathname.startsWith(prefix + "/");
  } catch {
    return false;
  }
}

/** @type {Set<(answer: { model: string, search: boolean }) => void>} */
const listeners = new Set();
/** @type {{ host: any, original: any, wrapped: any } | null} */
let installed = null;

/**
 * Call `listener` with every answer the console's own API responses carry.
 *
 * Idempotent: however many listeners subscribe, `host.fetch` is wrapped once, and the original is
 * put back when the last listener unsubscribes (unless something else has replaced the wrapper
 * since, which is left alone rather than clobbered).
 *
 * @param {{ fetch: any, location: { href: string } }} host `window`, or a stand-in in a test
 * @param {string} apiBase the API base the console calls
 * @param {(answer: { model: string, search: boolean }) => void} listener
 * @returns {() => void} unsubscribe
 */
export function watchAnswers(host, apiBase, listener) {
  listeners.add(listener);
  if (!installed) {
    const original = host.fetch;
    /** @param {unknown} input @param {unknown} init */
    const wrapped = async (input, init) => {
      const response = await original.call(host, input, init);
      if (isConsoleApi(input, apiBase, host.location.href)) {
        const answer = answerOf(response.headers);
        if (answer) for (const notify of [...listeners]) notify(answer);
      }
      return response;
    };
    host.fetch = wrapped;
    installed = { host, original, wrapped };
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && installed) {
      if (installed.host.fetch === installed.wrapped) installed.host.fetch = installed.original;
      installed = null;
    }
  };
}
