# NINTH MelBet Helper

An unpacked Chrome/Edge Manifest V3 extension that transfers validated
**Moneyline**, **Totals**, **Mixed**, and **Player Props** builder legs from
NINTH to MelBet.

It also powers **Alter Ego**: with a Bet history slip selected on MelBet,
NINTH can read the complete scrollable leg drawer into local history, update
that slip by number, and analyze settled hit rate, near misses, market/side
performance, odds bands, card length, ROI, and repeated exposure.

## Install locally

1. Open `chrome://extensions` (or `edge://extensions`).
2. Turn on **Developer mode**.
3. Choose **Load unpacked** and select this `melbet-helper` folder.
4. Keep the MelBet tab active while the helper works; canvas-rendered markets can only be clicked while visible.

When the unpacked helper is reloaded after an update, it automatically refreshes
open NINTH tabs and any active NINTH MelBet handoff tab so Chrome injects the
new content scripts instead of leaving an invalidated message bridge behind.

The helper starts on `mel-bet.et`. If that host does not render the market grid within roughly 15 seconds, it automatically retries the same event and session on `melbet-322491.top`, then keeps the proxy host for the remaining legs.

If MelBet opens without restoring the signed-in session or its market canvas is
not yet clickable, the helper refreshes that exact event once. The helper
explicitly checks MelBet's account header before every selection; if the
Registration/Login state remains after the recovery refresh, it stops without
clicking. After a successful refresh it repeats the event, player, prop, side,
and threshold validation before clicking anything.

## Use

1. Build a Moneyline, Totals, Mixed, or Player Props card in NINTH.
2. Choose **Send to MelBet**.
3. Choose **Autofill all**.
4. Use **Stop autofill** in either NINTH or the MelBet status panel whenever
   you want to cancel. The current tab stays open and no later leg is clicked.
5. Review the completed MelBet betslip yourself before entering a stake.

Version 1.0.12 uses ordinary validated DOM controls for moneylines and a
short-lived Chrome debugger attachment for real browser-level input on
MelBet's canvas. Chrome may briefly show that the helper
is debugging the MelBet tab. The attachment is removed immediately after each
click. Reload the unpacked extension after updating so Chrome grants the new
permission.

Version 1.1.0 adds the read-only Alter Ego history bridge. It collects only
the selected slip's number, placement time, structure, prices, results, and
legs; it does not collect account identity, balance, credentials, or cookies.

Version 1.1.1 adds **Import all missing**. It walks MelBet's virtualized rows
for the currently applied history filter, skips slip numbers already stored by
NINTH, opens and fully reads only missing slips, then restores the original
page and selected-slip position.

## Safety contract

- Every selection is revalidated against MelBet immediately before its click.
- Moneylines are matched by exact event ID, both teams, and W1/W2 on the
  single baseball board. Mixed cards batch these board selections first.
  These normal DOM buttons avoid the canvas/debugger bridge used by deeper
  markets. MelBet's current exact selected-button state confirms the addition
  immediately even when a price change replaces the original clicked DOM node
  while the bet-slip text is still rendering.
  Both MelBet's top carousel cards and its main MLB dashboard rows are supported;
  dashboard W1/W2 controls are validated from their accessible labels.
- Full-game totals are matched only in **Regular time → Total**, using MelBet
  group 17, exact Over/Under type, and the exact paired threshold.
- Player props are matched by exact event ID, player, MelBet market group,
  selection type, side, and displayed threshold. This includes the one-sided
  `N Or More` Extra Total ladders, direct `Player To Score Home Run` selections,
  pitcher Yes/No decisions, and a lone displayed Over or Under when MelBet does
  not offer its counterpart. The feed follows MelBet's advertised selection
  count instead of stopping at its first 250 lazy-loaded selections.
- NINTH passes MelBet's exact displayed player name into the helper. A
  conservative fallback handles accents, omitted/full middle names, initials,
  suffixes, and a minor first-name spelling difference only when the exact
  surname match is unique; ambiguous candidates stop without clicking.
- The helper advances only after the exact player, side, and threshold appears in MelBet's bet slip.
- If MelBet does not confirm a click, the helper retries up to three times.
  Before every retry it checks whether the delayed selection already appeared,
  re-isolates the exact market, resets the canvas position, and revalidates the
  click point. This prevents a delayed first click from being toggled back off.
- Each click gets a short bet-slip confirmation window; an increased MelBet leg
  count is also accepted when its signed-in layout does not expose the exact
  selection text to the helper.
- Deep market rows are positioned with real wheel input on MelBet's fixed
  canvas renderer before the browser-level click is issued.
- Retained canvas-renderer position is reset before every leg without moving
  or blanking the canvas element itself.
- MelBet's own market search isolates the exact prop family before positioning
  a row, submits the search with browser-level keyboard input, and verifies the
  filtered group's height before any click. This eliminates vertical drift
  from unrelated market groups and stale, unsubmitted search text.
- Because MelBet replaces its canvas when a search is applied, the helper
  reacquires the current rendered canvas after every isolation before measuring
  its viewport bounds or sending input.
- Short filtered markets are accepted only at their feed-derived height. Long
  filtered markets are validated as virtualized results only when the exact
  target row exists in MelBet's scrollable extent; stale retained scroll height
  cannot invalidate a correctly shrunken result.
- One-sided batter `N Or More` and direct `Yes` feeds are translated from
  MelBet's flat feed order into its three balanced desktop columns. Pitcher
  strikeout ladders retain MelBet's single full-width vertical-list order.
- Canvas visibility is checked inside the filtered market's real content
  bounds, rather than against MelBet's fixed 850-pixel backing canvas.
- If an isolated market initially sits below the browser viewport, the helper
  reveals it and makes bounded document-scroll corrections until the canvas is
  visible. As soon as the helper boots, it clears the proxy fallback timer;
  authentication, market, viewport, and click errors therefore remain on the
  primary host and stop safely without refreshing into the proxy.
- The active helper version is displayed in the on-page status overlay.
- Cancellation is persisted in the session, clears fallback timers, detaches
  active browser input, and is rechecked before every trusted scroll, key, or click.
- A changed or missing line stops the whole handoff.
- Primary-host loading failure automatically falls back to the configured proxy without changing the event or selection.
- Sessions expire after 15 minutes and are kept in `chrome.storage.session` only.
- The extension never reads credentials, fills a stake, presses a confirmation button, or submits a wager.
The bundled manifest connects to NINTH on `localhost` / `127.0.0.1`. Before VPS deployment, add the final NINTH origin to the first content script's `matches` list in `manifest.json`.
