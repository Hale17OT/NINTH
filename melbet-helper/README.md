# NINTH MelBet Helper

An unpacked Chrome/Edge Manifest V3 extension that transfers validated
**Moneyline**, **Totals**, **Mixed**, and **Player Props** builder legs from
NINTH to MelBet.

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
4. Review the completed MelBet betslip yourself before entering a stake.

Version 0.7 uses ordinary validated DOM controls for moneylines and a
short-lived Chrome debugger attachment for real browser-level input on
MelBet's canvas. Chrome may briefly show that the helper
is debugging the MelBet tab. The attachment is removed immediately after each
click. Reload the unpacked extension after updating so Chrome grants the new
permission.

## Safety contract

- Every selection is revalidated against MelBet immediately before its click.
- Moneylines are matched by exact event ID, both teams, and W1/W2 on the
  single baseball board. Mixed cards batch these board selections first.
  These normal DOM buttons avoid the canvas/debugger bridge used by deeper
  markets. MelBet's exact selected-button state confirms the addition
  immediately while the bet-slip text finishes rendering.
- Full-game totals are matched only in **Regular time → Total**, using MelBet
  group 17, exact Over/Under type, and the exact paired threshold.
- Player props are matched by exact event ID, player, prop, side, and threshold.
- Accented player names are folded before matching (`Jesús` and `Jesus` match).
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
- Canvas visibility is checked inside the filtered market's real content
  bounds, rather than against MelBet's fixed 850-pixel backing canvas.
- The active helper version is displayed in the on-page status overlay.
- A changed or missing line stops the whole handoff.
- Primary-host loading failure automatically falls back to the configured proxy without changing the event or selection.
- Sessions expire after 15 minutes and are kept in `chrome.storage.session` only.
- The extension never reads credentials, fills a stake, presses a confirmation button, or submits a wager.
The bundled manifest connects to NINTH on `localhost` / `127.0.0.1`. Before VPS deployment, add the final NINTH origin to the first content script's `matches` list in `manifest.json`.
