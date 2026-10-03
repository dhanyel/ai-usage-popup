# Changelog

## 0.1.0 — 2026-10-03

First public release.

- GTK 3 popup with one card per vendor: Claude, Codex (OpenAI), Z.AI, OpenRouter, DeepSeek and Kimi.
- Usage gauges per window (session, weekly…), with the time left until each reset.
- Z.AI read straight from its quota API, so Lite plans (credit limits) show real numbers.
- Vendors without credentials are grouped under "Not configured", with what to set.
- Manual refresh; all vendors are read in parallel.
- `install.sh` for a per-user install (no sudo), with `--uninstall`.
