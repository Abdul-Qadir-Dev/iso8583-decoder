# ISO 8583 Message Decoder

Work in progress. Full overview, architecture, and setup sections land once the
parser and API exist; this file starts here because a couple of design
decisions are worth writing down as they're made, not reconstructed later.

## Design decisions

### Sensitive data handling

Card numbers and PIN blocks pass through this tool because troubleshooting
ISO 8583 traffic means looking at real messages. That doesn't mean the tool
should display them.

- **Masked** (PAN, and PANs embedded in track 1/2 data): shown as first 6 +
  last 4, the middle replaced with `*`. Enough to confirm you're looking at
  the right card without exposing the full number.
- **Redacted** (PIN block, security-related control information): never
  shown. Not "shown if you ask nicely" -- there is no troubleshooting reason
  to render a PIN block, so it isn't an option. Output is just
  `[redacted, N bytes]`.
- **Reveal** is an explicit opt-in flag, off by default. `POST /decode`
  threads it through as a request field (`reveal: bool = false`), not a
  config setting someone can forget is on.

Masking dispatches on a declared strategy in the spec, not on field number:
a processor whose PAN sits in a different field marks it in YAML, without
touching renderer code.

This lives at the render layer, not the parser. The parser always carries
the true decoded value; masking is applied only at the point a value becomes
displayed text. That's deliberate: it means the same masking rule covers the
decoded-field table, the diagnostics panel, and error messages, instead of
being something each output path has to remember to apply on its own. The
usual way these tools leak data isn't the happy path, it's an exception
message that interpolates the raw value it was complaining about.

Masking also fails closed. Track 1/2 data only gets partially masked (PAN
hidden, rest of the track shown) when the format is recognized; anything
that doesn't match a known track layout gets masked in full rather than
risk exposing a PAN in a shape the code didn't anticipate.

Which fields are masked or redacted, and which masking strategy applies, is
data in the spec file (`sensitivity` and `mask_strategy` per field) rather
than a field-number check inside the renderer.

### API security posture

`iso8583_decoder/api.py` has no authentication layer. That's a deliberate
scope decision, not an oversight: this is a local/internal troubleshooting
tool, and bolting on an auth scheme just to satisfy a checklist would be
security theater without a real deployment story behind it. **Do not expose
this API on a public or shared network as-is.** If it's ever deployed
somewhere reachable by anyone other than its operator, it needs a real auth
layer first.

What the API does enforce:

- The raw message body is never logged, echoed, or persisted anywhere.
  Request logs carry only endpoint, encoding, byte length, and diagnostic
  codes -- never message content or decoded field values.
- Unhandled exceptions return a fixed, generic `{"detail": "internal server
  error"}` body and log only the exception's type name, never `str(exc)` or
  a traceback, since an internal exception message could in principle embed
  a raw field value.
- Request bodies over 64 KB are rejected with 413 before any handler runs.
- Decoded fields are masked/redacted by default in every response
  (`reveal: bool = false`), same rule as the render layer above.

A message that fails to decode -- a stop, a diagnostic, a partial result --
is still a successful API call and returns `200` with the result in the
body. 4xx is reserved for a malformed *request* (missing `encoding`, an
invalid encoding value, an oversized body); 5xx is reserved for actual
server bugs. Even the two cases where `decode_message()` can't produce a
result at all (an MTI too broken to read, or an MTI version with no mapped
spec) come back as `200` with `partial: true` and a `reason_code`, not an
HTTP error -- the JSON request was well-formed even though the ISO 8583
message inside it wasn't, and that's what decides the status code.
