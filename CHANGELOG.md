# Changelog

## 0.2.0 — 2026-10-05

- OpenRouter is read as money instead of time windows. Its card now has two gauges, Balance and
  Per-key limit, each showing what is left in dollars where a time vendor shows its reset, plus
  today/week/month spend in the footer. It had no gauges at all before, because the vendor puts the
  bar and the percentage on separate lines.
- The gauges are ordered by how much is spent, so the headline figure is the limit that actually
  binds — a balance barely touched no longer hides a cap about to block every request.
- No fragment of an API key can reach the screen. Every label built from a vendor tooltip is
  redacted; OpenRouter's tooltip title carries part of the key, and it used to be shown as the plan.
- A figure the popup cannot read now costs its own gauge and says so on stderr, instead of
  discarding the card or reporting a working account as unavailable.

## 0.1.0 — 2026-10-03

First public release.

- GTK 3 popup with one card per vendor: Claude, Codex (OpenAI), Z.AI, OpenRouter, DeepSeek and Kimi.
- Usage gauges per window (session, weekly…), with the time left until each reset.
- Z.AI read straight from its quota API, so Lite plans (credit limits) show real numbers.
- Vendors without credentials are grouped under "Not configured", with what to set.
- Manual refresh; all vendors are read in parallel.
- `install.sh` for a per-user install (no sudo), with `--uninstall`.
