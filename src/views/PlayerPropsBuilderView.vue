<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Check, Sparkles, Trash2, X } from "lucide-vue-next";
import { api } from "../services/api";
import CustomDatePicker from "../components/ui/CustomDatePicker.vue";
import CustomDateRangePicker from "../components/ui/CustomDateRangePicker.vue";
import CustomSelect from "../components/ui/CustomSelect.vue";
import LoadingState from "../components/ui/LoadingState.vue";
import PlayerHeadshot from "../components/player/PlayerHeadshot.vue";
import TeamLogo from "../components/team/TeamLogo.vue";
import BuilderMarketTabs from "../components/builder/BuilderMarketTabs.vue";
import SlateModeToggle from "../components/builder/SlateModeToggle.vue";
import BuilderRefreshButton from "../components/builder/BuilderRefreshButton.vue";
import CustomMultiSelect from "../components/ui/CustomMultiSelect.vue";
import MelbetHandoff from "../components/builder/MelbetHandoff.vue";

const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const addDays = (value, amount) => { const next = new Date(`${value}T12:00:00Z`); next.setUTCDate(next.getUTCDate() + amount); return next.toISOString().slice(0, 10); };
const saved = (() => {
  try {
    const value = JSON.parse(localStorage.getItem("ninth-props-builder")) || {};
    return Date.now() - Number(value.updatedAt || 0) <= 15 * 60 * 1000 ? value : {};
  } catch {
    return {};
  }
})();
const mode = ref(saved.mode === "multi" ? "multi" : "daily");
const date = ref(saved.date || today);
const dateRange = ref(saved.dateRange || { start: date.value, end: addDays(date.value, 2) });
const targetLegs = ref(String(saved.targetLegs || 5));
const role = ref(saved.role || "all");
const buildSide = ref(["over", "under"].includes(saved.buildSide) ? saved.buildSide : "both");
const picks = ref(saved.picks || {});
const chosenProps = ref({});
const chosenLines = ref({});
const selectedPropTypes = ref(Array.isArray(saved.propTypes) ? saved.propTypes : []);
const propFilterInitialized = ref(false);
const propFilterCustomized = ref(saved.propTypesCustomized === true);
const board = ref(null);
const activeGame = ref(null);
const loading = ref(false);
const error = ref("");
const marketNotice = ref("");
let timer;
let token = 0;

const selectedDays = computed(() => mode.value === "daily" ? 1 : Math.max(1, Math.min(7, Math.round((new Date(`${dateRange.value.end}T12:00:00Z`) - new Date(`${dateRange.value.start}T12:00:00Z`)) / 86400000) + 1)));
const selectedStart = computed(() => mode.value === "daily" ? date.value : dateRange.value.start);
const maxTargetLegs = computed(() => {
  if (!board.value) return Math.max(1, Number(targetLegs.value || 5));
  return Math.max(1, (board.value.games || []).filter(game => (game.players || []).some(player => (player.props || []).some(prop => selectedPropTypes.value.includes(prop.prop)))).length);
});
const legOptions = computed(() => {
  return Array.from({ length: maxTargetLegs.value }, (_, index) => {
    const value = String(index + 1);
    return { value, label: `${value} ${value === "1" ? "leg" : "legs"}`, meta: "One player prop per game" };
  });
});
const keyFor = (game, player, prop) => `${game.game_id}:${player.player_id}:${prop}`;
const playerKey = (game, player) => `${game.game_id}:${player.player_id}`;
const availablePropOptions = computed(() => {
  const values = new Map();
  for (const game of board.value?.games || []) for (const player of game.players || []) for (const prop of player.props || []) values.set(prop.prop, prop.label);
  return [...values].map(([value, label]) => ({ value, label, meta: "Currently displayed by MelBet" })).sort((a, b) => a.label.localeCompare(b.label));
});
const propsFor = player => (player.props || []).filter(prop => selectedPropTypes.value.includes(prop.prop));
const selectedProp = (game, player) => {
  const available = propsFor(player);
  return available.find(prop => prop.prop === chosenProps.value[playerKey(game, player)]) || available.find(prop => prop.prop === player.best_projection?.prop) || available[0];
};
const selectedThreshold = (game, player) => {
  const prop = selectedProp(game, player); if (!prop) return null;
  const wanted = chosenLines.value[keyFor(game, player, prop.prop)] ?? prop.recommended_line;
  return prop.thresholds.find(row => Number(row.line) === Number(wanted)) || prop.thresholds[0];
};
const propOptions = player => propsFor(player).map(prop => ({ value: prop.prop, label: prop.label, meta: `Last 10: ${prop.recent_10_average}` }));
const lineOptions = (game, player) => (selectedProp(game, player)?.thresholds || []).map(row => ({ value: String(row.line), label: `${selectedProp(game, player).label} ${row.line}`, meta: `${pct(row.over_probability)} over` }));
const legs = computed(() => Object.values(picks.value));
const rawJoint = computed(() => legs.value.length ? legs.value.reduce((total, leg) => total * Number(leg.probability), 1) : 0);
const adjustedJoint = computed(() => legs.value.length ? legs.value.reduce((total, leg) => total * (.5 + (Number(leg.probability) - .5) * Math.min(1, .72 + Number(leg.history_games || 0) / 180)), 1) : 0);
const typicalLeg = computed(() => legs.value.length ? Math.pow(rawJoint.value, 1 / legs.value.length) : 0);
const scoreLabel = computed(() => !legs.value.length ? "ADD LEGS TO SCORE" : adjustedJoint.value >= .15 ? "STRONG FOR A MULTI-LEG SLIP" : adjustedJoint.value >= .07 ? "MODERATE COMBINATION" : "HIGH COMBINATION RISK");
const selectedLegs = computed(() => legs.value.map(leg => {
  const game = (board.value?.games || []).find(row => String(row.game_id) === String(leg.game_id));
  const player = game?.players?.find(row => String(row.player_id) === String(leg.player_id));
  const prop = player?.props?.find(row => row.prop === leg.prop);
  return { ...leg, propKey: leg.prop, game, player, prop };
}));
const melbetEventUrl = id => id ? `https://mel-bet.et/en/line/baseball/166775-usa-mlb/${id}-ninth-selection` : null;
const melbetEntries = computed(() => selectedLegs.value.map(leg => {
  const bookmakerId = leg.game?.player_line_market?.player_subgame_id;
  return {
    key: `${leg.game_id}:${leg.player_id}:${leg.propKey}`,
    game: leg.matchup,
    selection: `${leg.player_name} — ${leg.label} — ${leg.side.toUpperCase()} ${leg.line}`,
    searchText: leg.player_name,
    url: melbetEventUrl(bookmakerId),
    note: bookmakerId ? `MelBet Players' stats event ${bookmakerId}` : "MelBet has not listed this player event in the current feed.",
    automation: bookmakerId ? {
      kind: "player_prop",
      eventId: String(bookmakerId),
      player: leg.player_name,
      prop: leg.propKey,
      marketLabel: leg.label,
      side: leg.side,
      line: Number(leg.line),
    } : null,
  };
}));
const pct = value => `${(Number(value || 0) * 100).toFixed(1)}%`;
const dateLabel = value => new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" }).format(new Date(`${value}T12:00:00Z`));
const timeLabel = value => new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York", timeZoneName: "short" }).format(new Date(value));
const visiblePlayers = game => (game?.players || []).filter(player => propsFor(player).length && (role.value === "all" || player.kind === role.value)).sort((a, b) => Number(b.best_projection?.recommended_probability || 0) - Number(a.best_projection?.recommended_probability || 0));
const playersWithSelectedProps = game => (game?.players || []).filter(player => propsFor(player).length);
const gamePick = game => legs.value.find(pick => String(pick.game_id) === String(game.game_id));
const selected = (game, player, side) => picks.value[keyFor(game, player, selectedProp(game, player)?.prop)]?.side === side;
const openGame = game => { activeGame.value = game; role.value = "all"; };
const closeGame = () => { activeGame.value = null; };
function chooseProp(game, player, value) { chosenProps.value = { ...chosenProps.value, [playerKey(game, player)]: value }; }
function chooseLine(game, player, value) { const prop = selectedProp(game, player); chosenLines.value = { ...chosenLines.value, [keyFor(game, player, prop.prop)]: Number(value) }; }
function select(game, player, side) {
  const prop = selectedProp(game, player), threshold = selectedThreshold(game, player); if (!prop || !threshold) return;
  const key = keyFor(game, player, prop.prop), current = picks.value[key];
  const next = Object.fromEntries(Object.entries(picks.value).filter(([, pick]) => String(pick.game_id) !== String(game.game_id)));
  if (current?.side === side) { picks.value = next; return; }
  if (Object.keys(next).length >= Number(targetLegs.value)) return;
  next[key] = { game_id: game.game_id, player_id: player.player_id, player_name: player.name, team_id: player.team_id, prop: prop.prop, label: prop.label, line: threshold.line, side, probability: Number(threshold[`${side}_probability`]), history_games: player.history_games, matchup: `${game.away.name} at ${game.home.name}` };
  picks.value = next;
  closeGame();
}
function removeLeg(leg) { picks.value = Object.fromEntries(Object.entries(picks.value).filter(([, pick]) => !(String(pick.game_id) === String(leg.game_id) && String(pick.player_id) === String(leg.player_id) && pick.prop === leg.propKey))); }
function updatePropTypes(values) { propFilterCustomized.value = true; selectedPropTypes.value = values; }
function editLeg(leg) {
  if (!leg.game || !leg.player) return;
  chosenProps.value = { ...chosenProps.value, [playerKey(leg.game, leg.player)]: leg.propKey };
  chosenLines.value = { ...chosenLines.value, [keyFor(leg.game, leg.player, leg.propKey)]: Number(leg.line) };
  openGame(leg.game);
}
function recommend() {
  const candidates = (board.value?.games || []).map(game => (game.players || []).flatMap(player => propsFor(player).map(prop => {
    const line = prop.thresholds.find(row => Number(row.line) === Number(prop.recommended_line)) || prop.thresholds[0];
    const side = buildSide.value === "both"
      ? (Number(line.over_probability) >= Number(line.under_probability) ? "over" : "under")
      : buildSide.value;
    return { game, player, prop, line, side, probability: Number(line[`${side}_probability`]) };
  })).sort((a, b) => b.probability - a.probability)[0]).filter(Boolean).sort((a, b) => b.probability - a.probability).slice(0, Number(targetLegs.value));
  picks.value = Object.fromEntries(candidates.map(({ game, player, prop, line, side, probability }) => [keyFor(game, player, prop.prop), { game_id: game.game_id, player_id: player.player_id, player_name: player.name, team_id: player.team_id, prop: prop.prop, label: prop.label, line: line.line, side, probability, history_games: player.history_games, matchup: `${game.away.name} at ${game.home.name}` }]));
}
function reconcilePicks(games) {
  const reconciled = {};
  const previousCount = Object.keys(picks.value).length;
  for (const pick of Object.values(picks.value)) {
    const game = (games || []).find(row => String(row.game_id) === String(pick.game_id));
    const player = game?.players?.find(row => String(row.player_id) === String(pick.player_id));
    const prop = player?.props?.find(row => row.prop === pick.prop);
    const threshold = prop?.thresholds?.find(row => Number(row.line) === Number(pick.line));
    if (!game || !player || !prop || !threshold || !["over", "under"].includes(pick.side)) continue;
    reconciled[keyFor(game, player, prop.prop)] = {
      ...pick,
      player_name: player.name,
      team_id: player.team_id,
      label: prop.label,
      line: Number(threshold.line),
      probability: Number(threshold[`${pick.side}_probability`]),
      history_games: player.history_games,
      matchup: `${game.away.name} at ${game.home.name}`,
    };
  }
  picks.value = reconciled;
  const removed = previousCount - Object.keys(reconciled).length;
  marketNotice.value = removed ? `${removed} saved ${removed === 1 ? "leg was" : "legs were"} removed because MelBet changed or relabeled the listed market.` : "";
}
async function load(refresh = false) {
  const current = ++token; loading.value = true; error.value = "";
  try { const result = await api.playerProps(selectedStart.value, selectedDays.value, refresh === true); if (current === token) { board.value = result; reconcilePicks(result.games); } }
  catch (caught) { if (current === token) error.value = caught?.message || "Player props could not be loaded."; }
  finally { if (current === token) { loading.value = false; window.clearTimeout(timer); timer = window.setTimeout(load, Math.max(10, Number(board.value?.refresh_seconds || 60)) * 1000); } }
}
const onKeydown = event => { if (event.key === "Escape") closeGame(); };
watch([mode, date, () => dateRange.value.start, () => dateRange.value.end], load);
watch(availablePropOptions, options => {
  if (!options.length) return;
  const available = new Set(options.map(option => option.value));
  if (!propFilterInitialized.value || !propFilterCustomized.value) { selectedPropTypes.value = [...available]; propFilterInitialized.value = true; }
  else {
    const retained = selectedPropTypes.value.filter(value => available.has(value));
    if (retained.length) selectedPropTypes.value = retained;
    else {
      selectedPropTypes.value = [...available];
      propFilterCustomized.value = false;
      marketNotice.value = "Your saved prop filter did not match today's MelBet markets, so all available props were restored.";
    }
  }
}, { immediate: true });
watch(selectedPropTypes, values => {
  const allowed = new Set(values);
  picks.value = Object.fromEntries(Object.entries(picks.value).filter(([, pick]) => allowed.has(pick.prop)));
}, { deep: true });
watch([mode, date, dateRange, targetLegs, role, buildSide, picks, selectedPropTypes], () => localStorage.setItem("ninth-props-builder", JSON.stringify({ mode: mode.value, date: date.value, dateRange: dateRange.value, targetLegs: targetLegs.value, role: role.value, buildSide: buildSide.value, picks: picks.value, propTypes: selectedPropTypes.value, propTypesCustomized: propFilterCustomized.value, updatedAt: Date.now() })), { deep: true });
watch(targetLegs, () => { if (legs.value.length > Number(targetLegs.value)) picks.value = Object.fromEntries(Object.entries(picks.value).slice(0, Number(targetLegs.value))); });
watch(maxTargetLegs, count => { if (Number(targetLegs.value) > count) targetLegs.value = String(count); });
onMounted(() => { load(); window.addEventListener("keydown", onKeydown); });
onBeforeUnmount(() => { window.clearTimeout(timer); window.removeEventListener("keydown", onKeydown); });
</script>

<template>
  <div class="props-page">
    <section class="props-hero">
      <div class="hero-copy"><span class="eyebrow">NINTH / PLAYER LAB</span><h1>Build from the player up.</h1><p>Start with a matchup, inspect its available player markets, then add only the legs you want to the card.</p></div>
      <div class="hero-tools"><BuilderMarketTabs active="props" /><div class="slate-toolbar"><SlateModeToggle v-model="mode" /><CustomDatePicker v-if="mode === 'daily'" v-model="date" label="Game date" /><CustomDateRangePicker v-else v-model="dateRange" label="Game range" :max-days="7" /><CustomSelect v-model="targetLegs" label="Target legs" :options="legOptions" /><BuilderRefreshButton :loading="loading" @refresh="load(true)" /></div><div class="prop-filter-row"><CustomMultiSelect :model-value="selectedPropTypes" class="prop-market-filter" label="Included player props" placeholder="No prop markets selected" :options="availablePropOptions" @update:model-value="updatePropTypes" /><div class="build-side-control"><span>BUILD DIRECTION</span><div role="group" aria-label="Automatic player prop build direction"><button v-for="side in ['both','over','under']" :key="side" type="button" :class="{ active: buildSide === side }" :aria-pressed="buildSide === side" @click="buildSide = side">{{ side.toUpperCase() }}</button></div></div></div></div>
    </section>

    <section class="scoreboard">
      <div class="score-ring" :style="{ '--score': `${adjustedJoint * 100}%` }"><span><strong class="mono">{{ (adjustedJoint * 100).toFixed(1) }}</strong><small>%</small></span></div>
      <div class="score-copy"><span class="eyebrow">SAMPLE-SIZE ADJUSTED SLIP CONFIDENCE</span><h2>{{ scoreLabel }}</h2><p>Estimated chance that every selected prop lands. Short player histories are pulled toward 50%, and recommended cards use one prop per game to limit hidden same-game correlation.</p><small>MODEL PROBABILITY, NOT A GUARANTEE</small></div>
      <div class="score-metrics"><span><small>LEGS</small><b>{{ legs.length }} / {{ targetLegs }}</b></span><span><small>ADJUSTED</small><b>{{ pct(adjustedJoint) }}</b></span><span><small>RAW PRODUCT</small><b>{{ pct(rawJoint) }}</b></span><span><small>TYPICAL LEG</small><b>{{ pct(typicalLeg) }}</b></span></div>
      <div class="score-actions"><button class="recommend" :disabled="maxTargetLegs < Number(targetLegs)" @click="recommend"><Sparkles /> BUILD BEST {{ targetLegs }}{{ buildSide === 'both' ? '' : ` ${buildSide.toUpperCase()}` }}</button><MelbetHandoff :entries="melbetEntries" autofill-mode="player_prop" /><button class="clear" :disabled="!legs.length" @click="picks = {}"><Trash2 /> CLEAR</button></div>
    </section>
    <div v-if="marketNotice" class="market-notice">{{ marketNotice }}</div>

    <section v-if="selectedLegs.length" class="selected-section">
      <header><div><span class="eyebrow">YOUR PLAYER PROP CARD</span><h2>{{ selectedLegs.length }} selected {{ selectedLegs.length === 1 ? 'leg' : 'legs' }}</h2></div><small>Tap a card to edit its market or line.</small></header>
      <div class="selected-grid">
        <article v-for="leg in selectedLegs" :key="`${leg.game_id}:${leg.player_id}:${leg.propKey}`" class="selected-card" @click="editLeg(leg)">
          <button class="remove" aria-label="Remove leg" @click.stop="removeLeg(leg)"><X /></button>
          <div class="player"><PlayerHeadshot :player="{ id: leg.player_id, name: leg.player_name }" :size="76" /><span><small>{{ leg.player?.kind?.toUpperCase() || 'PLAYER' }} · {{ leg.player?.lineup_status?.toUpperCase() || 'PROJECTED' }}</small><b>{{ leg.player_name }}</b><em>{{ leg.matchup }}</em></span></div>
          <div class="selected-line"><span><small>{{ leg.side.toUpperCase() }} {{ leg.line }}</small><b>{{ leg.label }}</b></span><span class="model-chance"><small>NINTH MODEL CHANCE</small><strong>{{ pct(leg.probability) }}</strong></span></div>
          <footer>LAST 10 AVG <b>{{ leg.prop?.recent_10_average ?? '—' }}</b><span>{{ leg.prop?.confidence_label || 'Model' }} confidence · {{ leg.prop?.confidence_score ?? '—' }}/100</span></footer>
        </article>
      </div>
    </section>

    <LoadingState v-if="loading && !board" label="Building player distributions" detail="Loading official lineups, probable starters and calibrated prop thresholds." />
    <div v-else-if="error" class="error">{{ error }} <button @click="load">RETRY</button></div>
    <template v-else-if="board">
      <div class="board-note"><span><i></i>{{ board.games.length }} GAMES · {{ dateLabel(selectedStart).toUpperCase() }} · {{ board.player_prop_line_feed?.listed_games || 0 }} WITH CURRENT PLAYER MARKETS · AUTO {{ board.refresh_seconds }}S</span><p>Only players, prop types and thresholds currently displayed by MelBet are selectable. Prices are discarded before the model scores the lines.</p></div>
      <section v-if="board.games.length" class="game-grid">
        <button v-for="game in board.games" :key="game.game_id" class="game-card" :class="{ picked: gamePick(game), unavailable: !playersWithSelectedProps(game).length }" :disabled="!playersWithSelectedProps(game).length" @click="openGame(game)">
          <span class="game-time">{{ timeLabel(game.datetime) }}</span>
          <div class="team"><TeamLogo :team="game.away" :size="58" /><span><b>{{ game.away.name }}</b><small>AWAY</small></span></div>
          <div class="versus">AT</div>
          <div class="team home"><span><b>{{ game.home.name }}</b><small>HOME</small></span><TeamLogo :team="game.home" :size="58" /></div>
          <div v-if="gamePick(game)" class="game-selection"><Check /><span><b>{{ gamePick(game).player_name }}</b><small>{{ gamePick(game).side.toUpperCase() }} {{ gamePick(game).line }} {{ gamePick(game).label }}</small></span></div>
          <span class="open-props">{{ gamePick(game) ? 'EDIT PLAYER PROP' : playersWithSelectedProps(game).length ? `VIEW ${playersWithSelectedProps(game).length} MATCHING PLAYERS →` : 'NO MATCHING PLAYER PROPS' }}</span>
        </button>
      </section>
      <div v-else class="empty">No upcoming MLB games were found in this range.</div>
    </template>

    <Teleport to="body">
      <div v-if="activeGame" class="modal-backdrop" @click.self="closeGame">
        <section class="props-modal" role="dialog" aria-modal="true" :aria-label="`${activeGame.away.name} at ${activeGame.home.name} player props`">
          <header class="modal-header"><div class="modal-matchup"><TeamLogo :team="activeGame.away" :size="48" /><span><small>{{ timeLabel(activeGame.datetime) }}</small><b>{{ activeGame.away.name }} <em>at</em> {{ activeGame.home.name }}</b></span><TeamLogo :team="activeGame.home" :size="48" /></div><button aria-label="Close player props" @click="closeGame"><X /></button></header>
          <div class="modal-toolbar"><div><span class="eyebrow">AVAILABLE PLAYER PROPS</span><p>Select a player, market and line. One leg is allowed from each game.</p></div><div class="seg"><button v-for="value in ['all','batter','pitcher']" :key="value" :class="{ active: role === value }" @click="role = value">{{ value.toUpperCase() }}</button></div></div>
          <div class="modal-scroll"><div v-if="visiblePlayers(activeGame).length" class="player-grid">
            <article v-for="player in visiblePlayers(activeGame)" :key="player.player_id" class="player-card" :class="{ picked: gamePick(activeGame)?.player_id === player.player_id }">
              <div class="player"><PlayerHeadshot :player="{ id: player.player_id, name: player.name }" :size="72" /><span><small>{{ player.kind.toUpperCase() }} · {{ player.lineup_status.toUpperCase() }}</small><b>{{ player.name }}</b><em>{{ player.role }} · {{ player.history_games }} tracked games</em></span></div>
              <div class="selectors"><CustomSelect :model-value="selectedProp(activeGame, player)?.prop" label="Prop" :options="propOptions(player)" @update:model-value="chooseProp(activeGame, player, $event)" /><CustomSelect :model-value="String(selectedThreshold(activeGame, player)?.line)" label="Line" :options="lineOptions(activeGame, player)" @update:model-value="chooseLine(activeGame, player, $event)" /></div>
              <div v-if="selectedThreshold(activeGame, player)" class="sides"><button v-for="side in ['over','under']" :key="side" :disabled="legs.length >= Number(targetLegs) && !gamePick(activeGame)" :class="{ active: selected(activeGame, player, side) }" @click="select(activeGame, player, side)"><span><small>{{ side.toUpperCase() }} {{ selectedThreshold(activeGame, player).line }}</small><b>{{ selectedProp(activeGame, player).label }}</b></span><span class="model-chance"><small>NINTH MODEL</small><strong>{{ pct(selectedThreshold(activeGame, player)[`${side}_probability`]) }}</strong></span><Check /></button></div>
              <footer>LAST 10 AVG <b>{{ selectedProp(activeGame, player)?.recent_10_average }}</b><span>{{ selectedProp(activeGame, player)?.confidence_label }} confidence · {{ selectedProp(activeGame, player)?.confidence_score }}/100</span></footer>
            </article>
          </div><div v-else class="empty">No {{ role === 'all' ? '' : role }} props are available for this matchup.</div></div>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.props-page{display:grid;gap:14px;padding-top:20px}.props-hero{padding:30px 34px;border:1px solid var(--line);background:radial-gradient(circle at 82% 10%,color-mix(in srgb,var(--accent) 28%,transparent),transparent 30%),var(--surface);display:grid;grid-template-columns:minmax(330px,1fr) auto;gap:22px 28px;align-items:end}.hero-copy{max-width:720px}.props-hero h1{font-size:clamp(42px,5vw,72px);letter-spacing:-.065em;line-height:.9;margin:10px 0 16px}.props-hero p,.score-copy p,.board-note p{color:var(--muted);line-height:1.6}.market-control{justify-self:end}.market-control>span{display:block;margin-bottom:7px;font:600 7px 'DM Mono';letter-spacing:.12em;color:var(--muted)}.market-control>div{display:flex;padding:4px;border:1px solid var(--line);background:var(--surface-2)}.market-control a{padding:11px 13px;color:var(--muted);font-size:10px;font-weight:900;text-decoration:none}.market-control a.active{background:var(--selection-bg);color:var(--selection-text)}.controls{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:10px}.seg{display:flex;padding:4px;border:1px solid var(--line);background:var(--surface-2)}.seg button,.refresh{padding:11px 14px;border:0;background:transparent;color:var(--muted);font-weight:900;font-size:11px}.seg button.active{background:var(--selection-bg);color:var(--selection-text)}.refresh{border:1px solid var(--line);display:flex;align-items:center;gap:8px}.refresh svg{width:15px}.scoreboard{display:grid;grid-template-columns:auto minmax(260px,1fr) auto auto;gap:22px;align-items:center;padding:22px 25px;background:var(--ink);color:var(--paper)}.score-ring{--score:0%;width:112px;height:112px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--accent) var(--score),#343931 0);position:relative}.score-ring:after{content:'';position:absolute;inset:9px;border-radius:50%;background:var(--ink)}.score-ring span{position:relative;z-index:1}.score-ring strong{font-size:27px}.score-ring small{color:var(--accent)}.score-copy h2{font-size:18px;margin:6px 0}.score-copy p{max-width:520px;font-size:9px;margin:0}.score-copy>small{display:block;margin-top:8px;font:500 7px 'DM Mono';color:#ffffff75}.score-metrics{display:grid;grid-template-columns:repeat(2,minmax(90px,1fr));gap:13px}.score-metrics span{border-left:1px solid #ffffff25;padding-left:12px}.score-metrics small,.score-metrics b{display:block}.score-metrics small{font-size:8px;color:#ffffff75}.score-metrics b{font-size:16px}.score-actions{display:grid;gap:8px}.score-actions button{padding:12px 16px;display:flex;gap:8px;align-items:center;justify-content:center;border:1px solid #ffffff35;color:white;font-weight:900;font-size:10px}.score-actions svg{width:15px}.recommend{background:var(--accent);color:var(--ink)!important;border-color:var(--accent)!important}.clear{background:transparent}.selected-section{border:1px solid var(--line);background:var(--surface);padding:20px}.selected-section>header{display:flex;justify-content:space-between;align-items:end;margin-bottom:14px}.selected-section h2{font-size:22px;margin:5px 0 0}.selected-section>header>small{color:var(--muted)}.selected-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.selected-card{position:relative;border:1px solid var(--accent);box-shadow:inset 3px 0 var(--accent);padding:14px;background:var(--surface-2);display:grid;gap:12px;cursor:pointer}.remove{position:absolute;right:8px;top:8px;z-index:2;width:30px;height:30px;display:grid;place-items:center;border:1px solid var(--line);background:var(--surface);color:var(--muted)}.remove svg{width:14px}.selected-line{display:flex;align-items:center;justify-content:space-between;padding:12px;border:1px solid var(--line);background:var(--selection-bg);color:var(--selection-text)}.selected-line small,.selected-line b{display:block}.selected-line small{font-size:9px}.selected-line strong{font-size:20px}.board-note{padding:15px 18px;border:1px solid var(--line);background:var(--surface)}.board-note span{font-size:11px;font-weight:900}.board-note i{display:inline-block;width:7px;height:7px;background:var(--accent);border-radius:50%;margin-right:8px}.board-note p{font-size:11px;margin:5px 0 0}.game-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.game-card{display:grid;grid-template-columns:1fr auto 1fr;gap:10px;align-items:center;position:relative;padding:20px;border:1px solid var(--line);background:var(--surface);color:var(--text);text-align:left;cursor:pointer;transition:transform .15s,border-color .15s}.game-card:hover{transform:translateY(-2px);border-color:var(--text)}.game-card.picked{border-color:var(--accent);box-shadow:inset 0 3px var(--accent)}.game-time{grid-column:1/-1;color:var(--muted);font:600 8px 'DM Mono';text-align:center}.team{display:flex;gap:9px;align-items:center;min-width:0}.team.home{justify-content:flex-end;text-align:right}.team span,.team b,.team small{display:block;min-width:0}.team b{font-size:13px}.team small{margin-top:4px;font-size:8px;color:var(--muted)}.versus{font:800 9px 'DM Mono';color:var(--muted)}.game-selection{grid-column:1/-1;display:flex;gap:9px;align-items:center;padding:10px;background:var(--selection-bg);color:var(--selection-text)}.game-selection svg{width:16px}.game-selection b,.game-selection small{display:block}.game-selection small{font-size:9px;margin-top:3px}.open-props{grid-column:1/-1;margin-top:5px;font:800 9px 'DM Mono';color:var(--muted);text-align:right}.modal-backdrop{position:fixed;inset:0;z-index:100;background:#080a08c9;backdrop-filter:blur(8px);display:grid;place-items:center;padding:24px}.props-modal{width:min(1180px,100%);max-height:min(880px,calc(100vh - 48px));display:grid;grid-template-rows:auto auto minmax(0,1fr);background:var(--surface);border:1px solid var(--line);box-shadow:0 28px 80px #0008}.modal-header{padding:16px 20px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between}.modal-header>button{width:38px;height:38px;display:grid;place-items:center;border:1px solid var(--line);background:var(--surface-2);color:var(--text)}.modal-header>button svg{width:17px}.modal-matchup{display:flex;align-items:center;gap:12px}.modal-matchup span{text-align:center}.modal-matchup small,.modal-matchup b{display:block}.modal-matchup small{font-size:8px;color:var(--muted);margin-bottom:3px}.modal-matchup b{font-size:16px}.modal-matchup em{font-style:normal;color:var(--muted);margin:0 5px}.modal-toolbar{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:16px}.modal-toolbar p{margin:4px 0 0;color:var(--muted);font-size:10px}.modal-scroll{overflow:auto}.player-grid{padding:12px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.player-card{border:1px solid var(--line);padding:14px;background:var(--surface-2);display:grid;gap:12px}.player-card.picked{border-color:var(--accent);box-shadow:inset 3px 0 var(--accent)}.player{display:flex;gap:12px;align-items:center}.player span{min-width:0}.player small,.player b,.player em{display:block}.player small{font-size:9px;color:var(--accent);font-weight:900}.player b{font-size:17px;margin:3px 0}.player em{font-style:normal;color:var(--muted);font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.selectors,.sides{display:grid;grid-template-columns:1fr 1fr;gap:8px}.sides button{display:flex;justify-content:space-between;align-items:center;text-align:left;padding:12px;border:1px solid var(--line);background:var(--surface);color:var(--text)}.sides button small,.sides button b{display:block}.sides button small{font-size:9px;color:var(--muted)}.sides button strong{font-size:17px}.sides button svg{display:none;width:15px}.sides button.active{background:var(--selection-bg);color:var(--selection-text);border-color:var(--accent)}.sides button.active svg{display:block}.player-card footer,.selected-card footer{font-size:9px;color:var(--muted);font-weight:800}.player-card footer b,.selected-card footer b{color:var(--text);margin-left:5px}.player-card footer span,.selected-card footer span{float:right}.error,.empty{padding:40px;text-align:center;border:1px solid var(--line);background:var(--surface)}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.hero-tools{width:min(720px,52vw);display:grid;justify-items:end;gap:14px}.hero-tools :deep(.market-tabs){width:430px}.slate-toolbar{width:100%;display:flex;align-items:end;justify-content:flex-end;gap:8px}.slate-toolbar :deep(.custom-select){width:145px}.slate-toolbar :deep(.date-picker){width:190px}.slate-toolbar :deep(.range-picker){width:280px}.mode-control{width:190px}.mode-control>span{display:block;margin-bottom:6px;font:500 7px 'DM Mono';letter-spacing:.1em;color:var(--muted)}.mode-control>div{height:44px;display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--line);background:var(--surface);padding:3px}.mode-control button{border:0;background:transparent;font:700 7px 'DM Mono';letter-spacing:.04em;color:var(--muted)}.mode-control button.active{background:var(--selection-bg);color:var(--selection-text)}.game-card.unavailable{opacity:.58;cursor:not-allowed}.game-card.unavailable:hover{transform:none;border-color:var(--line)}
@media(max-width:1120px){.props-hero{grid-template-columns:1fr}.hero-tools{width:100%;justify-items:start}.scoreboard{grid-template-columns:auto 1fr}.score-metrics,.score-actions{grid-column:2}.game-grid,.selected-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:760px){.props-hero{padding:24px}.hero-tools :deep(.market-tabs),.mode-control{width:100%}.slate-toolbar{flex-wrap:wrap;justify-content:stretch}.slate-toolbar :deep(.date-picker),.slate-toolbar :deep(.range-picker){flex:1;width:100%}.scoreboard{grid-template-columns:1fr;padding:20px}.score-ring{margin:auto}.score-metrics,.score-actions{grid-column:auto}.game-grid,.selected-grid,.player-grid{grid-template-columns:1fr}.selected-section>header,.modal-toolbar{align-items:flex-start;flex-direction:column}.modal-backdrop{padding:8px}.props-modal{max-height:calc(100vh - 16px)}.modal-header{padding:12px}.modal-matchup b{font-size:12px}.selectors,.sides{grid-template-columns:1fr}.player-card footer span,.selected-card footer span{float:none;display:block;margin-top:5px}}
.props-hero{grid-template-columns:minmax(300px,1fr) minmax(0,720px)}.hero-tools{width:100%;min-width:0;max-width:100%}.hero-tools :deep(.market-tabs){width:min(430px,100%)}.slate-toolbar{min-width:0;flex-wrap:wrap}
@media(min-width:761px){.slate-toolbar{display:grid;grid-template-columns:190px minmax(170px,1fr) 210px 110px}}
@media(max-width:1120px){.props-hero{grid-template-columns:1fr}}
.model-chance{text-align:right}.model-chance small{display:block;font-size:7px!important;letter-spacing:.04em;opacity:.7;margin-bottom:2px}.model-chance strong{display:block}
.market-notice{padding:12px 16px;border:1px solid #d99b32;background:color-mix(in srgb,#d99b32 13%,var(--surface));color:var(--text);font-size:10px;font-weight:800}
.prop-filter-row{width:100%;display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:8px;align-items:end}.build-side-control>span{display:block;margin-bottom:6px;font:500 7px 'DM Mono';letter-spacing:.1em;color:var(--muted)}.build-side-control>div{height:44px;display:grid;grid-template-columns:repeat(3,1fr);padding:3px;border:1px solid var(--line);background:var(--surface)}.build-side-control button{border:0;background:transparent;color:var(--muted);font:700 8px 'DM Mono';letter-spacing:.04em}.build-side-control button.active{background:var(--selection-bg);color:var(--selection-text)}
.scoreboard{background:var(--contrast);color:var(--on-contrast)}
.score-ring:after{background:var(--contrast)}
.score-copy p{color:#aeb3aa}
.score-copy>small{color:#d5d8d1}
.score-actions button{color:var(--on-contrast)}
.recommend{color:var(--selection-text)!important}
@media(max-width:760px){.prop-filter-row{grid-template-columns:1fr}}
</style>
