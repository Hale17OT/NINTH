<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api } from "../services/api";
import TeamLogo from "../components/team/TeamLogo.vue";
import CustomDatePicker from "../components/ui/CustomDatePicker.vue";
import CustomSelect from "../components/ui/CustomSelect.vue";
import CustomDateRangePicker from "../components/ui/CustomDateRangePicker.vue";
import LoadingState from "../components/ui/LoadingState.vue";
import BuilderMarketTabs from "../components/builder/BuilderMarketTabs.vue";
import SlateModeToggle from "../components/builder/SlateModeToggle.vue";
import BuilderRefreshButton from "../components/builder/BuilderRefreshButton.vue";
import MelbetHandoff from "../components/builder/MelbetHandoff.vue";
import OddsFloorSelect from "../components/builder/OddsFloorSelect.vue";
import { Check, Sparkles, Trash2 } from "lucide-vue-next";
import { selectMixedCandidates, selectTotalsCandidates } from "../services/slipBuilderRecommendations";

const today = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
}).format(new Date());
const readJson = (key, fallback) => {
  try {
    return JSON.parse(localStorage.getItem(key)) || fallback;
  } catch {
    return fallback;
  }
};
const BUILDER_TTL = 15 * 60 * 1000;
const LAST_VISIT_KEY = "ninth-builder-last-visited";
const builderKeys = ["ninth-slip-builder", "ninth-builder-settings", "ninth-builder-target"];
const hasSavedBuilderState = builderKeys.some((key) => localStorage.getItem(key) !== null);
const storedLastVisit = Number(localStorage.getItem(LAST_VISIT_KEY)) || (hasSavedBuilderState ? Date.now() : 0);
if (storedLastVisit && Date.now() - storedLastVisit > BUILDER_TTL) {
  builderKeys.forEach((key) => localStorage.removeItem(key));
  localStorage.removeItem(LAST_VISIT_KEY);
}
const markVisited = () => localStorage.setItem(LAST_VISIT_KEY, String(Date.now()));
markVisited();
const savedSettings = readJson("ninth-builder-settings", {});
const route = useRoute();
const requestedMarket = ["moneyline", "totals", "combined"].includes(String(route.query.market)) ? String(route.query.market) : null;
const date = ref(savedSettings.date || today);
const addDays = (value, amount) => {
  const next = new Date(`${value}T12:00:00Z`);
  next.setUTCDate(next.getUTCDate() + amount);
  return next.toISOString().slice(0, 10);
};
const dateRange = ref(savedSettings.dateRange?.start && savedSettings.dateRange?.end ? savedSettings.dateRange : { start: date.value, end: addDays(date.value, 2) });
const board = ref(null);
const mode = ref(savedSettings.mode === "multi" ? "multi" : "daily");
const marketMode = ref(requestedMarket || (["moneyline", "totals", "combined"].includes(savedSettings.marketMode) ? savedSettings.marketMode : "moneyline"));
const targetLegs = ref(savedSettings.targetLegs || localStorage.getItem("ninth-builder-target") || "5");
const minimumOdds = ref(savedSettings.minimumOdds === "all" || Number(savedSettings.minimumOdds) >= 1 ? String(savedSettings.minimumOdds) : "1.50");
const loading = ref(false);
const error = ref("");
const recommendationNotice = ref("");
const picks = ref(readJson("ninth-slip-builder", {}));
const totalLineChoices = ref({});
const normalizedPick = (value) => (typeof value === "string" ? { market: "moneyline", side: value } : value);
const totalThreshold = (game, line) => game.totals_projection?.thresholds?.find((row) => Number(row.line) === Number(line));
const totalLineForGame = (game) => (normalizedPick(picks.value[String(game.game_id)])?.market === "totals" ? normalizedPick(picks.value[String(game.game_id)]).line : (totalLineChoices.value[String(game.game_id)] ?? game.totals_projection?.recommended_line ?? game.totals_projection?.thresholds?.[0]?.line));
const totalProbability = (game, side, line = totalLineForGame(game)) => Number(totalThreshold(game, line)?.[`${side}_probability`] || 0);
const moneylineOdds = (game, side) => Number(game.moneyline_odds?.[side]) || null;
const totalOdds = (game, side, line = totalLineForGame(game)) => Number(totalThreshold(game, line)?.melbet_odds?.[side]) || null;
const selectionOdds = (game, market, side, line = null) => market === "totals" ? totalOdds(game, side, line ?? totalLineForGame(game)) : moneylineOdds(game, side);
const oddsEligible = odds => minimumOdds.value === "all" || (Number.isFinite(Number(odds)) && Number(odds) >= Number(minimumOdds.value));
const formatOdds = odds => Number.isFinite(Number(odds)) ? Number(odds).toFixed(3).replace(/0+$/, "").replace(/\.$/, "") : "—";
const totalPushProbability = (game, line = totalLineForGame(game)) => Number(totalThreshold(game, line)?.push_probability || 0);
const totalLineOptions = (game) =>
  (game.totals_projection?.thresholds || []).map((row) => ({
    value: String(row.line),
    label: `Total ${row.line}`,
    meta: `Over @ ${formatOdds(row.melbet_odds?.over)} · Under @ ${formatOdds(row.melbet_odds?.under)}${Number(row.push_probability) > 0 ? " · push possible" : ""}`,
  }));
const maxTargetLegs = computed(() => Math.max(1, Number(board.value?.games?.length || targetLegs.value || 5)));
const legOptions = computed(() => {
  const first = maxTargetLegs.value === 1 ? 1 : 2;
  return Array.from({ length: maxTargetLegs.value - first + 1 }, (_, index) => {
    const value = String(index + first);
    return { value, label: `${value} ${value === "1" ? "leg" : "legs"}` };
  });
});
const selectedDays = computed(() => (mode.value === "daily" ? 1 : Math.max(1, Math.min(14, Math.round((new Date(`${dateRange.value.end}T12:00:00Z`) - new Date(`${dateRange.value.start}T12:00:00Z`)) / 86400000) + 1))));
const selectedStart = computed(() => (mode.value === "daily" ? date.value : dateRange.value.start));
const legs = computed(() =>
  (board.value?.games || []).flatMap((game) => {
    const pick = normalizedPick(picks.value[String(game.game_id)]);
    if (!pick) return [];
    const probability = pick.market === "totals" ? totalProbability(game, pick.side, pick.line) : Number(game[`${pick.side}_win_probability`] || 0);
    const inputCompleteness = pick.market === "totals" ? Number(game.totals_projection?.input_completeness || 0) : Number(game.input_completeness || 0);
    return [
      {
        ...game,
        ...pick,
        team: pick.market === "moneyline" ? game[pick.side] : null,
        probability,
        decimalOdds: selectionOdds(game, pick.market, pick.side, pick.line),
        inputCompleteness,
      },
    ];
  }),
);
const melbetEventUrl = (id) => id ? `https://mel-bet.et/en/line/baseball/166775-usa-mlb/${id}-ninth-selection` : null;
const melbetMoneylineUrl = "https://mel-bet.et/en/line/baseball";
const melbetEntries = computed(() => legs.value.map((leg) => {
  const bookmakerId = leg.totals_projection?.line_market?.bookmaker_game_id;
  const game = `${leg.away.name} at ${leg.home.name}`;
  const selection = leg.market === "totals"
    ? `Total runs — ${leg.side.toUpperCase()} ${leg.line} @ ${formatOdds(leg.decimalOdds)}`
    : `${leg.team?.name || leg[leg.side]?.name} moneyline (${leg.side === "home" ? "W1" : "W2"}) @ ${formatOdds(leg.decimalOdds)}`;
  return {
    key: `${leg.game_id}:${leg.market}`,
    game,
    selection,
    searchText: leg.market === "moneyline" ? (leg.team?.name || game) : game,
    url: bookmakerId ? (leg.market === "moneyline" ? melbetMoneylineUrl : melbetEventUrl(bookmakerId)) : null,
    note: bookmakerId
      ? (leg.market === "moneyline" ? `MelBet baseball board · event ${bookmakerId}` : `MelBet Regular time event ${bookmakerId}`)
      : "MelBet has not listed this event in the current feed.",
    automation: bookmakerId ? {
      kind: leg.market,
      eventId: String(bookmakerId),
      homeTeam: leg.home.name,
      awayTeam: leg.away.name,
      side: leg.side,
      line: leg.market === "totals" ? Number(leg.line) : null,
    } : null,
  };
}));
const jointProbability = computed(() => (legs.value.length ? legs.value.reduce((total, leg) => total * leg.probability, 1) : 0));
const inputAdjustedJoint = computed(() =>
  legs.value.length
    ? legs.value.reduce((total, leg) => {
        const reliability = 0.75 + 0.25 * leg.inputCompleteness;
        return total * (0.5 + (leg.probability - 0.5) * reliability);
      }, 1)
    : 0,
);
const calibrationMarket = computed(() => (marketMode.value === "combined" ? "mixed" : marketMode.value));
const totalsCalibrationCompatible = computed(() => board.value?.market_slip_calibration?.compatible_with_deployed_totals === true);
const candidateCalibration = computed(() => {
  if (marketMode.value === "moneyline") return null;
  if (!totalsCalibrationCompatible.value) return null;
  const market = board.value?.market_slip_calibration?.markets?.[calibrationMarket.value];
  return mode.value === "daily" ? market?.daily?.[String(targetLegs.value)] : market?.multiday?.[String(selectedDays.value)]?.[String(targetLegs.value)];
});
const activeCalibration = computed(() => {
  if (marketMode.value === "moneyline") return mode.value === "daily" ? board.value?.slip_calibration : board.value?.multiday_validation_grid?.[String(selectedDays.value)]?.[String(targetLegs.value)];
  return candidateCalibration.value?.status === "insufficient" ? null : candidateCalibration.value;
});
const followsRecommendation = (leg) => {
  if (marketMode.value === "moneyline") return leg.market === "moneyline" && leg.side === leg.recommended_side;
  if (marketMode.value === "totals") return leg.market === "totals" && leg.side === leg.totals_projection?.recommended_side && Number(leg.line) === Number(leg.totals_projection?.recommended_line);
  const expected = optionForGame(leg);
  return expected && leg.market === expected.market && leg.side === expected.side && (leg.market !== "totals" || Number(leg.line) === Number(expected.line));
};
const calibrationApplies = computed(() => activeCalibration.value?.promoted === true && legs.value.length === Number(targetLegs.value) && legs.value.length >= 2 && legs.value.length <= 8 && legs.value.every(followsRecommendation));
const calibratedProbability = computed(() => {
  const calibration = activeCalibration.value;
  if (!legs.value.length) return 0;
  if (!calibration || !calibrationApplies.value) return inputAdjustedJoint.value;
  const raw = Math.min(0.999999, Math.max(0.000001, inputAdjustedJoint.value));
  const logit = Math.log(raw / (1 - raw));
  return 1 / (1 + Math.exp(-(calibration.intercept + calibration.logit_slope * logit)));
});
const confidenceBand = computed(() => {
  if (!calibrationApplies.value) return null;
  if (marketMode.value !== "moneyline")
    return {
      observed_all_correct: activeCalibration.value.validation_observed_all_correct,
      wilson_low: activeCalibration.value.validation_wilson_low,
      wilson_high: activeCalibration.value.validation_wilson_high,
    };
  if (mode.value === "multi")
    return {
      observed_all_correct: activeCalibration.value.validation_observed_all_correct,
      wilson_low: activeCalibration.value.validation_wilson_low,
      wilson_high: activeCalibration.value.validation_wilson_high,
    };
  return activeCalibration.value?.bins?.find((bin) => inputAdjustedJoint.value >= bin.raw_min && inputAdjustedJoint.value < (bin.raw_max === 1 ? 1.0001 : bin.raw_max));
});
const averageStrength = computed(() => (legs.value.length ? Math.pow(jointProbability.value, 1 / legs.value.length) : 0));
const scoreLabel = computed(() => (calibratedProbability.value >= 0.15 ? "STRONG FOR A MULTI-LEG SLIP" : calibratedProbability.value >= 0.07 ? "MODERATE COMBINATION" : legs.value.length ? "HIGH COMBINATION RISK" : "ADD LEGS TO SCORE"));
const confidenceMethod = computed(() => (calibrationApplies.value ? "JOINT BACKTEST-ADJUSTED" : legs.value ? "MULTIPLICATIVE MODEL" : "MODEL"));
const marketOptionsForGame = (game) => {
  const moneylineOddsValue = moneylineOdds(game, game.recommended_side);
  const moneyline = oddsEligible(moneylineOddsValue) ? {
    market: "moneyline",
    side: game.recommended_side,
    probability: Number(game.recommended_probability || 0),
    odds: moneylineOddsValue,
  } : null;
  const total = game.totals_projection?.available
      && game.totals_projection?.selection_available !== false
      && (game.totals_projection?.automatic_builder_eligible === true
        || (game.totals_projection?.automatic_builder_eligible == null
          && game.totals_projection?.automatic_selection_available === true))
      && oddsEligible(totalOdds(game, game.totals_projection.recommended_side, game.totals_projection.recommended_line))
    ? {
        market: "totals",
        side: game.totals_projection.recommended_side,
        line: game.totals_projection.recommended_line,
        probability: Number(game.totals_projection.recommended_probability || 0),
        odds: totalOdds(game, game.totals_projection.recommended_side, game.totals_projection.recommended_line),
      }
    : null;
  return { moneyline, total };
};
const optionForGame = (game) => {
  const { moneyline, total } = marketOptionsForGame(game);
  if (marketMode.value === "moneyline") return moneyline;
  if (marketMode.value === "totals") return total;
  if (!moneyline) return total;
  return !total || moneyline.probability >= total.probability ? moneyline : total;
};
const canRecommend = computed(() => (board.value?.games || []).filter(game => optionForGame(game)).length >= Number(targetLegs.value));
const eligibleRecommendationCount = computed(() => (board.value?.games || []).filter(game => optionForGame(game)).length);
const gameDay = (value) =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
const groupedGames = computed(() => {
  if (!board.value) return [];
  if (mode.value === "daily") return [[date.value, board.value.games]];
  const groups = new Map();
  for (const game of board.value.games) {
    const key = gameDay(game.starts_at);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(game);
  }
  return groups.size ? [...groups] : [[dateRange.value.start, []]];
});
const dateLabel = (value) =>
  new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
const timeLabel = (value) =>
  new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
    timeZoneName: "short",
  }).format(new Date(value));
const snapshotLabel = (value) =>
  value
    ? new Intl.DateTimeFormat("en-US", {
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
      }).format(new Date(value))
    : "pending";
const pct = (value) => `${(Number(value || 0) * 100).toFixed(1)}%`;
let loadToken = 0;
let refreshTimer;
let mounted = false;
function queueRefresh() {
  if (!mounted) return;
  window.clearTimeout(refreshTimer);
  refreshTimer = window.setTimeout(
    () => {
      markVisited();
      load();
    },
    Math.max(3, Number(board.value?.refresh_seconds || 60)) * 1000,
  );
}
function trimToTarget() {
  const limit = Number(targetLegs.value);
  if (legs.value.length <= limit) return;
  const keep = [...legs.value].sort((a, b) => b.probability - a.probability).slice(0, limit);
  picks.value = Object.fromEntries(keep.map((leg) => [String(leg.game_id), { market: leg.market, side: leg.side, line: leg.line }]));
}
function pickEligible(game, pick) {
  if (!game) return false;
  if (!pick || !["moneyline", "totals"].includes(pick.market)) return false;
  if (pick.market === "totals" && (!game.totals_projection?.selection_available || !totalThreshold(game, pick.line))) return false;
  return oddsEligible(selectionOdds(game, pick.market, pick.side, pick.line));
}
async function load() {
  const token = ++loadToken;
  loading.value = true;
  error.value = "";
  try {
    const result = await api.projectionBoard(selectedStart.value, selectedDays.value);
    if (token !== loadToken) return;
    board.value = result;
    const available = new Map(board.value.games.map((game) => [String(game.game_id), game]));
    picks.value = Object.fromEntries(Object.entries(picks.value).filter(([id, rawPick]) => {
      const game = available.get(id), pick = normalizedPick(rawPick);
      if (!game) return false;
      return pickEligible(game, pick);
    }));
    trimToTarget();
  } catch (caught) {
    if (token === loadToken) error.value = caught?.message || "The projection board could not be loaded.";
  } finally {
    if (token === loadToken) {
      loading.value = false;
      queueRefresh();
    }
  }
}
function isSelected(game, market, side) {
  const pick = normalizedPick(picks.value[String(game.game_id)]);
  return pick?.market === market
    && pick?.side === side
    && (market !== "totals" || Number(pick.line) === Number(totalLineForGame(game)));
}
function setTotalLine(game, value) {
  const id = String(game.game_id),
    line = Number(value);
  totalLineChoices.value = { ...totalLineChoices.value, [id]: line };
  const pick = normalizedPick(picks.value[id]);
  if (pick?.market === "totals") picks.value = { ...picks.value, [id]: { ...pick, line } };
}
function select(game, market, side) {
  recommendationNotice.value = "";
  const id = String(game.game_id);
  if (isSelected(game, market, side)) {
    const next = { ...picks.value };
    delete next[id];
    picks.value = next;
  } else if (picks.value[id] || legs.value.length < Number(targetLegs.value)) {
    const line = market === "totals" ? Number(totalLineForGame(game)) : null;
    if (!oddsEligible(selectionOdds(game, market, side, line))) return;
    picks.value = { ...picks.value, [id]: { market, side, line } };
  }
}
function recommend() {
  recommendationNotice.value = "";
  const ranked = (board.value?.games || [])
    .flatMap((game) => {
      if (marketMode.value !== "combined") {
        const option = optionForGame(game);
        return option ? [{ game, option }] : [];
      }
      return Object.values(marketOptionsForGame(game)).filter(Boolean).map(option => ({ game, option }));
    })
    .sort((a, b) => b.option.probability - a.option.probability);
  const chosen = marketMode.value === "combined"
    ? selectMixedCandidates(ranked, Number(targetLegs.value))
    : marketMode.value === "totals"
      ? selectTotalsCandidates(ranked, Number(targetLegs.value))
      : ranked.slice(0, Number(targetLegs.value));
  if (!chosen.length) {
    picks.value = {};
    recommendationNotice.value = minimumOdds.value === "all"
      ? `No ${marketMode.value === "totals" ? "model-consistent totals" : "eligible selections"} currently pass the automatic-selection policy.`
      : `No ${marketMode.value === "totals" ? "model-consistent totals" : "eligible selections"} currently satisfy the selected odds floor and automatic-selection policy.`;
    return;
  }
  picks.value = Object.fromEntries(chosen.map(({ game, option }) => [String(game.game_id), { market: option.market, side: option.side, line: option.line }]));
  totalLineChoices.value = {
    ...totalLineChoices.value,
    ...Object.fromEntries(
      chosen
        .filter(({ option }) => option.market === "totals")
        .map(({ game, option }) => [String(game.game_id), Number(option.line)]),
    ),
  };
  if (chosen.length < Number(targetLegs.value)) {
    recommendationNotice.value = minimumOdds.value === "all"
      ? `Built ${chosen.length} of ${targetLegs.value} requested legs. Only ${chosen.length} ${marketMode.value === "totals" ? "model-consistent totals" : "eligible games"} currently pass the automatic-selection policy.`
      : `Built ${chosen.length} of ${targetLegs.value} requested legs. Only ${chosen.length} ${marketMode.value === "totals" ? "model-consistent totals" : "eligible games"} currently satisfy the selected odds floor and automatic-selection policy.`;
  }
}
function clearSlip() {
  picks.value = {};
}
watch(
  picks,
  (value) => {
    localStorage.setItem("ninth-slip-builder", JSON.stringify(value));
    markVisited();
  },
  { deep: true },
);
watch([date, mode, () => dateRange.value.start, () => dateRange.value.end], load);
watch(minimumOdds, () => {
  if (!board.value) return;
  const games = new Map(board.value.games.map(game => [String(game.game_id), game]));
  picks.value = Object.fromEntries(Object.entries(picks.value).filter(([id, rawPick]) => pickEligible(games.get(id), normalizedPick(rawPick))));
});
watch(marketMode, () => {
  picks.value = {};
  markVisited();
});
watch(() => route.query.market, value => {
  const next = String(value || "");
  if (["moneyline", "totals", "combined"].includes(next) && marketMode.value !== next) marketMode.value = next;
});
watch(targetLegs, (value) => {
  localStorage.setItem("ninth-builder-target", value);
  markVisited();
  trimToTarget();
});
watch(() => board.value?.games?.length, count => {
  if (count && Number(targetLegs.value) > count) targetLegs.value = String(count);
});
watch([date, mode, marketMode, targetLegs, minimumOdds, () => dateRange.value.start, () => dateRange.value.end], () => {
  localStorage.setItem(
    "ninth-builder-settings",
    JSON.stringify({
      date: date.value,
      mode: mode.value,
      marketMode: marketMode.value,
      targetLegs: targetLegs.value,
      minimumOdds: minimumOdds.value,
      dateRange: { ...dateRange.value },
    }),
  );
  markVisited();
});
onMounted(() => {
  mounted = true;
  markVisited();
  load();
});
onBeforeUnmount(() => {
  mounted = false;
  markVisited();
  window.clearTimeout(refreshTimer);
});
</script>

<template>
  <div class="builder-page">
    <section class="builder-hero">
      <div>
        <span class="eyebrow">NINTH / SLIP LAB</span>
        <h1>
          Build
          {{ mode === "daily" ? "today's" : "a multi-day" }} card.<br /><em>See the real risk.</em>
        </h1>
        <p>Build moneyline, total-runs, or mixed cards from market-free probabilities. Mixed mode chooses the stronger model per matchup while enforcing one selection per game.</p>
      </div>
      <div class="hero-tools">
        <BuilderMarketTabs :active="marketMode" />
        <div class="slate-toolbar"><SlateModeToggle v-model="mode" /><CustomDatePicker v-if="mode === 'daily'" v-model="date" label="Game date" /><CustomDateRangePicker v-else v-model="dateRange" label="Game range" :max-days="14" /><CustomSelect v-model="targetLegs" label="Target legs" :options="legOptions" /><OddsFloorSelect v-model="minimumOdds" /><BuilderRefreshButton :loading="loading" @refresh="load" /></div>
      </div>
    </section>
    <section class="scoreboard">
      <div class="score-ring" :style="{ '--score': `${Math.min(100, calibratedProbability * 100)}%` }">
        <span
          ><strong class="mono">{{ (calibratedProbability * 100).toFixed(1) }}</strong
          ><small>%</small></span
        >
      </div>
      <div class="score-copy">
        <span class="eyebrow">{{ confidenceMethod }} SLIP CONFIDENCE</span>
        <h2>{{ scoreLabel }}</h2>
        <p>
          Estimated chance that <b>all {{ legs.length || 0 }} legs</b> win. Leg probabilities are multiplied—never added—and each uses its own moneyline or total-runs model plus official-input coverage<template v-if="calibrationApplies"
            >, then the joint result is logit-calibrated against historical
            {{ mode === "daily" ? "same-day" : `${selectedDays}-day` }}
            {{ calibrationMarket }} cards</template
          >.
        </p>
        <small v-if="confidenceBand">Comparable historical cards finished together {{ pct(confidenceBand.observed_all_correct) }} of the time · 95% range {{ pct(confidenceBand.wilson_low) }}–{{ pct(confidenceBand.wilson_high) }}</small
        ><small v-else-if="marketMode !== 'moneyline' && legs.length && !totalsCalibrationCompatible">The previous card calibrator was built from an older totals model, so it is disabled. This score is the current models' multiplicative estimate.</small><small v-else-if="marketMode !== 'moneyline' && legs.length && activeCalibration?.promoted === false">This exact {{ calibrationMarket }} × {{ mode === "daily" ? "daily" : `${selectedDays}-day` }} × {{ targetLegs }}-leg cell did not improve temporal-audit Brier, so the displayed score remains the multiplicative model estimate.</small><small v-else-if="legs.length > 8">Backtest adjustment is currently supported only for 2–8 legs. Extended cards remain multiplicative model estimates.</small><small v-else-if="mode === 'multi' && activeCalibration?.promoted === false">The cross-day calibrator did not improve unseen-season Brier score, so it is deliberately not applied.</small><small v-else-if="legs.length">Historical calibration applies only when every selection follows the model's recommended market and side.</small>
      </div>
      <div class="score-metrics">
        <span
          ><small>LEGS / TARGET</small><b class="mono">{{ legs.length }} / {{ targetLegs }}</b></span
        ><span
          ><small>{{ calibrationApplies ? "JOINT CALIBRATED" : "MODEL PRODUCT" }}</small
          ><b class="mono">{{ pct(calibratedProbability) }}</b></span
        ><span
          ><small>RAW PRODUCT</small><b class="mono">{{ pct(jointProbability) }}</b></span
        ><span
          ><small>TYPICAL LEG</small><b class="mono">{{ pct(averageStrength) }}</b></span
        >
      </div>
      <div class="score-actions">
        <button class="recommend" type="button" :disabled="loading || !board || !eligibleRecommendationCount" @click="recommend"><Sparkles /> BUILD BEST {{ targetLegs }}</button><MelbetHandoff :entries="melbetEntries" autofill-mode="card" /><button class="clear" type="button" :disabled="!legs.length" @click="clearSlip"><Trash2 /> CLEAR</button>
      </div>
    </section>
    <small v-if="recommendationNotice" class="recommendation-notice" role="status">{{ recommendationNotice }}</small>
    <section v-if="activeCalibration" class="calibration-audit" :class="{ rejected: activeCalibration.promoted === false }">
      <template v-if="mode === 'daily'"
        ><div>
          <span class="eyebrow">CALIBRATION AUDIT</span><b>{{ activeCalibration.training_samples.toLocaleString() }} historical same-day cards</b><small>{{ activeCalibration.training_days }} walk-forward windows · 2–8 legs</small>
        </div>
        <div>
          <span>UNSEEN 2025–26 BRIER</span><b class="mono">{{ activeCalibration.validation_brier_calibrated.toFixed(5) }}</b
          ><small>Raw multiplication {{ activeCalibration.validation_brier_raw.toFixed(5) }}</small>
        </div>
        <div>
          <span>HISTORICAL BEST-5</span><b class="mono">{{ pct(activeCalibration.top_five.observed_all_correct) }}</b
          ><small>{{ activeCalibration.top_five.samples }} cards · raw predicted {{ pct(activeCalibration.top_five.mean_raw) }}</small>
        </div>
        <p>Calibration was learned only from out-of-fold model picks. It measures model uncertainty; it does not guarantee a result or assume sportsbook odds.</p></template
      ><template v-else
        ><div>
          <span class="eyebrow">{{ activeCalibration.promoted ? "EXACT CELL PROMOTED" : "EXACT CELL NOT PROMOTED" }}</span
          ><b>{{ selectedDays }}-day × {{ targetLegs }}-leg validation</b><small>{{ activeCalibration.training_samples }} older cards · {{ activeCalibration.validation_samples }} unseen cards</small>
        </div>
        <div>
          <span>UNSEEN 2025–26 BRIER</span><b class="mono">{{ activeCalibration.validation_brier_calibrated?.toFixed(5) ?? "—" }}</b
          ><small>Raw multiplication {{ activeCalibration.validation_brier_raw?.toFixed(5) ?? "—" }} · change {{ activeCalibration.validation_improvement > 0 ? "+" : "" }}{{ activeCalibration.validation_improvement?.toFixed(5) ?? "—" }}</small>
        </div>
        <div>
          <span>UNSEEN ALL-CORRECT RATE</span><b class="mono">{{ pct(activeCalibration.validation_observed_all_correct) }}</b
          ><small>95% range {{ pct(activeCalibration.validation_wilson_low) }}–{{ pct(activeCalibration.validation_wilson_high) }} · {{ activeCalibration.validation_wins }} sweeps</small>
        </div>
        <p>
          {{ activeCalibration.promoted ? "This exact range-and-leg cell passed the aggregate and separate-year stability gates." : "This exact range-and-leg cell failed the promotion gate. Its calibration is audit-only and the displayed score remains input-adjusted." }}
          <template v-if="activeCalibration.per_year"
            >2025 change {{ activeCalibration.per_year["2025"]?.improvement > 0 ? "+" : "" }}{{ activeCalibration.per_year["2025"]?.improvement?.toFixed(5) }}
            · 2026 change
            {{ activeCalibration.per_year["2026"]?.improvement > 0 ? "+" : "" }}{{ activeCalibration.per_year["2026"]?.improvement?.toFixed(5) }}.</template
          >
        </p></template
      >
    </section>
    <LoadingState v-if="loading && !board" label="Building the projection board" detail="Loading the slate and synchronizing every available matchup projection." />
    <div v-else-if="error" class="state error">{{ error }} <button @click="load">RETRY</button></div>
    <template v-else-if="board">
      <div v-if="board.enrichment_pending" class="board-note enriching">
          <span><i></i>BOARD READY · ENRICHING {{ board.enrichment_pending }} MATCHUPS</span>
          <p v-if="board.projection_pending">{{ board.games.length }} of {{ board.scheduled_games }} projections are ready. Remaining games are calculating in the background and will appear automatically.</p>
          <p v-else>Baseline projections are usable now. Confirmed lineups, starters, bullpen workload and weather are merging automatically without blocking the board.</p>
      </div>
      <div class="board-note">
        <span
          ><i></i>{{ board.games.length }} UPCOMING GAMES ·
          {{ mode === "daily" ? dateLabel(date).toUpperCase() : `${dateLabel(dateRange.start).toUpperCase()} – ${dateLabel(dateRange.end).toUpperCase()}` }}
          · AUTO {{ board.refresh_seconds || 15 }}S</span
        >
        <p v-if="canRecommend">“Best {{ targetLegs }}” selects exactly {{ targetLegs }} highest-probability games that satisfy {{ minimumOdds === 'all' ? 'the All odds setting' : `minimum MelBet decimal odds of ${minimumOdds}` }}.<template v-if="marketMode === 'combined'"> Mixed cards retain at least one eligible moneyline and one eligible total.</template> Moneyline has no probability cutoff; totals use the held-out production calibration. Odds only control eligibility and never enter either model.</p>
        <p v-else>Only {{ eligibleRecommendationCount }} of {{ targetLegs }} requested games satisfy {{ minimumOdds === 'all' ? 'the automatic-selection policy' : 'the current odds floor and automatic-selection policy' }}. Build Best will select those {{ eligibleRecommendationCount }} instead of doing nothing. Totals remain manual-only when no calibrated or distribution-consistent listed line is available.</p>
      </div>
      <section v-for="group in groupedGames" :key="group[0]" class="day-group">
        <header>
          <span class="eyebrow">SLATE DAY</span>
          <h2>{{ dateLabel(group[0]) }}</h2>
          <small>{{ group[1].length }} GAMES</small>
        </header>
        <div class="game-grid">
          <article v-for="game in group[1]" :key="game.game_id" class="game-pick" :class="{ selected: picks[String(game.game_id)] }">
            <div class="game-meta">
              <span>{{ timeLabel(game.starts_at) }}</span
              ><RouterLink
                :to="{
                  path: `/games/${game.game_id}`,
                  query: { from: 'builder' },
                }"
                >OPEN MATCHUP</RouterLink
              >
            </div>
            <div v-if="marketMode === 'totals'" class="matchup-identity">
              <span
                ><TeamLogo :team="game.away" :size="34" /><b>{{ game.away.name }}</b
                ><small>AWAY</small></span
              ><i>AT</i
              ><span class="home"
                ><TeamLogo :team="game.home" :size="34" /><b>{{ game.home.name }}</b
                ><small>HOME</small></span
              >
            </div>
            <template v-if="marketMode !== 'totals'"
              ><div class="market-label">MONEYLINE</div>
              <button type="button" :disabled="!oddsEligible(moneylineOdds(game, 'away')) || (legs.length >= Number(targetLegs) && !picks[String(game.game_id)])" :class="{ active: isSelected(game, 'moneyline', 'away'), unavailable: !oddsEligible(moneylineOdds(game, 'away')) }" @click="select(game, 'moneyline', 'away')">
                <TeamLogo :team="game.away" :size="42" /><span
                  ><small>AWAY MONEYLINE</small><b>{{ game.away.name }}</b></span
                ><strong class="mono">{{ pct(game.away_win_probability) }}<small>MELBET @ {{ formatOdds(moneylineOdds(game, 'away')) }}</small></strong
                ><Check />
              </button>
              <div class="versus">VS</div>
              <button type="button" :disabled="!oddsEligible(moneylineOdds(game, 'home')) || (legs.length >= Number(targetLegs) && !picks[String(game.game_id)])" :class="{ active: isSelected(game, 'moneyline', 'home'), unavailable: !oddsEligible(moneylineOdds(game, 'home')) }" @click="select(game, 'moneyline', 'home')">
                <TeamLogo :team="game.home" :size="42" /><span
                  ><small>HOME MONEYLINE</small><b>{{ game.home.name }}</b></span
                ><strong class="mono">{{ pct(game.home_win_probability) }}<small>MELBET @ {{ formatOdds(moneylineOdds(game, 'home')) }}</small></strong
                ><Check /></button
            ></template>
            <template v-if="marketMode !== 'moneyline'"
              ><div class="market-label total">
                TOTAL RUNS · BEST LISTED LINE
                {{ game.totals_projection?.recommended_line ?? "—" }}
                <span v-if="game.totals_projection?.selection_available">{{ game.totals_projection.line_market.lines.length }} CURRENT LINES · PROJECTED {{ game.totals_projection.expected_total_runs }}</span>
              </div>
              <div v-if="game.totals_projection?.available && game.totals_projection?.selection_available" class="total-market-picker">
                <CustomSelect :model-value="String(totalLineForGame(game))" label="Currently listed full-game total" :options="totalLineOptions(game)" @update:model-value="setTotalLine(game, $event)" />
                <small v-if="totalPushProbability(game)" class="push-note">{{ pct(totalPushProbability(game)) }} model push probability at this integer line</small>
              </div>
              <div v-if="game.totals_projection?.available && game.totals_projection?.selection_available" class="total-options">
                <button v-for="side in ['over', 'under']" :key="side" type="button" :disabled="!oddsEligible(totalOdds(game, side)) || (legs.length >= Number(targetLegs) && !picks[String(game.game_id)])" :class="{ active: isSelected(game, 'totals', side), unavailable: !oddsEligible(totalOdds(game, side)) }" @click="select(game, 'totals', side)">
                  <span
                    ><small>{{ side.toUpperCase() }} {{ totalLineForGame(game) }}</small
                    ><b>{{ side === "over" ? "Higher scoring" : "Lower scoring" }}</b></span
                  ><strong class="mono">{{ pct(totalProbability(game, side)) }}<small>MELBET @ {{ formatOdds(totalOdds(game, side)) }}</small></strong
                  ><Check />
                </button>
              </div>
              <p v-else class="total-unavailable">No current full-game total is listed for this matchup. MelBet generally publishes only the next 24 hours.</p></template
            >
            <footer>
              <span
                >BEST ELIGIBLE <b>{{ optionForGame(game)?.market === "totals" ? `${optionForGame(game).side.toUpperCase()} ${optionForGame(game).line}` : optionForGame(game) ? game[game.recommended_side].name : 'NONE' }}<template v-if="optionForGame(game)"> · @ {{ formatOdds(optionForGame(game).odds) }}</template></b></span
              ><span>{{ game.projection_basis === "matchup_synced" ? "MATCHUP-SYNCED" : "EARLY BASELINE" }} · {{ snapshotLabel(game.projection_updated_at) }} · ONE PICK PER GAME</span>
            </footer>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.builder-page {
  display: grid;
  gap: 14px;
  padding-top: 20px;
}
.builder-hero {
  min-height: 290px;
  padding: 36px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 28px;
  border: 1px solid var(--line);
  background: radial-gradient(circle at 80% 15%, color-mix(in srgb, var(--accent) 36%, transparent), transparent 31%), var(--surface);
}
h1 {
  font-size: clamp(45px, 6vw, 82px);
  line-height: 0.86;
  letter-spacing: -0.075em;
  margin: 14px 0 20px;
}
h1 em {
  font-style: normal;
  color: var(--acid);
}
.builder-hero p {
  max-width: 630px;
  margin: 0;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.65;
}
.hero-tools {
  display: grid;
  justify-items: end;
  gap: 14px;
  flex: none;
  width: min(840px, 58vw);
  min-width: 0;
  max-width: 100%;
}
.hero-tools :deep(.market-tabs) {
  width: 430px;
}
.slate-toolbar {
  width: 100%;
  display: grid;
  grid-template-columns: 150px minmax(170px, 1fr) 125px 155px 110px;
  align-items: end;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}
.slate-toolbar > * {
  min-width: 0;
}
.slate-toolbar :deep(.custom-select),
.slate-toolbar :deep(.date-picker),
.slate-toolbar :deep(.range-picker),
.slate-toolbar :deep(.refresh-control),
.slate-toolbar :deep(.refresh-control button) {
  width: 100%;
  min-width: 0;
}
.slate-toolbar > button {
  height: 42px;
  padding: 0 16px;
  border: 0;
  background: var(--ink);
  color: var(--paper);
  display: flex;
  align-items: center;
  gap: 8px;
  font: 700 8px "DM Mono";
  cursor: pointer;
}
.slate-toolbar svg {
  width: 14px;
}
.spin {
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.mode-control {
  width: 190px;
}
.market-control {
  width: 360px;
}
.mode-control > span,
.market-control > span {
  display: block;
  margin-bottom: 6px;
  font: 500 7px "DM Mono";
  letter-spacing: 0.1em;
  color: var(--muted);
}
.mode-control > div,
.market-control > div {
  height: 44px;
  display: grid;
  border: 1px solid var(--line);
  background: var(--surface);
  padding: 3px;
}
.mode-control > div {
  grid-template-columns: 1fr 1fr;
}
.market-control > div {
  grid-template-columns: repeat(4, 1fr);
}
.mode-control button,
.market-control button,
.props-mode-link {
  border: 0;
  background: transparent;
  font: 700 7px "DM Mono";
  letter-spacing: 0.04em;
  cursor: pointer;
  color: var(--muted);
  display: grid;
  place-items: center;
  text-align: center;
  text-decoration: none;
}
.mode-control button.active,
.market-control button.active {
  background: var(--ink);
  color: var(--accent);
}
.scoreboard {
  display: grid;
  grid-template-columns: auto minmax(260px, 1fr) auto auto;
  gap: 22px;
  align-items: center;
  padding: 22px 25px;
  background: var(--ink);
  color: var(--paper);
}
.score-ring {
  --score: 0%;
  width: 112px;
  height: 112px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: conic-gradient(var(--accent) var(--score), #343931 0);
  position: relative;
}
.score-ring:after {
  content: "";
  position: absolute;
  inset: 8px;
  border-radius: 50%;
  background: var(--ink);
}
.score-ring span {
  position: relative;
  z-index: 1;
}
.score-ring strong {
  font-size: 27px;
}
.score-ring small {
  font-size: 9px;
  color: #9ca297;
}
.score-copy h2 {
  font-size: 18px;
  margin: 7px 0;
}
.score-copy p {
  max-width: 520px;
  font-size: 9px;
  line-height: 1.55;
  color: #aeb3aa;
  margin: 0;
}
.score-copy > small {
  display: block;
  max-width: 560px;
  margin-top: 7px;
  color: #d5d8d1;
  font: 500 7px "DM Mono";
  line-height: 1.5;
}
.score-copy .eyebrow {
  color: var(--accent);
}
.score-metrics {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1px;
  background: #343931;
}
.score-metrics span {
  min-width: 90px;
  padding: 12px;
  background: #20241e;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.score-metrics small {
  font: 500 7px "DM Mono";
  color: #949a90;
}
.score-metrics b {
  font-size: 13px;
}
.score-actions {
  display: grid;
  gap: 7px;
}
.score-actions button {
  height: 42px;
  padding: 0 14px;
  border: 1px solid #4a5046;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  font: 700 8px "DM Mono";
  cursor: pointer;
}
.score-actions svg {
  width: 14px;
}
.recommend {
  background: var(--accent);
  color: var(--ink);
  border-color: var(--accent) !important;
}
.clear {
  background: transparent;
  color: var(--paper);
}
.recommendation-notice {
  display: block;
  margin: 8px 0 0;
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, var(--accent) 40%, #4a5046);
  color: var(--accent);
  font: 600 8px/1.5 "DM Mono";
}
button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.calibration-audit {
  display: grid;
  grid-template-columns: repeat(3, auto) minmax(260px, 1fr);
  align-items: center;
  gap: 1px;
  border: 1px solid var(--line);
  background: var(--line);
}
.calibration-audit > div,
.calibration-audit > p {
  height: 100%;
  padding: 14px 17px;
  background: var(--surface);
  margin: 0;
}
.calibration-audit > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.calibration-audit span {
  font: 500 7px "DM Mono";
  color: var(--muted);
}
.calibration-audit b {
  font-size: 12px;
}
.calibration-audit small {
  font-size: 8px;
  color: var(--muted);
}
.calibration-audit p {
  font-size: 9px;
  line-height: 1.55;
  color: var(--muted);
  display: flex;
  align-items: center;
}
.calibration-audit.rejected {
  border-color: color-mix(in srgb, var(--orange) 55%, var(--line));
}
.calibration-audit.rejected .eyebrow {
  color: var(--orange);
}
.state {
  padding: 45px;
  text-align: center;
  border: 1px solid var(--line);
  background: var(--surface);
  font: 600 9px "DM Mono";
  color: var(--acid);
}
.state.error {
  color: var(--orange);
}
.board-note {
  padding: 14px 17px;
  border: 1px solid var(--line);
  background: var(--surface);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.board-note span {
  font: 600 8px "DM Mono";
  white-space: nowrap;
}
.board-note i {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 7px;
  background: var(--acid);
  border-radius: 50%;
}
.board-note p {
  font-size: 9px;
  color: var(--muted);
  margin: 0;
  max-width: 760px;
  text-align: right;
}
.day-group {
  border: 1px solid var(--line);
  background: var(--surface);
}
.day-group > header {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: end;
  padding: 16px 18px;
  border-bottom: 1px solid var(--line);
}
.day-group > header .eyebrow {
  grid-column: 1;
}
.day-group > header h2 {
  font-size: 18px;
  margin: 5px 0 0;
}
.day-group > header small {
  grid-column: 2;
  grid-row: 1/3;
  font: 600 8px "DM Mono";
  color: var(--muted);
}
.game-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 10px;
}
.game-pick {
  border: 1px solid var(--line);
  background: var(--wash);
  padding: 10px;
}
.game-pick.selected {
  border-color: var(--ink);
}
.game-meta,
.game-pick footer {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font: 600 7px "DM Mono";
  color: var(--muted);
}
.game-meta {
  padding: 2px 4px 9px;
}
.game-meta a {
  text-decoration: none;
  border-bottom: 1px solid;
}
.game-pick > button {
  width: 100%;
  min-height: 69px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto 17px;
  align-items: center;
  gap: 10px;
  text-align: left;
  padding: 8px;
  border: 1px solid transparent;
  background: var(--surface);
  cursor: pointer;
}
.game-pick > button:hover {
  border-color: var(--muted);
}
.game-pick > button.active {
  border-color: var(--ink);
  background: color-mix(in srgb, var(--accent) 28%, var(--surface));
}
.game-pick > button span {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.game-pick > button small {
  font: 500 7px "DM Mono";
  color: var(--muted);
}
.game-pick > button b {
  font-size: 11px;
  margin-top: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.game-pick > button strong {
  font-size: 15px;
}
.game-pick > button strong small,
.total-options button strong small {
  display: block;
  margin-top: 4px;
  font-size: 7px;
  white-space: nowrap;
}
.game-pick > button.unavailable,
.total-options button.unavailable {
  opacity: .45;
  cursor: not-allowed;
}
.game-pick > button svg {
  width: 15px;
  opacity: 0;
}
.game-pick > button.active svg {
  opacity: 1;
}
.versus {
  text-align: center;
  font: 600 7px "DM Mono";
  color: var(--muted);
  height: 18px;
  line-height: 18px;
}
.game-pick footer {
  padding: 10px 4px 1px;
  border-top: 1px solid var(--line);
  margin-top: 9px;
}
.game-pick footer b {
  color: var(--text);
}
.market-label {
  display: flex;
  justify-content: space-between;
  padding: 8px 4px 6px;
  font: 700 7px "DM Mono";
  letter-spacing: 0.08em;
  color: var(--muted);
}
.market-label.total {
  margin-top: 8px;
  border-top: 1px solid var(--line);
  color: var(--acid);
}
.market-label span {
  color: var(--muted);
}
.total-market-picker {
  display: flex;
  align-items: end;
  gap: 9px;
  margin-bottom: 6px;
}
.total-market-picker :deep(.custom-select) {
  min-width: 0;
  width: 190px;
}
.push-note {
  padding-bottom: 8px;
  font: 600 7px/1.4 "DM Mono";
  color: var(--muted);
}
.total-options {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 5px;
}
.total-options button {
  min-height: 62px;
  display: grid;
  grid-template-columns: 1fr auto 17px;
  align-items: center;
  gap: 8px;
  text-align: left;
  padding: 10px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
}
.total-options button span {
  display: flex;
  flex-direction: column;
}
.total-options button small {
  font: 600 7px "DM Mono";
  color: var(--muted);
}
.total-options button b {
  font-size: 10px;
  margin-top: 4px;
}
.total-options button strong {
  font-size: 15px;
}
.total-options button svg {
  width: 14px;
  opacity: 0;
}
.total-options button.active {
  background: var(--selection-bg);
  color: var(--selection-text);
  border-color: color-mix(in srgb, var(--selection-text) 55%, var(--selection-bg));
}
.total-options button.active svg {
  opacity: 1;
}
.total-options button.active small {
  color: var(--selection-muted);
}
.total-unavailable {
  padding: 15px;
  margin: 0;
  background: var(--raised);
  font-size: 8px;
  color: var(--muted);
}
.matchup-identity {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 10px;
  padding: 10px;
  margin-bottom: 4px;
  border: 1px solid var(--line);
  background: var(--surface);
}
.matchup-identity > span {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-rows: auto auto;
  column-gap: 8px;
  align-items: center;
}
.matchup-identity > span :deep(.team-logo) {
  grid-row: 1/3;
}
.matchup-identity b {
  font-size: 10px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.matchup-identity small {
  font: 600 7px "DM Mono";
  color: var(--muted);
}
.matchup-identity > i {
  font: 700 7px "DM Mono";
  font-style: normal;
  color: var(--acid);
}
.matchup-identity > span.home {
  text-align: right;
  grid-template-columns: minmax(0, 1fr) auto;
}
.matchup-identity > span.home :deep(.team-logo) {
  grid-column: 2;
}
.matchup-identity > span.home b,
.matchup-identity > span.home small {
  grid-column: 1;
}
@media (max-width: 1100px) {
  .scoreboard {
    grid-template-columns: auto 1fr;
  }
  .score-metrics,
  .score-actions {
    grid-column: 2;
  }
  .score-actions {
    grid-template-columns: 1fr 1fr;
  }
  .game-grid {
    grid-template-columns: 1fr;
  }
  .calibration-audit {
    grid-template-columns: repeat(3, 1fr);
  }
  .calibration-audit > p {
    grid-column: 1/-1;
  }
}
@media (max-width: 1200px) {
  .builder-hero {
    align-items: flex-start;
    flex-direction: column;
  }
  .hero-tools {
    width: 100%;
  }
}
@media (max-width: 700px) {
  .builder-hero {
    padding: 25px;
    align-items: flex-start;
    flex-direction: column;
  }
  .hero-tools {
    width: 100%;
  }
  .hero-tools :deep(.market-tabs),
  .mode-control {
    width: 100%;
  }
  .slate-toolbar {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .slate-toolbar > :last-child {
    grid-column: 1 / -1;
  }
  .scoreboard {
    grid-template-columns: 1fr;
    text-align: center;
  }
  .score-ring {
    margin: auto;
  }
  .score-metrics,
  .score-actions {
    grid-column: 1;
  }
  .score-copy p {
    margin: auto;
  }
  .board-note {
    align-items: flex-start;
    flex-direction: column;
  }
  .board-note p {
    text-align: left;
  }
  .game-pick footer {
    flex-direction: column;
  }
  .game-pick > button {
    grid-template-columns: auto minmax(0, 1fr) auto 15px;
  }
  .calibration-audit {
    grid-template-columns: 1fr;
  }
  .calibration-audit > p {
    grid-column: 1;
  }
}
@media (max-width: 460px) {
  .slate-toolbar {
    grid-template-columns: 1fr;
  }
  .slate-toolbar > :last-child {
    grid-column: auto;
  }
}
.calibration-audit {
  display: none;
}
.scoreboard {
  background: var(--contrast);
  color: var(--on-contrast);
}
.score-ring:after {
  background: var(--contrast);
}
.clear {
  color: var(--on-contrast);
}
.recommend {
  color: var(--selection-text);
}
.game-pick > button.active {
  background: var(--selection-bg);
  color: var(--selection-text);
  border-color: color-mix(in srgb, var(--selection-text) 55%, var(--selection-bg));
}
.game-pick > button.active small {
  color: var(--selection-muted);
}
.game-pick > button.active b,
.game-pick > button.active strong,
.game-pick > button.active svg {
  color: var(--selection-text);
}
</style>
