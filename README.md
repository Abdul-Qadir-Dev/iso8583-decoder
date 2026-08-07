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
- **Reveal** is an explicit opt-in flag, off by default. When the API exists
  it will thread this flag through as a request parameter, not a config
  setting someone can forget is on.

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
