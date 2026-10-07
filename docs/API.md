# Same-origin JSON API

The v1 API is served by the Flask application. It is intended for same-origin use by the web interface or trusted tooling in the same browser origin. It has no accounts or CORS access for arbitrary sites. Keep the default local server on loopback. In `server` mode, requests must arrive through the explicitly trusted HTTPS reverse-proxy boundary and pass the exact Host, Origin, and CSRF checks.

## Routes

| Method and path | Purpose |
| --- | --- |
| `GET /api/v1/health` | Legacy liveness response: `{"status":"ok","api_version":"v1"}`. |
| `GET /api/v1/health/live` | Liveness-only response: `{"status":"live"}`. |
| `GET /api/v1/health/ready` | Checks review-worker and limiter readiness; returns `{"status":"ready"}` or a generic `503` `{"status":"not_ready"}`. |
| `GET /api/v1/csrf` | Returns a signed `csrf_token` and sets its matching `HttpOnly`, `SameSite=Strict` `ra_csrf` cookie. The token expires after 30 minutes by default. |
| `POST /api/v1/audit` | Returns human review prompts, visible citation cues, and repetition counts. It has no dedicated full-source field; bounded sentence/citation excerpts are included as review evidence and may equal a short input. |
| `POST /api/v1/revise` | Returns the revised text, proposed edits, and a bounded diff. It does not modify a local or uploaded source file. |

## Request contract

POST bodies must be `application/json` objects with a required string `text` and optional fields:

| Field | Accepted values | Default |
| --- | --- | --- |
| `source_format` | `txt`, `tex`; a leading dot is accepted | `txt` |
| `content_language` | `en`, `fr` | `en` |

The `content_language` field describes the document analyzed and revised. It is independent of the web-shell `locale`. Unknown fields and implicit type conversions are rejected. The text limit is 250,000 Unicode code points, 1,000,000 UTF-8 bytes, and 10,000 lines. The HTTP request cap is 1,100,000 bytes; uploads are available only through the HTML form and are bounded separately. Requests exceeding a limit are rejected rather than truncated.

## Same-origin flow

Fetch a token first and preserve the cookie for the POST:

```js
const bootstrap = await fetch("/api/v1/csrf", {
  credentials: "same-origin",
});
const { csrf_token } = await bootstrap.json();

const response = await fetch("/api/v1/audit", {
  method: "POST",
  credentials: "same-origin",
  headers: {
    "Content-Type": "application/json",
    "X-CSRF-Token": csrf_token,
  },
  body: JSON.stringify({
    text: "The fictional instrument records one sample every two seconds.",
    source_format: "txt",
    content_language: "en",
  }),
});
const result = await response.json();
```

Keep the token in page memory. The server checks the host, same-origin `Origin` or `Referer`, secure scheme in public mode, and CSRF cookie/token pair. Do not add permissive CORS headers or accept opaque `Origin: null` requests.

## Audit response

Successful audit responses include:

```json
{
  "source_format": "txt",
  "content_language": "en",
  "summary": {
    "word_count": 9,
    "sentence_count": 1,
    "finding_count": 0,
    "citation_cue_count": 0
  },
  "notes": ["Prompts use visible text and citation markers; no external sources are looked up."],
  "findings": [],
  "findings_summary": {"total_count": 0, "displayed_count": 0, "omitted_count": 0, "limit": 30},
  "citation_cues": [],
  "citation_cues_summary": {"total_count": 0, "displayed_count": 0, "omitted_count": 0, "limit": 30},
  "repetition": {"repeated_starts": [], "repeated_phrases": []}
}
```

Each finding contains a stable `code`, `category`, one-based `sentence_index` and original-source `line`, localized `reason` and `prompt`, and a sentence excerpt. Optional evidence fields include `phrase`, `count`, `occurrences`, and `citation_keys`. Findings are prompts, not judgments. Current codes are:

- `repeated_sentence_start`
- `repeated_phrase`
- `long_sentence`
- `dense_sentence`
- `formulaic_phrase`
- `claim_needs_source`
- `citation_context_prompt`

Citation cue objects report recognized visible syntax and keys/labels, source line and sentence, and an excerpt. They do not resolve TeX keys or retrieve/check URLs, DOI records, bibliography entries, or source content. The service does not verify whether a cited source exists, is relevant, or supports a statement; it does not determine factuality, plagiarism, or authorship. For measured scope and fixture counts, see [language cue evaluation](EVALUATION.md).

When a recognized visible citation immediately follows terminal punctuation, the API associates it with the preceding sentence by proximity. A clear narrative author-date prefix such as `Smith (2024)` or an explicit narrative TeX citation such as `\textcite{smith2024}` or `\citet{smith2024}` remains with the following sentence. This positional association is only a review cue; it does not establish that the source supports the statement.

The API limits displayed findings and citation cues to 30 each and reports total/displayed/omitted counts. Repetition summaries display at most 15 values of each type. These are output-size bounds, not confidence or quality scores.

Revision responses contain `source_format`, `content_language`, `revised_text`, up to 50 bounded `edits`, an `edits_summary`, and a diff capped at 150,000 characters with `diff_truncated`. Proposed phrase substitutions are intentionally limited; compare the result with the source before using it.

## Errors and throttling

Errors return JSON such as `{"error":{"code":"…","message":"…","field":"text","request_id":"…"}}`. `field` and server-generated `request_id` appear when applicable. Messages are localized to the interface locale. Common statuses:

| Status | Meaning |
| --- | --- |
| `400` | Malformed JSON, invalid object, unsupported field, or invalid field value. |
| `403` | CSRF or origin validation failed. |
| `413` | Request, text, upload, or line limit exceeded. |
| `415` | Unsupported media type. |
| `429` | Per-client rolling-window limit exceeded; `Retry-After` indicates the wait. |
| `503` | Shared limiter or analysis capacity unavailable; retry later. |
| `504` | Analysis exceeded its wall-clock deadline. |

The local profile uses a bounded in-memory per-process limiter. Public `server` mode uses Redis for an atomic shared rolling-window quota across app replicas; Redis failure or active-client capacity exhaustion fails closed with generic `503`. The public deployment currently configures 30 analyses per 60 seconds and a maximum of 4,096 active client identities. Identities are HMAC-derived and Redis stores quota metadata only. See [the public deployment runbook](PRODUCTION.md) and [security notes](SECURITY.md).
