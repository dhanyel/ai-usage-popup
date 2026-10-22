# Changelog

## 0.9.0 — 2026-10-22

- A **toolbar** presentation: the usage as a thin, undecorated, always-on-top bar pinned to the
  bottom edge of the screen at full width — one compact block per vendor, side by side, no "Not
  configured" section — for leaving it always visible like a taskbar. An **i** button opens the
  card view, and a 📌 button in the cards view pins the bar again; the choice is remembered.
- The bar reserves its strip through `_NET_WM_STRUT_PARTIAL`, so maximized windows stop above it
  instead of sliding under it, and the app runs under XWayland (`GDK_BACKEND=x11`), because a
  native Wayland client gets no say over its position or stacking.
- Each block shows three lines: the vendor, its window quota and its weekly quota. Claude drops its
  "Fable weekly" meter; a vendor with no weekly window (Qwen) shows two lines; OpenRouter shows its
  Balance and Per-key limit. Each meter line carries its own tiny status dot (green to red by that
  meter's usage), so one block can show a calm session next to a hot weekly. The toolbar's header
  is a single line (title, stamp and countdown).
- Switching between the toolbar and the cards never re-reads the vendors and never disturbs the
  automatic refresh.

## 0.3.1 — 2026-10-22

- Automatic refresh every 5 minutes, for every vendor, through the same path the ↻ Refresh button
  uses. A countdown next to the last-update stamp (`updated at HH:MM · N vendors · next in M:SS`)
  shows how long until the next cycle, so a window left open no longer silently goes stale.
- The countdown is armed when a cycle completes, not when it starts, so a slow vendor (Z.AI 15s,
  Qwen 30s) cannot eat its own interval, and a manual refresh re-arms it instead of being followed
  one second later by an automatic one. While a cycle is in flight the countdown is hidden — the
  header already says `updating…`.

## 0.3.0 — 2026-10-22

- Qwen card: Bailian Token Plan usage (monthly percentage and reset), read through the `bl` CLI —
  needs `npm i -g bailian-cli` plus a one-time `bl auth login --console`. Until then the card sits
  under "Not configured" with that fix. The vendor does not go through ai-usagebar, which does not
  know it, and the console gateway refuses the `DASHSCOPE_API_KEY`.
- The Qwen percentage is scaled from the fraction the API reports (`0.0124` = 1.25%), which used to
  read as 0% on a plan that was already being used.
- When the Qwen card cannot read, it says why. `bl` answers an expired console session with an error
  body and exit code 0, so the card used to report "no usage" — a data problem — for what is a login
  problem that dies on idle timeout every few days.
- Multiple Claude accounts: every `[[anthropic.accounts]]` entry in ai-usagebar's config gets its
  own "Claude · <label>" card, queried with `--account <label>`. Cards are re-read on every
  refresh, so adding an account to the config needs no restart. An entry whose credentials file is
  the default account's is skipped instead of rendering the same data twice.
- Cards can be reordered by dragging one onto another position; the rest shift along. The order is
  saved in `~/.config/ai-usage-popup/card-order.json` and restored on reopen, and a vendor that is
  offline keeps its slot so it comes back where it was instead of at the end.
- The window opens tall enough for four rows of cards, clamped to the screen: 940×640 cut the third
  row off once the vendor list grew.

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
