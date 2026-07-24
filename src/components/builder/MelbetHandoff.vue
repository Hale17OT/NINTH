<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { Check, Copy, ExternalLink, Send, WandSparkles, X } from "lucide-vue-next";

const props = defineProps({
  entries: { type: Array, default: () => [] },
  autofillMode: { type: String, default: "" },
});

const open = ref(false);
const copied = ref(false);
const copiedEntryKey = ref(null);
const helperState = ref("idle");
const helperMessage = ref("");
let helperTimeout;
let helperRequestId = "";
const linkedCount = computed(() => props.entries.filter((entry) => entry.url).length);
const playerAutofill = computed(() => props.autofillMode === "player_prop");
const cardAutofill = computed(() => props.autofillMode === "card");
const autofillEnabled = computed(() => playerAutofill.value || cardAutofill.value);
const supportedKinds = computed(() => playerAutofill.value ? ["player_prop"] : ["moneyline", "totals"]);
const autofillReady = computed(() => autofillEnabled.value && props.entries.length > 0
  && props.entries.every((entry) => entry.url && supportedKinds.value.includes(entry.automation?.kind)));
const autofillUnavailableReason = computed(() => {
  if (!autofillEnabled.value) return "";
  if (!props.entries.length) return `Add at least one listed ${playerAutofill.value ? "player-prop" : "moneyline or total"} leg before starting autofill.`;
  const missing = props.entries.filter((entry) => !entry.url || !supportedKinds.value.includes(entry.automation?.kind)).length;
  return missing ? `${missing} selected ${missing === 1 ? "leg is" : "legs are"} no longer linked to an exact current MelBet market.` : "";
});
const transferText = computed(() => [
  "NINTH — MELBET HANDOFF",
  ...props.entries.map((entry, index) => `${index + 1}. ${entry.game}\n   ${entry.selection}`),
  "",
  "Review every event and line in MelBet before confirming.",
].join("\n"));

function legacyCopy(value) {
  const area = document.createElement("textarea");
  area.value = value;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.focus();
  area.select();
  const copied = document.execCommand("copy");
  area.remove();
  return copied;
}

function writeClipboard(value) {
  let copied = false;
  try { copied = legacyCopy(value); } catch { copied = false; }
  if (!copied && navigator.clipboard?.writeText) navigator.clipboard.writeText(value).catch(() => {});
}

function copyText() {
  writeClipboard(transferText.value);
  copied.value = true;
  window.setTimeout(() => { copied.value = false; }, 2200);
}

function copyEntry(entry) {
  writeClipboard(entry.searchText || entry.selection);
  copiedEntryKey.value = entry.key;
  window.setTimeout(() => { if (copiedEntryKey.value === entry.key) copiedEntryKey.value = null; }, 2500);
}

function openEntry(entry) {
  copyEntry(entry);
  window.open(entry.url, "_blank", "noopener,noreferrer");
}

function prepare() {
  open.value = true;
  copyText();
}

function receiveHelperStatus(event) {
  if (event.source !== window || event.origin !== window.location.origin) return;
  if (event.data?.source !== "NINTH_EXTENSION" || event.data?.type !== "NINTH_MELBET_AUTOFILL_STATUS") return;
  const detail = event.data.detail || {};
  if (detail.requestId && helperRequestId && detail.requestId !== helperRequestId) return;
  window.clearTimeout(helperTimeout);
  helperState.value = detail.state || "ready";
  helperMessage.value = detail.message || "NINTH helper connected.";
  if (helperState.value === "detected") {
    helperTimeout = window.setTimeout(() => {
      if (helperState.value !== "detected") return;
      helperState.value = "error";
      helperMessage.value = "The helper was detected, but its background service did not start. Reload NINTH MelBet Helper in chrome://extensions and try again.";
    }, 8000);
  }
}

function autofill() {
  if (!autofillReady.value) return;
  window.clearTimeout(helperTimeout);
  helperRequestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  helperState.value = "connecting";
  helperMessage.value = "Connecting to the NINTH browser helper...";
  helperTimeout = window.setTimeout(() => {
    if (helperState.value !== "connecting") return;
    helperState.value = "missing";
    helperMessage.value = "NINTH could not detect the helper. Reload the unpacked NINTH MelBet Helper in chrome://extensions, refresh this page, and try again.";
  }, 3000);
  try {
    window.postMessage({
      source: "NINTH_APP",
      type: "NINTH_MELBET_AUTOFILL",
      requestId: helperRequestId,
      payload: {
        version: 2,
        entries: props.entries.map(({ key, game, selection, url, automation }) => ({
          key: String(key || ""),
          game: String(game || ""),
          selection: String(selection || ""),
          url: String(url || ""),
          automation: automation ? {
            kind: String(automation.kind || ""),
            eventId: String(automation.eventId || ""),
            player: String(automation.player || ""),
            prop: String(automation.prop || ""),
            marketLabel: String(automation.marketLabel || ""),
            homeTeam: String(automation.homeTeam || ""),
            awayTeam: String(automation.awayTeam || ""),
            side: String(automation.side || ""),
            line: automation.line == null ? null : Number(automation.line),
          } : null,
        })),
      },
    }, window.location.origin);
  } catch (error) {
    window.clearTimeout(helperTimeout);
    helperState.value = "error";
    helperMessage.value = error?.message || "The helper request could not be sent.";
  }
}

onMounted(() => window.addEventListener("message", receiveHelperStatus));
onBeforeUnmount(() => {
  window.clearTimeout(helperTimeout);
  window.removeEventListener("message", receiveHelperStatus);
});
</script>

<template>
  <button class="melbet-trigger" type="button" :disabled="!entries.length" @click="prepare"><Send /> SEND TO MELBET</button>
  <Teleport to="body">
    <div v-if="open" class="handoff-backdrop" @click.self="open = false">
      <section class="handoff-modal" role="dialog" aria-modal="true" aria-label="MelBet handoff">
        <header>
          <div><span class="eyebrow">NINTH / EXTERNAL HANDOFF</span><h2>Build this card in MelBet.</h2><p>Your {{ entries.length }} legs are copied. Open each event below and select the matching market.</p></div>
          <button class="close" type="button" aria-label="Close MelBet handoff" @click="open = false"><X /></button>
        </header>
        <div class="handoff-status"><span><Check /> {{ linkedCount }} / {{ entries.length }} EVENT LINKS READY</span><button type="button" @click="copyText"><Check v-if="copied" /><Copy v-else /> {{ copied ? 'COPIED' : 'COPY ALL LEGS' }}</button></div>
        <div v-if="autofillEnabled" class="autofill-panel" :class="{ unavailable: !autofillReady }">
          <div><b>{{ playerAutofill ? 'ONE-CLICK PLAYER PROPS' : 'ONE-CLICK MELBET CARD' }}</b><span>{{ autofillUnavailableReason || helperMessage || (playerAutofill ? 'Exact event, player, market, side and line are checked again immediately before every click.' : 'Moneylines are matched by exact event and W1/W2. Totals are matched under Regular time by exact side and line.') }}</span></div>
          <button type="button" :disabled="!autofillReady || ['connecting', 'detected', 'started', 'working'].includes(helperState)" @click="autofill"><WandSparkles /> {{ !autofillReady ? 'AUTOFILL UNAVAILABLE' : ['connecting', 'detected'].includes(helperState) ? 'CONNECTING' : ['started', 'working'].includes(helperState) ? 'AUTOFILL RUNNING' : helperState === 'done' ? 'AUTOFILL AGAIN' : 'AUTOFILL ALL' }}</button>
        </div>
        <div v-else-if="entries.length" class="autofill-panel unavailable"><div><b>MANUAL HANDOFF FOR THIS CARD</b><span>Automatic clicking is currently limited to exact Player Props lines. Moneyline and game-total event links remain available below.</span></div></div>
        <ol>
          <li v-for="(entry, index) in entries" :key="entry.key || `${entry.game}:${entry.selection}`">
            <span class="number">{{ String(index + 1).padStart(2, '0') }}</span>
            <div><small>{{ entry.game }}</small><b>{{ entry.selection }}</b><em v-if="entry.note">{{ entry.note }}</em></div>
            <button v-if="entry.url" class="event-link" type="button" @click="openEntry(entry)">{{ copiedEntryKey === entry.key ? 'NAME COPIED' : entry.searchText ? 'COPY NAME + OPEN' : 'OPEN EVENT' }} <Check v-if="copiedEntryKey === entry.key" /><ExternalLink v-else /></button>
            <span v-else class="unlisted">EVENT NOT LISTED</span>
          </li>
        </ol>
        <footer><b>Final review stays in MelBet.</b><span>NINTH percentages are model probabilities; MelBet numbers are decimal odds and are expected to differ. The copied handoff contains only the player/team, market, side and threshold. NINTH does not transmit credentials, prices, stakes, or submit wagers.</span></footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.melbet-trigger{min-height:40px;padding:12px 16px;border:1px solid #ffffff55;background:#f2f1e9;color:#0e110e;display:flex;align-items:center;justify-content:center;gap:8px;font-size:9px;font-weight:900;letter-spacing:.03em;cursor:pointer}.melbet-trigger:hover:not(:disabled){background:var(--selection-bg);border-color:var(--accent);color:var(--selection-text)}.melbet-trigger:disabled{opacity:.4;cursor:not-allowed}.melbet-trigger svg{width:14px}.handoff-backdrop{position:fixed;inset:0;z-index:130;background:#080a08d9;backdrop-filter:blur(9px);display:grid;place-items:center;padding:24px}.handoff-modal{width:min(820px,100%);max-height:calc(100vh - 48px);overflow:auto;border:1px solid var(--line);background:var(--surface);color:var(--text);box-shadow:0 30px 90px #0009}.handoff-modal>header{padding:24px;display:flex;align-items:flex-start;justify-content:space-between;gap:24px;border-bottom:1px solid var(--line)}h2{font-size:28px;margin:6px 0}p{margin:0;color:var(--muted);font-size:11px;line-height:1.6}.close{width:38px;height:38px;display:grid;place-items:center;flex:0 0 auto;border:1px solid var(--line);background:var(--surface-2);color:var(--text)}.close svg{width:16px}.handoff-status{padding:12px 24px;display:flex;align-items:center;justify-content:space-between;gap:16px;background:var(--selection-bg);color:var(--selection-text)}.handoff-status span,.handoff-status button{display:flex;align-items:center;gap:7px;font-size:9px;font-weight:900}.handoff-status button{padding:9px 12px;border:1px solid currentColor;background:transparent;color:inherit}.handoff-status svg{width:13px}ol{list-style:none;margin:0;padding:0 24px}li{display:grid;grid-template-columns:34px minmax(0,1fr) auto;align-items:center;gap:12px;padding:15px 0;border-bottom:1px solid var(--line)}.number{font:800 10px 'DM Mono';color:var(--accent)}li small,li b,li em{display:block}li small{color:var(--muted);font-size:9px;margin-bottom:4px}li b{font-size:13px}li em{margin-top:4px;color:var(--muted);font-style:normal;font-size:9px}.event-link,.unlisted{display:flex;align-items:center;gap:7px;padding:10px 12px;border:1px solid var(--line);background:transparent;color:var(--text);font-size:8px;font-weight:900;text-decoration:none;white-space:nowrap}.event-link:hover{border-color:var(--accent);background:var(--selection-bg);color:var(--selection-text)}.event-link svg{width:13px}.unlisted{opacity:.5}.handoff-modal>footer{padding:18px 24px;background:var(--surface-2);display:grid;gap:5px}.handoff-modal>footer b{font-size:10px}.handoff-modal>footer span{color:var(--muted);font-size:9px;line-height:1.5}@media(max-width:620px){.handoff-backdrop{padding:8px}.handoff-modal{max-height:calc(100vh - 16px)}.handoff-modal>header,.handoff-status{padding:16px}.handoff-status{align-items:flex-start;flex-direction:column}ol{padding:0 16px}li{grid-template-columns:28px minmax(0,1fr)}.event-link,.unlisted{grid-column:2;justify-self:start}.handoff-modal>footer{padding:16px}}
.autofill-panel{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:16px 24px;border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--accent) 8%,var(--surface))}.autofill-panel>div{display:grid;gap:4px}.autofill-panel b{font-size:10px}.autofill-panel span{max-width:520px;color:var(--muted);font-size:9px;line-height:1.5}.autofill-panel button{display:flex;align-items:center;justify-content:center;gap:8px;min-width:142px;padding:12px 14px;border:1px solid var(--accent);background:var(--selection-bg);color:var(--selection-text);font-size:9px;font-weight:900;white-space:nowrap}.autofill-panel button:disabled{opacity:.55;cursor:wait}.autofill-panel button svg{width:14px}.autofill-panel.unavailable{background:var(--surface-2)}@media(max-width:620px){.autofill-panel{padding:16px;align-items:stretch;flex-direction:column}.autofill-panel button{width:100%}}
</style>
