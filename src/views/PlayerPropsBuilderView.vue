<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Check, RefreshCw, Sparkles, Trash2, X } from "lucide-vue-next";
import { AnimatePresence, motion, useReducedMotion } from "motion-v";
import { api } from "../services/api";
import { createSharedPoller } from "../services/polling";
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
import OddsFloorSelect from "../components/builder/OddsFloorSelect.vue";
import ProbabilityRing from "../components/charts/ProbabilityRing.vue";
import {
  buildGuaranteeCandidates,
  DEFAULT_GUARANTEE_ROBUST_FLOOR,
  guaranteeOddsFloor,
  rankGuaranteeCandidates,
  selectGuaranteeCandidates,
} from "../services/playerPropGuaranteeRecommendations";
import {
  automaticMarketRule,
  automaticThresholdCandidates,
  applyBuildSelectionCalibration,
  applyWithinGameReranking,
  historyAdjustedProbability,
  nextSameGameAlternate,
  normalizePlayerPropMarkets,
  playerPropBuildSide,
  playerPropExposureKey,
  playerPropPortfolioContextKey,
  playerPropMarketKey,
  playerPropMarketSelected,
  recommendationCutoffFloor,
  rerankWithinGameCandidates,
  robustRecommendationProbability,
  saferSamePropLine,
  selectDiversifiedCandidates,
  strongestPlayerPropMarkets,
  strongestPlayerPropSide,
} from "../services/playerPropRecommendations";

const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const reducedMotion = useReducedMotion();
const shadowTestMode = new URLSearchParams(window.location.search).get("shadow") === "1";
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
const buildStyle = ref(saved.buildStyle === "sweep" ? "sweep" : "balanced");
const portfolioMode = ref(saved.portfolioMode === "best" ? "best" : "independent");
const cardExposureKeys = ref(Array.isArray(saved.cardExposureKeys) ? saved.cardExposureKeys : []);
const cardExposureContextKeys = ref(Array.isArray(saved.cardExposureContextKeys) ? saved.cardExposureContextKeys : []);
const rotationDepth = ref(Math.max(0, Number(saved.rotationDepth || 0)));
const exposureSlate = ref(saved.exposureSlate || "");
const minimumOdds = ref(saved.minimumOdds === "all" || Number(saved.minimumOdds) >= 1 ? String(saved.minimumOdds) : "1.50");
const probabilityCutoffOptions = [
  { value: "ignore", label: "Ignore cutoff" },
  ...[50, 55, 60, 65, 70, 75, 80].map(value => ({
    value: (value / 100).toFixed(2), label: `${value}%`,
  })),
];
const portfolioModeOptions = [
  { value: "independent", label: "Independent cards" },
  { value: "best", label: "Best available" },
];
const propPresetOptions = [
  { value: "included", label: "Included markets" },
  { value: "strongest", label: "Strongest picks" },
  { value: "guarantee", label: "Guarantee" },
];
const propPreset = ref(["strongest", "guarantee"].includes(saved.propPreset) ? saved.propPreset : "included");
if (propPreset.value === "guarantee" && (minimumOdds.value === "all" || Number(minimumOdds.value) < 1.2)) {
  minimumOdds.value = "1.20";
}
const recommendationCutoff = ref(
  saved.recommendationCutoff === "ignore" || probabilityCutoffOptions.some(option => option.value === String(saved.recommendationCutoff))
    ? String(saved.recommendationCutoff)
    : "0.65",
);
const picks = ref(saved.picks || {});
const usedAlternateKeys = ref(Array.isArray(saved.usedAlternateKeys) ? saved.usedAlternateKeys : []);
const bulkAlternateKeys = ref(Array.isArray(saved.bulkAlternateKeys) ? saved.bulkAlternateKeys : []);
const chosenProps = ref({});
const chosenLines = ref({});
const selectedPropTypes = ref(Array.isArray(saved.propTypes) ? saved.propTypes : []);
const propSidePreferences = ref(saved.propSidePreferences && typeof saved.propSidePreferences === "object"
  ? saved.propSidePreferences
  : {});
const propFilterInitialized = ref(false);
const propFilterCustomized = ref(saved.propTypesCustomized === true);
const board = ref(null);
const guaranteePayload = ref(null);
const activeGame = ref(null);
const loading = ref(false);
const error = ref("");
const marketNotice = ref("");
let poller;
let token = 0;
const selectedRecommendationFloor = computed(() => recommendationCutoffFloor(recommendationCutoff.value));
const isSweepMode = computed(() => buildStyle.value === "sweep");
const recommendationCutoffLabel = computed(() => recommendationCutoff.value === "ignore"
  ? "with the probability cutoff ignored"
  : `at or above the selected ${Math.round(selectedRecommendationFloor.value * 100)}% adjusted-probability cutoff`);

const selectedDays = computed(() => mode.value === "daily" ? 1 : Math.max(1, Math.min(7, Math.round((new Date(`${dateRange.value.end}T12:00:00Z`) - new Date(`${dateRange.value.start}T12:00:00Z`)) / 86400000) + 1)));
const selectedStart = computed(() => mode.value === "daily" ? date.value : dateRange.value.start);
const currentExposureSlate = computed(() => `${selectedStart.value}:${selectedDays.value}`);
const guaranteeMarketKeys = computed(() => new Set((guaranteePayload.value?.records || [])
  .filter(record => Number(record.samples || 0) >= 3)
  .map(record => `${record.player_id}:${record.kind}:${record.prop}`)));
const guaranteeExactKey = (playerId, kind, prop, side, line) => `${playerId}:${kind}:${prop}:${side}:${Number(line)}`;
const guaranteeRecordMap = computed(() => new Map((guaranteePayload.value?.records || [])
  .filter(record => Number(record.samples || 0) >= 3)
  .map(record => [
    guaranteeExactKey(record.player_id, record.kind, record.prop, record.side, record.line),
    record,
  ])));
const propIncluded = (player, prop) => propPreset.value === "strongest"
  ? Boolean(strongestPlayerPropSide(player.kind, prop.prop))
  : propPreset.value === "guarantee"
    ? guaranteeMarketKeys.value.has(`${player.player_id}:${player.kind}:${prop.prop}`)
  : playerPropMarketSelected(selectedPropTypes.value, player.kind, prop.prop);
const maxTargetLegs = computed(() => {
  if (!board.value) return Math.max(1, Number(targetLegs.value || 5));
  if (propPreset.value === "guarantee") return Math.max(1, selectGuaranteeCandidates(
    allGuaranteeCandidates.value,
    999,
    {
      sweep: isSweepMode.value,
      priorExposureKeys: new Set(cardExposureKeys.value),
      priorContextExposureKeys: new Set(cardExposureContextKeys.value),
      avoidPriorExposure: portfolioMode.value === "independent",
    },
  ).length);
  return Math.max(1, (board.value.games || []).filter(game => (game.players || []).some(player => (player.props || []).some(prop => propIncluded(player, prop) && eligibleThresholds(prop).length))).length);
});
const legOptions = computed(() => {
  const first = isSweepMode.value ? 3 : 1;
  const last = Math.min(maxTargetLegs.value, isSweepMode.value ? 5 : maxTargetLegs.value);
  return Array.from({ length: Math.max(0, last - first + 1) }, (_, index) => {
    const value = String(index + first);
    return { value, label: `${value} ${value === "1" ? "leg" : "legs"}` };
  });
});
const keyFor = (game, player, prop) => `${game.game_id}:${player.player_id}:${prop}`;
const playerKey = (game, player) => `${game.game_id}:${player.player_id}`;
const availablePropOptions = computed(() => {
  const values = new Map();
  for (const game of board.value?.games || []) for (const player of game.players || []) for (const prop of player.props || []) if (eligibleThresholds(prop).length) {
    const value = playerPropMarketKey(player.kind, prop.prop);
    values.set(value, {
      label: `${player.kind === "pitcher" ? "Pitcher" : "Batter"} · ${prop.label}`,
      kind: player.kind,
    });
  }
  return [...values].map(([value, option]) => ({
    value,
    label: option.label,
    meta: `${option.kind === "pitcher" ? "Pitching" : "Batting"} market currently displayed by MelBet`,
  })).sort((a, b) => a.label.localeCompare(b.label));
});
const propSidePreference = market => ["both", "over", "under"].includes(propSidePreferences.value[market])
  ? propSidePreferences.value[market]
  : ["over", "under"].includes(buildSide.value) ? buildSide.value : "both";
const propDirectionSelection = market => selectedPropTypes.value.includes(market)
  ? propSidePreference(market)
  : "off";
const selectedPropSidePreferences = computed(() => Object.fromEntries(
  selectedPropTypes.value.map(market => [market, propSidePreference(market)]),
));
const selectedPropDirectionSummary = computed(() => {
  const sides = new Set(Object.values(selectedPropSidePreferences.value));
  if (!sides.size) return "both";
  return sides.size === 1 ? [...sides][0] : "mixed sides";
});
const selectedPropDirectionCounts = computed(() => availablePropOptions.value.reduce((counts, option) => {
  counts[propDirectionSelection(option.value)] += 1;
  return counts;
}, { off: 0, both: 0, over: 0, under: 0 }));
const auditBuildSide = computed(() => propPreset.value === "strongest"
  ? buildSide.value
  : selectedPropDirectionSummary.value === "mixed sides" ? "mixed" : selectedPropDirectionSummary.value);
const auditSelectedPropSides = computed(() => propPreset.value === "included"
  ? selectedPropSidePreferences.value
  : {});
const oddsEligible = value => Number.isFinite(Number(value)) && Number(value) >= (
  propPreset.value === "guarantee"
    ? guaranteeOddsFloor(minimumOdds.value)
    : minimumOdds.value === "all" ? 0 : Number(minimumOdds.value)
);
const formatOdds = value => Number.isFinite(Number(value)) ? Number(value).toFixed(3).replace(/0+$/, "").replace(/\.$/, "") : "—";
const rawMelbetSelections = (threshold, side) => threshold?.melbet_selections?.[side] || [];
const eligibleMelbetSelections = (threshold, side) => rawMelbetSelections(threshold, side).filter(selection => oddsEligible(selection.decimal_odds));
const rawAvailableSides = threshold => Array.isArray(threshold?.available_sides) && threshold.available_sides.length ? threshold.available_sides : ["over", "under"];
const sideAvailable = (threshold, side) => {
  if (!rawAvailableSides(threshold).includes(side)) return false;
  const selections = rawMelbetSelections(threshold, side);
  return selections.length ? eligibleMelbetSelections(threshold, side).length > 0 : minimumOdds.value === "all";
};
const availableSides = threshold => rawAvailableSides(threshold).filter(side => sideAvailable(threshold, side));
const eligibleThresholds = prop => (prop?.thresholds || []).filter(threshold => availableSides(threshold).length);
const guaranteeRecordFor = (player, prop, threshold, side) => guaranteeRecordMap.value.get(guaranteeExactKey(
  player?.player_id,
  player?.kind,
  prop?.prop,
  side,
  threshold?.line,
));
const exactGuaranteeCandidate = (player, prop, threshold, side) => allGuaranteeCandidates.value.find(candidate => (
  String(candidate.player?.player_id) === String(player?.player_id)
  && candidate.player?.kind === player?.kind
  && candidate.prop?.prop === prop?.prop
  && candidate.side === side
  && Number(candidate.line?.line) === Number(threshold?.line)
));
const guaranteeSides = (player, prop, threshold) => availableSides(threshold).filter(side => (
  Boolean(exactGuaranteeCandidate(player, prop, threshold, side))
));
const eligibleThresholdsForPlayer = (player, prop) => eligibleThresholds(prop).filter(threshold => (
  propPreset.value !== "guarantee" || guaranteeSides(player, prop, threshold).length
));
const propsFor = player => (player.props || []).filter(prop => propIncluded(player, prop) && eligibleThresholdsForPlayer(player, prop).length);
const selectedProp = (game, player) => {
  const available = propsFor(player);
  return available.find(prop => prop.prop === chosenProps.value[playerKey(game, player)]) || available.find(prop => prop.prop === player.best_projection?.prop) || available[0];
};
const selectedThreshold = (game, player) => {
  const prop = selectedProp(game, player); if (!prop) return null;
  const wanted = chosenLines.value[keyFor(game, player, prop.prop)] ?? prop.recommended_line;
  const thresholds = eligibleThresholdsForPlayer(player, prop);
  return thresholds.find(row => Number(row.line) === Number(wanted)) || thresholds.sort((a, b) => Math.max(...availableSides(b).map(side => Number(b[`${side}_probability`]))) - Math.max(...availableSides(a).map(side => Number(a[`${side}_probability`]))))[0];
};
const melbetSelections = (threshold, side) => eligibleMelbetSelections(threshold, side);
const preferredMelbetSelection = (threshold, side) => [...melbetSelections(threshold, side)].sort((a, b) => Number(b.decimal_odds || 0) - Number(a.decimal_odds || 0) || (a.format === "over_under" ? -1 : 1))[0] || null;
const selectionLabel = (threshold, side) => {
  const selections = melbetSelections(threshold, side);
  if (!selections.length) return `${side.toUpperCase()} ${threshold?.line}`;
  return selections.map(selection => `${selection.format === "at_least" ? `${selection.display_line} OR MORE` : ["yes", "yes_no"].includes(selection.format) ? (side === "over" ? "YES" : "NO") : `${side.toUpperCase()} ${selection.display_line}`} @ ${formatOdds(selection.decimal_odds)}`).join(" / ");
};
const propOptions = player => propsFor(player).map(prop => ({ value: prop.prop, label: prop.label, meta: `Last 10: ${prop.recent_10_average}` }));
const lineOptions = (game, player) => eligibleThresholdsForPlayer(player, selectedProp(game, player)).map(row => {
  const selections = availableSides(row).flatMap(side => melbetSelections(row, side));
  const names = [...new Set(selections.map(selection => selection.market_name))];
  const regular = selections.find(selection => selection.format === "over_under");
  const ladder = selections.find(selection => selection.format === "at_least");
  const direct = selections.find(selection => ["yes", "yes_no"].includes(selection.format));
  const listedLine = regular && ladder ? `O/U ${regular.display_line} / ${ladder.display_line}+` : regular ? `${row.available_sides?.length === 2 ? "O/U" : regular.side.toUpperCase()} ${regular.display_line}` : ladder ? `${ladder.display_line} OR MORE` : direct ? (row.available_sides?.length === 2 ? "YES / NO" : "YES") : row.line;
  const bestOdds = Math.max(...selections.map(selection => Number(selection.decimal_odds || 0)));
  return { value: String(row.line), label: `${selectedProp(game, player).label} — ${listedLine}`, meta: names.length ? `${names.join(" / ")} · best @ ${formatOdds(bestOdds)}` : `${pct(row.over_probability)} over` };
});
const legs = computed(() => Object.values(picks.value));
const rawJoint = computed(() => legs.value.length ? legs.value.reduce((total, leg) => total * Number(leg.probability), 1) : 0);
const adjustedJoint = computed(() => legs.value.length ? legs.value.reduce(
  (total, leg) => total * Number(
    leg.robust_probability
      ?? leg.recommendation_probability
      ?? historyAdjustedProbability(leg.probability, leg.history_games),
  ),
  1,
) : 0);
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
    selection: leg.melbet_selection_name || `${leg.player_name} — ${leg.label} — ${leg.side.toUpperCase()} ${leg.line}`,
    searchText: leg.player_name,
    url: melbetEventUrl(bookmakerId),
    note: bookmakerId ? `MelBet Players' stats event ${bookmakerId}` : "MelBet has not listed this player event in the current feed.",
    automation: bookmakerId ? {
      kind: "player_prop",
      eventId: String(bookmakerId),
      player: leg.player_name,
      melbetPlayerName: leg.melbet_player_name,
      prop: leg.propKey,
      marketLabel: leg.label,
      side: leg.side,
      line: Number(leg.line),
      melbetMarketLabel: leg.melbet_market_name,
      melbetSelectionName: leg.melbet_selection_name,
      melbetDisplayLine: leg.melbet_display_line,
      melbetFormat: leg.melbet_format,
      melbetGroupId: leg.melbet_group_id,
      melbetTypeId: leg.melbet_type_id,
    } : null,
  };
}));
const pct = value => `${(Number(value || 0) * 100).toFixed(1)}%`;
const dateLabel = value => new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" }).format(new Date(`${value}T12:00:00Z`));
const timeLabel = value => new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York", timeZoneName: "short" }).format(new Date(value));
const visiblePlayers = game => (game?.players || []).filter(player => propsFor(player).length && (role.value === "all" || player.kind === role.value)).sort((a, b) => Number(b.best_projection?.recommended_probability || 0) - Number(a.best_projection?.recommended_probability || 0));
const playersWithSelectedProps = game => (game?.players || []).filter(player => propsFor(player).length);
const gamePropsLabel = game => {
  const count = playersWithSelectedProps(game).length;
  if (game?.player_line_market?.market_status === "home_runs_only") {
    return count ? `VIEW ${count} HR-ONLY PLAYERS →` : "MELBET HAS HR-ONLY PROPS · FILTERED OUT";
  }
  return count ? `VIEW ${count} MATCHING PLAYERS →` : "NO MATCHING PLAYER PROPS";
};
const recommendationPolicy = computed(() => board.value?.automatic_recommendation_policy || {});
const automaticCandidatesForGame = game => {
  const rawCandidates = (game?.players || []).flatMap(player => propsFor(player).flatMap(prop => {
  const marketRule = automaticMarketRule(recommendationPolicy.value, player, prop);
  if (!marketRule?.automatic_eligible) return [];
  const side = propPreset.value === "strongest"
    ? strongestPlayerPropSide(player.kind, prop.prop)
    : playerPropBuildSide(
      propSidePreferences.value,
      player.kind,
      prop.prop,
      prop.recommended_side,
      buildSide.value,
    );

  // A short-priced primary ladder must not eliminate the entire game. Evaluate
  // every currently listed threshold that clears the user's odds floor, then
  // let calibrated model probability choose the strongest eligible line.
  return automaticThresholdCandidates(
    eligibleThresholds(prop),
    side,
    player.history_games,
    marketRule,
    sideAvailable,
    recommendationPolicy.value,
    { sweep: isSweepMode.value },
  ).map(({ line, probability, recommendationProbability, robustProbability, sportsbookProbability, evidence }) => ({
      game, player, prop, line, side, probability,
      recommendationProbability, robustProbability, sportsbookProbability, evidence, marketRule,
    }));
  }));
  const initiallyCalibrated = rawCandidates.sort((a, b) => b.robustProbability - a.robustProbability
    || b.recommendationProbability - a.recommendationProbability
    || b.probability - a.probability
    || Number(preferredMelbetSelection(b.line, b.side)?.decimal_odds || 0) - Number(preferredMelbetSelection(a.line, a.side)?.decimal_odds || 0))
    .map((candidate, index) => applyBuildSelectionCalibration(
    candidate,
    recommendationPolicy.value,
    {
      buildStyle: buildStyle.value,
      minimumOdds: minimumOdds.value,
      rotationDepth: rotationDepth.value,
      candidateRank: index + 1,
      propPreset: propPreset.value,
      selectedPropTypeCount: selectedPropTypes.value.length,
      selectionAction: "build_best",
    },
    ));
  const ranked = rerankWithinGameCandidates(initiallyCalibrated, recommendationPolicy.value);
  return ranked.map((candidate, index) => applyWithinGameReranking(applyBuildSelectionCalibration(
    candidate,
    recommendationPolicy.value,
    {
      buildStyle: buildStyle.value,
      minimumOdds: minimumOdds.value,
      rotationDepth: rotationDepth.value,
      candidateRank: index + 1,
      propPreset: propPreset.value,
      selectedPropTypeCount: selectedPropTypes.value.length,
      selectionAction: "build_best",
    },
  ), recommendationPolicy.value))
    .sort((a, b) => Number(b.rerankScore) - Number(a.rerankScore)
      || Number(b.processProbability) - Number(a.processProbability))
    .map((candidate, index) => ({ ...candidate, candidateRank: index + 1, withinGameRank: index + 1 }))
    .filter(candidate => candidate.robustProbability >= selectedRecommendationFloor.value);
};
const allAutomaticCandidates = computed(() => (board.value?.games || []).flatMap(automaticCandidatesForGame).sort(
  (a, b) => Number(b.rerankScore) - Number(a.rerankScore)
    || b.robustProbability - a.robustProbability || b.recommendationProbability - a.recommendationProbability,
));
const allGuaranteeCandidates = computed(() => rankGuaranteeCandidates(
  buildGuaranteeCandidates(
    board.value?.games || [],
    guaranteePayload.value?.records || [],
    { minimumOdds: minimumOdds.value, minimumSamples: 3 },
  ),
  recommendationPolicy.value,
  { minimumSupportProbability: DEFAULT_GUARANTEE_ROBUST_FLOOR },
));
const alternateAutomaticCandidates = computed(() => (board.value?.games || []).flatMap(game => rerankWithinGameCandidates(
  allAutomaticCandidates.value.filter(candidate => String(candidate.game.game_id) === String(game.game_id)).map(candidate => applyBuildSelectionCalibration(
    candidate,
    recommendationPolicy.value,
    {
      buildStyle: buildStyle.value,
      minimumOdds: minimumOdds.value,
      rotationDepth: rotationDepth.value,
      candidateRank: candidate.candidateRank,
      propPreset: propPreset.value,
      selectedPropTypeCount: selectedPropTypes.value.length,
      selectionAction: "alternate",
    },
  )),
  recommendationPolicy.value,
).map((candidate, index) => ({ ...candidate, candidateRank: index + 1, withinGameRank: index + 1 }))));
const automaticCandidates = computed(() => selectDiversifiedCandidates(
  allAutomaticCandidates.value,
  Number(targetLegs.value),
  recommendationPolicy.value,
  isSweepMode.value,
  {
    priorExposureKeys: new Set(cardExposureKeys.value),
    priorContextExposureKeys: new Set(cardExposureContextKeys.value),
    avoidPriorExposure: portfolioMode.value === "independent",
  },
));
const guaranteeCandidates = computed(() => selectGuaranteeCandidates(
  allGuaranteeCandidates.value,
  Number(targetLegs.value),
  {
    sweep: isSweepMode.value,
    priorExposureKeys: new Set(cardExposureKeys.value),
    priorContextExposureKeys: new Set(cardExposureContextKeys.value),
    avoidPriorExposure: portfolioMode.value === "independent",
  },
));
const activeCandidates = computed(() => propPreset.value === "guarantee"
  ? guaranteeCandidates.value
  : automaticCandidates.value);
const activeAlternateCandidates = computed(() => propPreset.value === "guarantee"
  ? allGuaranteeCandidates.value
  : alternateAutomaticCandidates.value);
const canRecommend = computed(() => activeCandidates.value.length >= Number(targetLegs.value));
const candidateKey = candidate => keyFor(candidate.game, candidate.player, candidate.prop.prop);
const selectedKeys = computed(() => new Set(Object.keys(picks.value)));
const bulkAlternateKeySet = computed(() => new Set(bulkAlternateKeys.value));
const bulkAlternateCandidates = computed(() => selectedLegs.value.filter(
  leg => bulkAlternateKeySet.value.has(`${leg.game_id}:${leg.player_id}:${leg.propKey}`)
    && alternateFor(leg),
));
const alternateFor = leg => nextSameGameAlternate(
  activeAlternateCandidates.value,
  leg,
  selectedKeys.value,
  new Set(usedAlternateKeys.value),
  selectedLegs.value,
);
const saferLineFor = leg => propPreset.value === "guarantee"
  ? null
  : saferSamePropLine(alternateAutomaticCandidates.value, leg);
const candidatePick = ({ game, player, prop, line, side, probability, recommendationProbability, robustProbability, processProbability, sportsbookProbability, evidence, postSelectionEvidence, candidateRank, withinGameRank, rerankScore, shadowRerankScore, rerankerPromoted, expectedValue, rawLineClearance, normalizedLineClearance, fragilityPenalty, fragilityReasons, sportsbookDisagreement, rerankerVersion, marketRule, melbetSelection: exactMelbetSelection, guaranteeRecord, guaranteeScore, guaranteeRobustFloor }, decision = {}) => {
  const melbetSelection = exactMelbetSelection || preferredMelbetSelection(line, side);
  return {
    game_id: game.game_id,
    player_id: player.player_id,
    player_name: player.name,
    kind: player.kind,
    team_id: player.team_id,
    prop: prop.prop,
    label: prop.label,
    line: line.line,
    side,
    probability,
    recommendation_probability: Number.isFinite(Number(recommendationProbability))
      ? Number(recommendationProbability)
      : null,
    robust_probability: Number.isFinite(Number(robustProbability)) ? Number(robustProbability) : null,
    process_probability: Number.isFinite(Number(processProbability)) ? Number(processProbability) : null,
    sportsbook_probability: sportsbookProbability != null && Number.isFinite(Number(sportsbookProbability)) ? Number(sportsbookProbability) : null,
    exact_audit_samples: Number(evidence?.exact?.samples || 0),
    selection_audit_samples: Number(evidence?.selection?.samples || 0),
    post_selection_samples: Number(postSelectionEvidence?.evidence?.samples || 0),
    candidate_rank: Number(candidateRank || 1),
    within_game_rank: Number(withinGameRank || candidateRank || 1),
    rerank_score: Number.isFinite(Number(rerankScore)) ? Number(rerankScore) : null,
    shadow_rerank_score: Number.isFinite(Number(shadowRerankScore)) ? Number(shadowRerankScore) : null,
    reranker_promoted: rerankerPromoted === true,
    expected_value: Number.isFinite(Number(expectedValue)) ? Number(expectedValue) : null,
    raw_line_clearance: Number.isFinite(Number(rawLineClearance)) ? Number(rawLineClearance) : null,
    normalized_line_clearance: Number.isFinite(Number(normalizedLineClearance)) ? Number(normalizedLineClearance) : null,
    fragility_penalty: Number(fragilityPenalty || 0),
    fragility_reasons: Array.isArray(fragilityReasons) ? fragilityReasons : [],
    sportsbook_disagreement: Number.isFinite(Number(sportsbookDisagreement)) ? Number(sportsbookDisagreement) : null,
    reranker_version: rerankerVersion || recommendationPolicy.value.reranker_version || "within_game_v1",
    selection_action: decision.selectionAction || "build_best",
    replaced_selection: decision.replacedSelection || null,
    audit_samples: Number(marketRule?.samples || 0),
    selection_source: guaranteeRecord ? "guarantee" : "model",
    guarantee_samples: Number(guaranteeRecord?.samples || 0),
    guarantee_correct: Number(guaranteeRecord?.correct || 0),
    guarantee_accuracy: Number.isFinite(Number(guaranteeRecord?.accuracy)) ? Number(guaranteeRecord.accuracy) : null,
    guarantee_wilson_lower: Number.isFinite(Number(guaranteeRecord?.wilson_lower)) ? Number(guaranteeRecord.wilson_lower) : null,
    guarantee_evidence: guaranteeRecord?.evidence || null,
    guarantee_score: Number.isFinite(Number(guaranteeScore)) ? Number(guaranteeScore) : null,
    guarantee_robust_floor: Number.isFinite(Number(guaranteeRobustFloor)) ? Number(guaranteeRobustFloor) : null,
    history_games: player.history_games,
    lineup_status: player.lineup_status,
    official_date: game.official_date,
    scheduled_start: game.datetime,
    matchup: `${game.away.name} at ${game.home.name}`,
    melbet_market_name: melbetSelection?.market_name,
    melbet_player_name: melbetSelection?.player_name,
    melbet_selection_name: melbetSelection?.selection_name,
    melbet_display_line: melbetSelection?.display_line,
    melbet_format: melbetSelection?.format,
    melbet_group_id: melbetSelection?.group_id,
    melbet_type_id: melbetSelection?.type_id,
    melbet_decimal_odds: melbetSelection?.decimal_odds,
  };
};
function archiveAdjustedCard(entries, selectionAction, decisions = []) {
  if (!entries.length) return;
  api.recordPlayerPropBuild({
    start_date: selectedStart.value,
    days: selectedDays.value,
    target_legs: Number(targetLegs.value),
    build_style: buildStyle.value,
    build_side: auditBuildSide.value,
    minimum_odds: minimumOdds.value,
    recommendation_cutoff: recommendationCutoff.value,
    portfolio_mode: portfolioMode.value,
    prop_preset: propPreset.value,
    guarantee_robust_floor: propPreset.value === "guarantee" ? DEFAULT_GUARANTEE_ROBUST_FLOOR : null,
    rotation_depth: rotationDepth.value,
    selection_action: selectionAction,
    shadow_test: shadowTestMode,
    decisions,
    selected_prop_types: selectedPropTypes.value,
    selected_prop_sides: auditSelectedPropSides.value,
    policy: recommendationPolicy.value,
    entries: entries.map(entry => ({
      game_id: entry.game_id,
      player_id: entry.player_id,
      player_name: entry.player_name,
      kind: entry.kind,
      team_id: entry.team_id,
      prop: entry.prop,
      label: entry.label,
      line: Number(entry.line),
      side: entry.side,
      model_probability: Number(entry.probability),
      recommendation_probability: Number(entry.recommendation_probability ?? entry.probability),
      robust_probability: Number(entry.robust_probability ?? entry.recommendation_probability ?? entry.probability),
      process_probability: Number(entry.process_probability ?? entry.robust_probability ?? entry.recommendation_probability ?? entry.probability),
      sportsbook_probability: entry.sportsbook_probability,
      decimal_odds: entry.melbet_decimal_odds,
      market_name: entry.melbet_market_name,
      selection_name: entry.melbet_selection_name,
      audit_samples: entry.audit_samples,
      exact_audit_samples: entry.exact_audit_samples,
      selection_audit_samples: entry.selection_audit_samples,
      post_selection_samples: entry.post_selection_samples,
      selection_source: entry.selection_source,
      guarantee_samples: entry.guarantee_samples,
      guarantee_correct: entry.guarantee_correct,
      guarantee_accuracy: entry.guarantee_accuracy,
      guarantee_wilson_lower: entry.guarantee_wilson_lower,
      guarantee_evidence: entry.guarantee_evidence,
      guarantee_score: entry.guarantee_score,
      guarantee_robust_floor: entry.guarantee_robust_floor,
      candidate_rank: entry.candidate_rank,
      within_game_rank: entry.within_game_rank,
      rerank_score: entry.rerank_score,
      shadow_rerank_score: entry.shadow_rerank_score,
      reranker_promoted: entry.reranker_promoted,
      expected_value: entry.expected_value,
      raw_line_clearance: entry.raw_line_clearance,
      normalized_line_clearance: entry.normalized_line_clearance,
      fragility_penalty: entry.fragility_penalty,
      fragility_reasons: entry.fragility_reasons,
      sportsbook_disagreement: entry.sportsbook_disagreement,
      reranker_version: entry.reranker_version,
      selection_action: entry.selection_action,
      replaced_selection: entry.replaced_selection,
      lineup_status: entry.lineup_status,
      official_date: entry.official_date,
      scheduled_start: entry.scheduled_start,
    })),
  }).catch(snapshotError => {
    marketNotice.value = `The adjusted card is ready, but its audit snapshot could not be stored: ${snapshotError.message}`;
  });
}
function rememberCandidateExposure(candidate) {
  cardExposureKeys.value = [...new Set([...cardExposureKeys.value, playerPropExposureKey(candidate)])];
  cardExposureContextKeys.value = [...new Set([
    ...cardExposureContextKeys.value,
    playerPropPortfolioContextKey(candidate),
  ])];
}
function useSaferLine(leg) {
  const candidate = saferLineFor(leg);
  if (!candidate) {
    marketNotice.value = "MelBet has no safer listed line for this prop that clears the current odds and audit rules.";
    return;
  }
  const key = `${leg.game_id}:${leg.player_id}:${leg.propKey}`;
  const decision = {
    action: "safer_line", game_id: leg.game_id,
    from: { player_id: leg.player_id, prop: leg.propKey, side: leg.side, line: leg.line },
    to: { player_id: candidate.player.player_id, prop: candidate.prop.prop, side: candidate.side, line: candidate.line.line },
  };
  const next = { ...picks.value, [key]: candidatePick(candidate, {
    selectionAction: "safer_line", replacedSelection: decision.from,
  }) };
  picks.value = next;
  rememberCandidateExposure(candidate);
  chosenLines.value = { ...chosenLines.value, [key]: Number(candidate.line.line) };
  marketNotice.value = `${leg.player_name} moved to the safer ${candidate.side.toUpperCase()} ${candidate.line.line} ${candidate.prop.label} line.`;
  archiveAdjustedCard(Object.values(next), "safer_line", [decision]);
}
const alternateCount = computed(() => selectedLegs.value.filter(leg => alternateFor(leg)).length);
const selectedAlternateLineCount = computed(() => bulkAlternateCandidates.value.length);
const allAlternateLinesSelected = computed(() => alternateCount.value > 0
  && selectedAlternateLineCount.value === alternateCount.value);
function toggleAllAlternateLines() {
  bulkAlternateKeys.value = allAlternateLinesSelected.value
    ? []
    : selectedLegs.value.filter(leg => alternateFor(leg)).map(
      leg => `${leg.game_id}:${leg.player_id}:${leg.propKey}`,
    );
}
function toggleBulkAlternate(leg) {
  const key = `${leg.game_id}:${leg.player_id}:${leg.propKey}`;
  bulkAlternateKeys.value = bulkAlternateKeySet.value.has(key)
    ? bulkAlternateKeys.value.filter(value => value !== key)
    : [...bulkAlternateKeys.value, key];
}
function useAlternateLinesForSelected() {
  let changed = 0;
  const next = { ...picks.value };
  const nextChosenLines = { ...chosenLines.value };
  const newlyUsed = [];
  const decisions = [];
  for (const leg of selectedLegs.value) {
    if (!bulkAlternateKeySet.value.has(`${leg.game_id}:${leg.player_id}:${leg.propKey}`)) continue;
    const alternate = alternateFor(leg);
    if (!alternate) continue;
    const replacementKey = candidateKey(alternate);
    const targetKey = Object.keys(next).find(key => {
      const pick = next[key];
      return String(pick.game_id) === String(leg.game_id)
        && String(pick.player_id) === String(leg.player_id)
        && pick.prop === leg.propKey;
    });
    if (targetKey) delete next[targetKey];
    const decision = {
      action: "alternate", game_id: leg.game_id,
      from: { player_id: leg.player_id, prop: leg.propKey, side: leg.side, line: leg.line },
      to: { player_id: alternate.player.player_id, prop: alternate.prop.prop, side: alternate.side, line: alternate.line.line },
    };
    next[replacementKey] = candidatePick(alternate, {
      selectionAction: "alternate", replacedSelection: decision.from,
    });
    decisions.push(decision);
    rememberCandidateExposure(alternate);
    nextChosenLines[replacementKey] = Number(alternate.line.line);
    newlyUsed.push(`${leg.game_id}:${leg.player_id}:${leg.propKey}`, replacementKey);
    changed += 1;
  }
  if (!changed) {
    marketNotice.value = "Select at least one checked leg whose game has another eligible player prop.";
    return;
  }
  picks.value = next;
  chosenLines.value = nextChosenLines;
  usedAlternateKeys.value = [...usedAlternateKeys.value, ...newlyUsed];
  bulkAlternateKeys.value = [];
  marketNotice.value = `${changed} checked ${changed === 1 ? "leg was" : "legs were"} replaced by the next-highest eligible player prop from the same game.`;
  archiveAdjustedCard(Object.values(next), "bulk_alternate", decisions);
}
const gamePick = game => legs.value.find(pick => String(pick.game_id) === String(game.game_id));
const selected = (game, player, side) => picks.value[keyFor(game, player, selectedProp(game, player)?.prop)]?.side === side;
const openGame = game => { activeGame.value = game; role.value = "all"; };
const closeGame = () => { activeGame.value = null; };
function chooseProp(game, player, value) { chosenProps.value = { ...chosenProps.value, [playerKey(game, player)]: value }; }
function chooseLine(game, player, value) { const prop = selectedProp(game, player); chosenLines.value = { ...chosenLines.value, [keyFor(game, player, prop.prop)]: Number(value) }; }
function select(game, player, side) {
  const prop = selectedProp(game, player), threshold = selectedThreshold(game, player); if (!prop || !threshold) return;
  if (propPreset.value === "strongest" && side !== strongestPlayerPropSide(player.kind, prop.prop)) return;
  const guaranteeCandidate = propPreset.value === "guarantee" ? exactGuaranteeCandidate(player, prop, threshold, side) : null;
  if (propPreset.value === "guarantee" && !guaranteeCandidate) return;
  if (!sideAvailable(threshold, side)) return;
  const key = keyFor(game, player, prop.prop), current = picks.value[key];
  const next = Object.fromEntries(Object.entries(picks.value).filter(([, pick]) => String(pick.game_id) !== String(game.game_id)));
  usedAlternateKeys.value = [];
  if (current?.side === side) { picks.value = next; return; }
  if (Object.keys(next).length >= Number(targetLegs.value)) return;
  if (guaranteeCandidate) {
    next[key] = candidatePick(guaranteeCandidate, { selectionAction: "manual" });
    picks.value = next;
    closeGame();
    return;
  }
  const melbetSelection = preferredMelbetSelection(threshold, side);
  next[key] = { game_id: game.game_id, player_id: player.player_id, player_name: player.name, kind: player.kind, team_id: player.team_id, prop: prop.prop, label: prop.label, line: threshold.line, side, probability: Number(threshold[`${side}_probability`]), selection_source: "model", history_games: player.history_games, matchup: `${game.away.name} at ${game.home.name}`, melbet_market_name: melbetSelection?.market_name, melbet_player_name: melbetSelection?.player_name, melbet_selection_name: melbetSelection?.selection_name, melbet_display_line: melbetSelection?.display_line, melbet_format: melbetSelection?.format, melbet_group_id: melbetSelection?.group_id, melbet_type_id: melbetSelection?.type_id, melbet_decimal_odds: melbetSelection?.decimal_odds };
  picks.value = next;
  closeGame();
}
function removeLeg(leg) {
  const key = `${leg.game_id}:${leg.player_id}:${leg.propKey}`;
  picks.value = Object.fromEntries(Object.entries(picks.value).filter(([, pick]) => !(String(pick.game_id) === String(leg.game_id) && String(pick.player_id) === String(leg.player_id) && pick.prop === leg.propKey)));
  bulkAlternateKeys.value = bulkAlternateKeys.value.filter(value => value !== key);
}
function clearCard() { picks.value = {}; usedAlternateKeys.value = []; bulkAlternateKeys.value = []; marketNotice.value = ""; }
function resetCardRotation() {
  cardExposureKeys.value = [];
  cardExposureContextKeys.value = [];
  rotationDepth.value = 0;
  exposureSlate.value = currentExposureSlate.value;
  marketNotice.value = "Independent-card exposure was reset for this slate.";
}
function useAlternate(leg) {
  const candidate = alternateFor(leg);
  if (!candidate) {
    marketNotice.value = "No additional unselected prop clears the current markets, build direction, odds floor and audited recommendation floor.";
    return;
  }
  const replacementKey = candidateKey(candidate);
  const decision = {
    action: "alternate", game_id: leg.game_id,
    from: { player_id: leg.player_id, prop: leg.propKey, side: leg.side, line: leg.line },
    to: { player_id: candidate.player.player_id, prop: candidate.prop.prop, side: candidate.side, line: candidate.line.line },
  };
  const replacement = candidatePick(candidate, {
    selectionAction: "alternate", replacedSelection: decision.from,
  });
  const next = Object.fromEntries(Object.entries(picks.value).map(([key, pick]) => {
    const isTarget = String(pick.game_id) === String(leg.game_id)
      && String(pick.player_id) === String(leg.player_id)
      && pick.prop === leg.propKey;
    return isTarget ? [replacementKey, replacement] : [key, pick];
  }));
  picks.value = next;
  rememberCandidateExposure(candidate);
  chosenProps.value = { ...chosenProps.value, [playerKey(candidate.game, candidate.player)]: candidate.prop.prop };
  chosenLines.value = { ...chosenLines.value, [replacementKey]: Number(candidate.line.line) };
  usedAlternateKeys.value = [
    ...usedAlternateKeys.value,
    `${leg.game_id}:${leg.player_id}:${leg.propKey}`,
    replacementKey,
  ];
  marketNotice.value = `${leg.player_name} ${leg.label} was replaced by ${candidate.player.name} ${candidate.prop.label}, the next-highest eligible prop that missed Build Best.`;
  archiveAdjustedCard(Object.values(next), "alternate", [decision]);
}
function updatePropTypes(values) { propFilterCustomized.value = true; selectedPropTypes.value = values; }
function setPropSide(market, side) {
  propFilterCustomized.value = true;
  if (side === "off") {
    selectedPropTypes.value = selectedPropTypes.value.filter(value => value !== market);
    return;
  }
  if (!selectedPropTypes.value.includes(market)) {
    selectedPropTypes.value = [...selectedPropTypes.value, market];
  }
  propSidePreferences.value = { ...propSidePreferences.value, [market]: side };
}
function setAllPropSides(side) {
  buildSide.value = side;
  propSidePreferences.value = {
    ...propSidePreferences.value,
    ...Object.fromEntries(selectedPropTypes.value.map(market => [market, side])),
  };
}
function editLeg(leg) {
  if (!leg.game || !leg.player) return;
  chosenProps.value = { ...chosenProps.value, [playerKey(leg.game, leg.player)]: leg.propKey };
  chosenLines.value = { ...chosenLines.value, [keyFor(leg.game, leg.player, leg.propKey)]: Number(leg.line) };
  openGame(leg.game);
}
async function recommend() {
  const candidates = activeCandidates.value.slice(0, Number(targetLegs.value));
  if (candidates.length < Number(targetLegs.value)) {
    if (propPreset.value === "guarantee") {
      marketNotice.value = `Only ${candidates.length} independent ${candidates.length === 1 ? "game has" : "games have"} an exact historical-consistency pick with at least ${Math.round(DEFAULT_GUARANTEE_ROBUST_FLOOR * 100)}% robust probability at @ ${guaranteeOddsFloor(minimumOdds.value).toFixed(2)} or higher. Reduce the target or odds floor.`;
      return;
    }
    const cutoffGuidance = recommendationCutoff.value === "ignore"
      ? "The probability cutoff is already ignored. Reduce the target, lower the odds floor, or include more prop markets."
      : "Reduce the target, lower the odds floor or probability cutoff, or include more prop markets.";
    marketNotice.value = `Only ${candidates.length} independent ${candidates.length === 1 ? "game has" : "games have"} an audited selection matching the chosen prop markets, build direction and odds floor ${recommendationCutoffLabel.value}. ${cutoffGuidance}`;
    return;
  }
  marketNotice.value = "";
  usedAlternateKeys.value = [];
  picks.value = Object.fromEntries(candidates.map(candidate => [candidateKey(candidate), candidatePick(candidate)]));
  const reused = candidates.filter(candidate => cardExposureKeys.value.includes(playerPropExposureKey(candidate))).length;
  cardExposureKeys.value = [...new Set([
    ...cardExposureKeys.value,
    ...candidates.map(playerPropExposureKey),
  ])];
  cardExposureContextKeys.value = [...new Set([
    ...cardExposureContextKeys.value,
    ...candidates.map(playerPropPortfolioContextKey),
  ])];
  exposureSlate.value = currentExposureSlate.value;
  if (portfolioMode.value === "independent") {
    marketNotice.value = reused
      ? "Independent Guarantee rotation was stopped because a prior exact leg would have been reused."
      : "Built with no repeated legs from earlier cards in this slate.";
  }
  bulkAlternateKeys.value = [];
  try {
    await api.recordPlayerPropBuild({
      start_date: selectedStart.value,
      days: selectedDays.value,
      target_legs: Number(targetLegs.value),
      build_style: buildStyle.value,
      build_side: auditBuildSide.value,
      minimum_odds: minimumOdds.value,
      recommendation_cutoff: recommendationCutoff.value,
      portfolio_mode: portfolioMode.value,
      prop_preset: propPreset.value,
      guarantee_robust_floor: propPreset.value === "guarantee" ? DEFAULT_GUARANTEE_ROBUST_FLOOR : null,
      rotation_depth: rotationDepth.value,
      selection_action: "build_best",
      shadow_test: shadowTestMode,
      selected_prop_types: selectedPropTypes.value,
      selected_prop_sides: auditSelectedPropSides.value,
      policy: recommendationPolicy.value,
      entries: candidates.map(candidate => {
        const selection = candidate.melbetSelection || preferredMelbetSelection(candidate.line, candidate.side);
        return {
          game_id: candidate.game.game_id,
          player_id: candidate.player.player_id,
          player_name: candidate.player.name,
          kind: candidate.player.kind,
          team_id: candidate.player.team_id,
          prop: candidate.prop.prop,
          label: candidate.prop.label,
          line: Number(candidate.line.line),
          side: candidate.side,
          model_probability: candidate.probability,
          recommendation_probability: candidate.recommendationProbability,
          robust_probability: candidate.robustProbability,
          process_probability: candidate.processProbability,
          sportsbook_probability: candidate.sportsbookProbability,
          decimal_odds: selection?.decimal_odds,
          market_name: selection?.market_name,
          selection_name: selection?.selection_name,
          audit_samples: candidate.marketRule?.samples,
          selection_source: candidate.guaranteeRecord ? "guarantee" : "model",
          guarantee_samples: candidate.guaranteeRecord?.samples,
          guarantee_correct: candidate.guaranteeRecord?.correct,
          guarantee_accuracy: candidate.guaranteeRecord?.accuracy,
          guarantee_wilson_lower: candidate.guaranteeRecord?.wilson_lower,
          guarantee_evidence: candidate.guaranteeRecord?.evidence,
          guarantee_score: candidate.guaranteeScore,
          guarantee_robust_floor: candidate.guaranteeRobustFloor,
          exact_audit_samples: candidate.evidence?.exact?.samples,
          selection_audit_samples: candidate.evidence?.selection?.samples,
          post_selection_samples: candidate.postSelectionEvidence?.evidence?.samples,
          candidate_rank: candidate.candidateRank,
          within_game_rank: candidate.withinGameRank,
          rerank_score: candidate.rerankScore,
          shadow_rerank_score: candidate.shadowRerankScore,
          reranker_promoted: candidate.rerankerPromoted,
          expected_value: candidate.expectedValue,
          raw_line_clearance: candidate.rawLineClearance,
          normalized_line_clearance: candidate.normalizedLineClearance,
          fragility_penalty: candidate.fragilityPenalty,
          fragility_reasons: candidate.fragilityReasons,
          sportsbook_disagreement: candidate.sportsbookDisagreement,
          reranker_version: candidate.rerankerVersion,
          selection_action: "build_best",
          lineup_status: candidate.player.lineup_status,
          official_date: candidate.game.official_date,
          scheduled_start: candidate.game.datetime,
        };
      }),
    });
    rotationDepth.value += 1;
  } catch (snapshotError) {
    marketNotice.value = `The card was built, but its audit snapshot could not be stored: ${snapshotError.message}`;
  }
}
function reconcilePicks(games) {
  const reconciled = {};
  const previousCount = Object.keys(picks.value).length;
  for (const pick of Object.values(picks.value)) {
    const game = (games || []).find(row => String(row.game_id) === String(pick.game_id));
    const player = game?.players?.find(row => String(row.player_id) === String(pick.player_id));
    const prop = player?.props?.find(row => row.prop === pick.prop);
    const threshold = prop?.thresholds?.find(row => Number(row.line) === Number(pick.line));
    if (!game || !player || !prop || !threshold || !sideAvailable(threshold, pick.side)) continue;
    const guaranteeCandidate = pick.selection_source === "guarantee"
      ? exactGuaranteeCandidate(player, prop, threshold, pick.side)
      : null;
    if (pick.selection_source === "guarantee" && !guaranteeCandidate) continue;
    if (guaranteeCandidate) {
      reconciled[keyFor(game, player, prop.prop)] = {
        ...pick,
        ...candidatePick(guaranteeCandidate, {
          selectionAction: pick.selection_action || "build_best",
          replacedSelection: pick.replaced_selection || null,
        }),
      };
      continue;
    }
    const melbetSelection = preferredMelbetSelection(threshold, pick.side);
    if (!melbetSelection) continue;
    const marketRule = automaticMarketRule(recommendationPolicy.value, player, prop);
    const adjusted = robustRecommendationProbability(
      Number(threshold[`${pick.side}_probability`]),
      player.history_games,
      marketRule,
      pick.side,
      threshold.line,
      recommendationPolicy.value,
    );
    reconciled[keyFor(game, player, prop.prop)] = {
      ...pick,
      player_name: player.name,
      team_id: player.team_id,
      label: prop.label,
      line: Number(threshold.line),
      probability: Number(threshold[`${pick.side}_probability`]),
      recommendation_probability: pick.selection_source === "guarantee"
        ? pick.recommendation_probability
        : pick.recommendation_probability == null || !marketRule?.automatic_eligible
        ? null
        : adjusted.recommendationProbability,
      robust_probability: pick.selection_source === "guarantee"
        ? pick.robust_probability
        : pick.recommendation_probability == null || !marketRule?.automatic_eligible
        ? null
        : adjusted.robustProbability,
      exact_audit_samples: Number(adjusted.evidence?.exact?.samples || 0),
      selection_audit_samples: Number(adjusted.evidence?.selection?.samples || 0),
      history_games: player.history_games,
      lineup_status: player.lineup_status,
      official_date: game.official_date,
      scheduled_start: game.datetime,
      matchup: `${game.away.name} at ${game.home.name}`,
      melbet_market_name: melbetSelection?.market_name,
      melbet_player_name: melbetSelection?.player_name,
      melbet_selection_name: melbetSelection?.selection_name,
      melbet_display_line: melbetSelection?.display_line,
      melbet_format: melbetSelection?.format,
      melbet_group_id: melbetSelection?.group_id,
      melbet_type_id: melbetSelection?.type_id,
      melbet_decimal_odds: melbetSelection?.decimal_odds,
    };
  }
  picks.value = reconciled;
  bulkAlternateKeys.value = bulkAlternateKeys.value.filter(key => Object.hasOwn(reconciled, key));
  const removed = previousCount - Object.keys(reconciled).length;
  marketNotice.value = removed ? `${removed} saved ${removed === 1 ? "leg was" : "legs were"} removed because the selection no longer clears the current MelBet or eligibility rules.` : "";
}
async function load(refresh = false) {
  const current = ++token; loading.value = true; error.value = "";
  try {
    const [result, guarantees] = await Promise.all([
      api.playerProps(selectedStart.value, selectedDays.value, refresh === true),
      api.playerPropGuarantees(3),
    ]);
    if (current === token) {
      board.value = result;
      guaranteePayload.value = guarantees;
      reconcilePicks(result.games);
    }
  }
  catch (caught) { if (current === token) error.value = caught?.message || "Player props could not be loaded."; }
  finally { if (current === token) loading.value = false; }
}
const onKeydown = event => { if (event.key === "Escape") closeGame(); };
watch([mode, date, () => dateRange.value.start, () => dateRange.value.end], load);
watch(availablePropOptions, options => {
  if (!options.length) return;
  const available = new Set(options.map(option => option.value));
  if (!propFilterInitialized.value) propFilterInitialized.value = true;
  if (!propFilterCustomized.value) {
    selectedPropTypes.value = [...available];
    return;
  }
  const requested = selectedPropTypes.value;
  const retained = normalizePlayerPropMarkets(requested, available);
  if (retained.length || !requested.length) {
    selectedPropTypes.value = retained;
  } else {
    selectedPropTypes.value = [...available];
    propFilterCustomized.value = false;
    marketNotice.value = "Your saved prop filter did not match today's MelBet markets, so all available props were restored.";
  }
}, { immediate: true });
watch(selectedPropTypes, values => {
  if (propPreset.value === "guarantee") return;
  picks.value = Object.fromEntries(Object.entries(picks.value).filter(([, pick]) => {
    const playerKind = pick.kind || (board.value?.games || [])
      .find(game => String(game.game_id) === String(pick.game_id))?.players
      ?.find(player => String(player.player_id) === String(pick.player_id))?.kind;
    return playerPropMarketSelected(values, playerKind, pick.prop);
  }));
}, { deep: true });
watch(propPreset, value => {
  if (value === "guarantee") {
    if (minimumOdds.value === "all" || Number(minimumOdds.value) < 1.2) minimumOdds.value = "1.20";
    picks.value = Object.fromEntries(Object.entries(picks.value).filter(([, pick]) => pick.selection_source === "guarantee"));
    return;
  }
  picks.value = Object.fromEntries(Object.entries(picks.value).filter(([, pick]) => pick.selection_source !== "guarantee"));
  if (value !== "strongest") return;
  picks.value = Object.fromEntries(Object.entries(picks.value).filter(([, pick]) => {
    const playerKind = pick.kind || (board.value?.games || [])
      .find(game => String(game.game_id) === String(pick.game_id))?.players
      ?.find(player => String(player.player_id) === String(pick.player_id))?.kind;
    return strongestPlayerPropSide(playerKind, pick.prop) === pick.side;
  }));
});
watch(minimumOdds, () => { if (board.value) reconcilePicks(board.value.games); });
watch([mode, date, dateRange, targetLegs, role, buildSide, buildStyle, portfolioMode, propPreset, minimumOdds, recommendationCutoff, picks, selectedPropTypes, propSidePreferences, usedAlternateKeys, bulkAlternateKeys, cardExposureKeys, cardExposureContextKeys, rotationDepth, exposureSlate], () => localStorage.setItem("ninth-props-builder", JSON.stringify({ mode: mode.value, date: date.value, dateRange: dateRange.value, targetLegs: targetLegs.value, role: role.value, buildSide: buildSide.value, buildStyle: buildStyle.value, portfolioMode: portfolioMode.value, propPreset: propPreset.value, minimumOdds: minimumOdds.value, recommendationCutoff: recommendationCutoff.value, picks: picks.value, usedAlternateKeys: usedAlternateKeys.value, bulkAlternateKeys: bulkAlternateKeys.value, cardExposureKeys: cardExposureKeys.value, cardExposureContextKeys: cardExposureContextKeys.value, rotationDepth: rotationDepth.value, exposureSlate: exposureSlate.value, propTypes: selectedPropTypes.value, propSidePreferences: propSidePreferences.value, propTypesCustomized: propFilterCustomized.value, updatedAt: Date.now() })), { deep: true });
watch(currentExposureSlate, slate => {
  if (exposureSlate.value && exposureSlate.value !== slate) {
    cardExposureKeys.value = [];
    cardExposureContextKeys.value = [];
    rotationDepth.value = 0;
  }
  exposureSlate.value = slate;
}, { immediate: true });
watch(buildStyle, value => {
  if (value === "sweep" && Number(targetLegs.value) > 5) targetLegs.value = "5";
  if (value === "sweep" && Number(targetLegs.value) < 3) targetLegs.value = "3";
});
watch(targetLegs, () => { if (legs.value.length > Number(targetLegs.value)) picks.value = Object.fromEntries(Object.entries(picks.value).slice(0, Number(targetLegs.value))); });
watch(maxTargetLegs, count => {
  const minimum = isSweepMode.value ? 3 : 1;
  if (count >= minimum && Number(targetLegs.value) > count) targetLegs.value = String(count);
});
onMounted(() => {
  poller = createSharedPoller({
    key: () => `player-props:${selectedStart.value}:${selectedDays.value}`,
    task: load,
    interval: () => Math.max(60, Number(board.value?.refresh_seconds || 300)) * 1000,
  });
  poller.start();
  window.addEventListener("keydown", onKeydown);
});
onBeforeUnmount(() => { poller?.stop(); window.removeEventListener("keydown", onKeydown); });
</script>

<template>
  <div class="props-page">
    <section class="props-hero">
      <div class="hero-copy"><span class="eyebrow">NINTH / PLAYER LAB</span><h1>Build from the player up.</h1><p>Start with a matchup, inspect its available player markets, then add only the legs you want to the card.</p></div>
      <div class="hero-tools">
        <BuilderMarketTabs active="props" />
        <div class="slate-toolbar"><SlateModeToggle v-model="mode" /><CustomDatePicker v-if="mode === 'daily'" v-model="date" label="Game date" /><CustomDateRangePicker v-else v-model="dateRange" label="Game range" :max-days="7" /><CustomSelect v-model="targetLegs" label="Target legs" :options="legOptions" /><OddsFloorSelect v-model="minimumOdds" :label="propPreset === 'guarantee' ? 'Guarantee odds floor' : 'Minimum MelBet odds'" :minimum="propPreset === 'guarantee' ? 1.2 : 1.1" :include-all="propPreset !== 'guarantee'" /><BuilderRefreshButton :loading="loading" @refresh="load(true)" /></div>
        <details class="advanced-controls">
          <summary><span>BUILD RULES</span><b>{{ propPreset === 'strongest' ? 'Strongest picks' : propPreset === 'guarantee' ? `Guarantee · ${Math.round(DEFAULT_GUARANTEE_ROBUST_FLOOR * 100)}% robust · @ ${guaranteeOddsFloor(minimumOdds).toFixed(2)}+` : `${selectedPropTypes.length} props · ${selectedPropDirectionSummary}` }}<template v-if="propPreset !== 'guarantee'"> · {{ recommendationCutoff === 'ignore' ? 'no cutoff' : `${Math.round(selectedRecommendationFloor * 100)}% floor` }}</template></b></summary>
          <div class="advanced-grid">
            <CustomSelect v-if="propPreset !== 'guarantee'" v-model="recommendationCutoff" class="cutoff-control" label="Prop cutoff" :options="probabilityCutoffOptions" />
            <CustomSelect v-model="propPreset" class="preset-control" label="Pick set" :options="propPresetOptions" />
            <CustomMultiSelect v-if="propPreset === 'included'" :model-value="selectedPropTypes" class="prop-market-filter" label="Included player props" placeholder="No prop markets selected" :options="availablePropOptions" @update:model-value="updatePropTypes" />
            <div v-else-if="propPreset === 'strongest'" class="strongest-summary"><span>STRONGEST PICKS</span><p>{{ strongestPlayerPropMarkets.map(market => market.label).join(' · ') }}</p></div>
            <div v-else class="strongest-summary guarantee-summary"><span>GUARANTEE HISTORY + TODAY'S MODEL</span><p>Exact player, role, prop, side and line · 3+ settled picks · at least {{ Math.round(DEFAULT_GUARANTEE_ROBUST_FLOOR * 100) }}% robust probability · live MelBet odds @ {{ guaranteeOddsFloor(minimumOdds).toFixed(2) }} or higher.</p></div>
            <CustomSelect v-model="portfolioMode" class="rotation-control" label="Card rotation" :options="portfolioModeOptions" />
            <div v-if="propPreset === 'included'" class="build-side-control"><span>APPLY DIRECTION TO ALL INCLUDED PROPS</span><div role="group" aria-label="Apply automatic build direction to all included player props"><button v-for="side in ['both','over','under']" :key="side" type="button" :class="{ active: selectedPropDirectionSummary === side }" :aria-pressed="selectedPropDirectionSummary === side" @click="setAllPropSides(side)">{{ side.toUpperCase() }}</button></div></div>
            <div v-if="propPreset === 'included' && availablePropOptions.length" class="prop-side-preferences">
              <header><span>PROP-SPECIFIC DIRECTIONS</span><small>{{ selectedPropDirectionCounts.off }} off · {{ selectedPropDirectionCounts.over }} over · {{ selectedPropDirectionCounts.under }} under · {{ selectedPropDirectionCounts.both }} both</small></header>
              <div class="prop-side-list">
                <div v-for="option in availablePropOptions" :key="option.value" class="prop-side-row"><span><b>{{ option.label }}</b><small>{{ option.meta }}</small></span><div role="group" :aria-label="`${option.label} automatic build direction`"><button v-for="side in ['off','both','over','under']" :key="side" type="button" :class="{ active: propDirectionSelection(option.value) === side }" :aria-pressed="propDirectionSelection(option.value) === side" @click="setPropSide(option.value, side)">{{ side.toUpperCase() }}</button></div></div>
              </div>
            </div>
            <button v-if="cardExposureKeys.length" type="button" class="reset-rotation" @click="resetCardRotation">RESET ROTATION · {{ cardExposureKeys.length }}</button>
          </div>
        </details>
      </div>
    </section>

    <section class="scoreboard">
      <ProbabilityRing class="score-ring" :value="adjustedJoint" :size="112" />
      <div class="score-copy"><span class="eyebrow">ROBUST SLIP CONFIDENCE</span><h2>{{ scoreLabel }}</h2><p>{{ propPreset === 'guarantee' ? `Guarantee mode first requires both today's model and the exact historical record to support at least ${Math.round(DEFAULT_GUARANTEE_ROBUST_FLOOR * 100)}% robust probability, then ranks only the survivors.` : 'Exact line, selection-bias and MelBet-consistency checks are applied before ranking. Independent rotation avoids legs used on earlier cards.' }}</p><small>HISTORICAL CONSISTENCY AND MODEL PROBABILITY, NOT FUTURE CERTAINTY</small></div>
      <div class="score-metrics"><span><small>LEGS</small><b>{{ legs.length }} / {{ targetLegs }}</b></span><span><small>ADJUSTED</small><b>{{ pct(adjustedJoint) }}</b></span><span><small>RAW PRODUCT</small><b>{{ pct(rawJoint) }}</b></span><span><small>TYPICAL LEG</small><b>{{ pct(typicalLeg) }}</b></span></div>
      <div class="score-actions"><div class="card-style" role="group" aria-label="Card style"><button type="button" :class="{ active: buildStyle === 'balanced' }" @click="buildStyle = 'balanced'">BALANCED</button><button type="button" :class="{ active: buildStyle === 'sweep' }" @click="buildStyle = 'sweep'">SWEEP 3–5</button></div><button class="recommend" :disabled="loading || !board" @click="recommend"><Sparkles /> BUILD {{ propPreset === 'guarantee' ? 'GUARANTEE' : buildStyle === 'sweep' ? 'SWEEP' : 'BEST' }} {{ targetLegs }}</button><small v-if="board && !canRecommend">{{ activeCandidates.length }} of {{ targetLegs }} games qualify {{ propPreset === 'guarantee' ? `with ${Math.round(DEFAULT_GUARANTEE_ROBUST_FLOOR * 100)}%+ robust exact history at @ ${guaranteeOddsFloor(minimumOdds).toFixed(2)}+` : recommendationCutoffLabel }}</small><MelbetHandoff :entries="melbetEntries" autofill-mode="player_prop" /><button class="clear" :disabled="!legs.length" @click="clearCard"><Trash2 /> CLEAR</button></div>
    </section>
    <div v-if="marketNotice" class="market-notice">{{ marketNotice }}</div>

    <section v-if="selectedLegs.length" class="selected-section">
      <header><div><span class="eyebrow">YOUR PLAYER PROP CARD</span><h2>{{ selectedLegs.length }} selected {{ selectedLegs.length === 1 ? 'leg' : 'legs' }}</h2></div><div class="selected-header-actions"><small>Check legs to replace with the next-best player prop from the same game.</small><div><button type="button" :disabled="!alternateCount" @click="toggleAllAlternateLines"><Check /> {{ allAlternateLinesSelected ? 'CLEAR ALL' : 'SELECT ALL' }}</button><button type="button" :disabled="!selectedAlternateLineCount" @click="useAlternateLinesForSelected"><RefreshCw /> USE CHECKED ALTERNATES · {{ selectedAlternateLineCount }}/{{ alternateCount }}</button></div></div></header>
      <div class="selected-grid">
        <article v-for="leg in selectedLegs" :key="`${leg.game_id}:${leg.player_id}:${leg.propKey}`" class="selected-card" @click="editLeg(leg)">
          <label class="bulk-check" :class="{ disabled: !alternateFor(leg) }" @click.stop><input type="checkbox" :checked="bulkAlternateKeySet.has(`${leg.game_id}:${leg.player_id}:${leg.propKey}`)" :disabled="!alternateFor(leg)" :aria-label="`Replace ${leg.player_name} with the next-best prop from this game`" @change="toggleBulkAlternate(leg)" /><span><Check /></span><small>ALTERNATE</small></label>
          <button class="remove" aria-label="Remove leg" @click.stop="removeLeg(leg)"><X /></button>
          <div class="player"><PlayerHeadshot :player="{ id: leg.player_id, name: leg.player_name }" :size="76" /><span><small>{{ leg.player?.kind?.toUpperCase() || 'PLAYER' }} · {{ leg.player?.lineup_status?.toUpperCase() || 'PROJECTED' }}</small><b>{{ leg.player_name }}</b><em>{{ leg.matchup }}</em></span></div>
          <div class="selected-line"><span><small>{{ leg.melbet_selection_name || `${leg.side.toUpperCase()} ${leg.line}` }}</small><b>{{ leg.melbet_market_name || leg.label }} · @ {{ formatOdds(leg.melbet_decimal_odds) }}</b></span><span class="model-chance"><small>{{ leg.robust_probability == null ? 'NINTH MODEL' : 'ROBUST' }}</small><strong>{{ pct(leg.robust_probability ?? leg.recommendation_probability ?? leg.probability) }}</strong></span></div>
          <div class="leg-actions"><button type="button" :disabled="!alternateFor(leg)" @click.stop="useAlternate(leg)"><RefreshCw /><span><small>NEXT PROP</small><b v-if="alternateFor(leg)">{{ alternateFor(leg).player.name }} · {{ alternateFor(leg).prop.label }}</b><b v-else>None eligible</b></span></button><button type="button" :disabled="!saferLineFor(leg)" @click.stop="useSaferLine(leg)"><span><small>SAFER LINE</small><b v-if="saferLineFor(leg)">{{ saferLineFor(leg).side.toUpperCase() }} {{ saferLineFor(leg).line.line }} · @ {{ formatOdds(preferredMelbetSelection(saferLineFor(leg).line, saferLineFor(leg).side)?.decimal_odds) }}</b><b v-else>Not listed</b></span></button></div>
          <footer v-if="leg.selection_source === 'guarantee'">EXACT HISTORY <b>{{ leg.guarantee_correct }}/{{ leg.guarantee_samples }} · {{ pct(leg.guarantee_accuracy) }}</b><span>{{ leg.guarantee_evidence }} · {{ pct(leg.guarantee_wilson_lower) }} lower bound</span></footer><footer v-else>LAST 10 AVG <b>{{ leg.prop?.recent_10_average ?? '—' }}</b><span>{{ leg.prop?.confidence_label || 'Model' }} confidence · {{ leg.prop?.confidence_score ?? '—' }}/100</span></footer>
        </article>
      </div>
    </section>

    <LoadingState v-if="loading && !board" label="Building player distributions" detail="Loading official lineups, probable starters and calibrated prop thresholds." />
    <div v-else-if="error" class="error">{{ error }} <button @click="load">RETRY</button></div>
    <template v-else-if="board">
      <div class="board-note"><span><i></i>{{ board.games.length }} GAMES · {{ dateLabel(selectedStart).toUpperCase() }} · {{ board.player_prop_line_feed?.listed_games || 0 }} WITH CURRENT PLAYER MARKETS<template v-if="board.player_prop_line_feed?.partial_games"> · {{ board.player_prop_line_feed.partial_games }} PARTIAL</template><template v-if="propPreset === 'guarantee'"> · GUARANTEE @ {{ guaranteeOddsFloor(minimumOdds).toFixed(2) }}+ · {{ Math.round(DEFAULT_GUARANTEE_ROBUST_FLOOR * 100) }}%+ ROBUST · 3+ EXACT SETTLED</template><template v-else> · {{ minimumOdds === 'all' ? 'ALL ODDS' : `MINIMUM @ ${minimumOdds}` }} · {{ recommendationCutoff === 'ignore' ? 'NO PROP CUTOFF' : `PROP CUTOFF ${Math.round(selectedRecommendationFloor * 100)}%` }}</template> · AUTO {{ board.refresh_seconds }}S</span><p>{{ propPreset === 'guarantee' ? `Only the same player, role, prop, side and exact line is eligible, and the weaker of today's model probability and its historical probability must be at least ${Math.round(DEFAULT_GUARANTEE_ROBUST_FLOOR * 100)}%.` : 'MelBet odds remain an eligibility signal, not a model input. Partial games are checked every 15 seconds until standard player markets appear; sparse exact lines remain manual-only.' }}</p></div>
      <section v-if="board.games.length" class="game-grid">
        <button v-for="game in board.games" :key="game.game_id" class="game-card" :class="{ picked: gamePick(game), unavailable: !playersWithSelectedProps(game).length }" :disabled="!playersWithSelectedProps(game).length" @click="openGame(game)">
          <span class="game-time">{{ timeLabel(game.datetime) }}</span>
          <div class="team"><TeamLogo :team="game.away" :size="58" /><span><b>{{ game.away.name }}</b><small>AWAY</small></span></div>
          <div class="versus">AT</div>
          <div class="team home"><span><b>{{ game.home.name }}</b><small>HOME</small></span><TeamLogo :team="game.home" :size="58" /></div>
          <div v-if="gamePick(game)" class="game-selection"><Check /><span><b>{{ gamePick(game).player_name }}</b><small>{{ gamePick(game).side.toUpperCase() }} {{ gamePick(game).line }} {{ gamePick(game).label }}</small></span></div>
          <span class="open-props">{{ gamePick(game) ? 'EDIT PLAYER PROP' : gamePropsLabel(game) }}</span>
        </button>
      </section>
      <div v-else class="empty">No upcoming MLB games were found in this range.</div>
    </template>

    <Teleport to="body">
      <AnimatePresence>
      <motion.div v-if="activeGame" class="modal-backdrop" :initial="reducedMotion?false:{opacity:0,backdropFilter:'blur(0px)'}" :animate="{opacity:1,backdropFilter:'blur(8px)'}" :exit="reducedMotion?undefined:{opacity:0,backdropFilter:'blur(0px)'}" :transition="{duration:.24}" @click.self="closeGame">
        <motion.section class="props-modal" role="dialog" aria-modal="true" :aria-label="`${activeGame.away.name} at ${activeGame.home.name} player props`" :initial="reducedMotion?false:{opacity:0,y:28,scale:.96,filter:'blur(8px)'}" :animate="{opacity:1,y:0,scale:1,filter:'blur(0px)'}" :exit="reducedMotion?undefined:{opacity:0,y:16,scale:.97,filter:'blur(6px)'}" :transition="{type:'spring',stiffness:250,damping:28}">
          <header class="modal-header"><div class="modal-matchup"><TeamLogo :team="activeGame.away" :size="48" /><span><small>{{ timeLabel(activeGame.datetime) }}</small><b>{{ activeGame.away.name }} <em>at</em> {{ activeGame.home.name }}</b></span><TeamLogo :team="activeGame.home" :size="48" /></div><button aria-label="Close player props" @click="closeGame"><X /></button></header>
          <div class="modal-toolbar"><div><span class="eyebrow">AVAILABLE PLAYER PROPS</span><p>Select a player, market and line. One leg is allowed from each game.</p></div><div class="seg"><button v-for="value in ['all','batter','pitcher']" :key="value" :class="{ active: role === value }" @click="role = value">{{ value.toUpperCase() }}</button></div></div>
          <div class="modal-scroll"><div v-if="visiblePlayers(activeGame).length" class="player-grid">
            <article v-for="player in visiblePlayers(activeGame)" :key="player.player_id" class="player-card" :class="{ picked: gamePick(activeGame)?.player_id === player.player_id }">
              <div class="player"><PlayerHeadshot :player="{ id: player.player_id, name: player.name }" :size="72" /><span><small>{{ player.kind.toUpperCase() }} · {{ player.lineup_status.toUpperCase() }}</small><b>{{ player.name }}</b><em>{{ player.role }} · {{ player.history_games }} tracked games</em></span></div>
              <div class="selectors"><CustomSelect :model-value="selectedProp(activeGame, player)?.prop" label="Prop" :options="propOptions(player)" @update:model-value="chooseProp(activeGame, player, $event)" /><CustomSelect :model-value="String(selectedThreshold(activeGame, player)?.line)" label="Line" :options="lineOptions(activeGame, player)" @update:model-value="chooseLine(activeGame, player, $event)" /></div>
              <div v-if="selectedThreshold(activeGame, player)" class="sides"><button v-for="side in ['over','under']" :key="side" :disabled="!sideAvailable(selectedThreshold(activeGame, player), side) || (propPreset === 'strongest' && side !== strongestPlayerPropSide(player.kind, selectedProp(activeGame, player).prop)) || (propPreset === 'guarantee' && !exactGuaranteeCandidate(player, selectedProp(activeGame, player), selectedThreshold(activeGame, player), side)) || (legs.length >= Number(targetLegs) && !gamePick(activeGame))" :class="{ active: selected(activeGame, player, side), unavailable: !sideAvailable(selectedThreshold(activeGame, player), side) || (propPreset === 'strongest' && side !== strongestPlayerPropSide(player.kind, selectedProp(activeGame, player).prop)) || (propPreset === 'guarantee' && !exactGuaranteeCandidate(player, selectedProp(activeGame, player), selectedThreshold(activeGame, player), side)) }" @click="select(activeGame, player, side)"><span><small>{{ sideAvailable(selectedThreshold(activeGame, player), side) ? selectionLabel(selectedThreshold(activeGame, player), side) : `${side.toUpperCase()} NOT LISTED` }}</small><b>{{ preferredMelbetSelection(selectedThreshold(activeGame, player), side)?.market_name || selectedProp(activeGame, player).label }}</b></span><span v-if="sideAvailable(selectedThreshold(activeGame, player), side)" class="model-chance"><template v-if="propPreset !== 'guarantee' || exactGuaranteeCandidate(player, selectedProp(activeGame, player), selectedThreshold(activeGame, player), side)"><small>{{ propPreset === 'guarantee' ? 'ROBUST / HISTORY' : 'NINTH MODEL' }}</small><strong>{{ propPreset === 'guarantee' ? `${pct(exactGuaranteeCandidate(player, selectedProp(activeGame, player), selectedThreshold(activeGame, player), side).robustProbability)} · ${guaranteeRecordFor(player, selectedProp(activeGame, player), selectedThreshold(activeGame, player), side).correct}/${guaranteeRecordFor(player, selectedProp(activeGame, player), selectedThreshold(activeGame, player), side).samples}` : pct(selectedThreshold(activeGame, player)[`${side}_probability`]) }}</strong></template><small v-else>BELOW GUARANTEE FLOOR</small></span><Check /></button></div>
              <footer>LAST 10 AVG <b>{{ selectedProp(activeGame, player)?.recent_10_average }}</b><span>{{ selectedProp(activeGame, player)?.confidence_label }} confidence · {{ selectedProp(activeGame, player)?.confidence_score }}/100</span></footer>
            </article>
          </div><div v-else class="empty">No {{ role === 'all' ? '' : role }} props are available for this matchup.</div></div>
        </motion.section>
      </motion.div>
      </AnimatePresence>
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
.selected-line{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center}.selected-line>span:first-child{min-width:0}.selected-line>span:first-child b{line-height:1.35;overflow-wrap:anywhere}.model-chance{min-width:54px;text-align:right}.model-chance small{display:block;font-size:7px!important;letter-spacing:.04em;opacity:.7;margin-bottom:2px}.model-chance strong{display:block;white-space:nowrap}
.market-notice{padding:12px 16px;border:1px solid #d99b32;background:color-mix(in srgb,#d99b32 13%,var(--surface));color:var(--text);font-size:10px;font-weight:800}
.sides button.unavailable{opacity:.45;cursor:not-allowed}.sides button.unavailable b{font-size:10px}
.selected-header-actions{display:grid;justify-items:end;gap:8px}.selected-header-actions>div{display:flex;gap:8px}.selected-header-actions button{display:flex;align-items:center;gap:7px;padding:9px 11px;border:1px solid var(--line);background:var(--surface-2);color:var(--text);font-size:8px;font-weight:900}.selected-header-actions button:disabled{opacity:.45}.selected-header-actions svg{width:13px}.selected-card{padding-top:50px}.bulk-check{position:absolute;left:14px;top:12px;z-index:2;display:flex;align-items:center;gap:7px;cursor:pointer}.bulk-check input{position:absolute;opacity:0;pointer-events:none}.bulk-check span{width:24px;height:24px;display:grid;place-items:center;border:1px solid var(--line);background:var(--surface);color:transparent}.bulk-check input:checked+span{border-color:var(--accent);background:var(--accent);color:var(--ink)}.bulk-check svg{width:14px}.bulk-check small{font:800 7px 'DM Mono';letter-spacing:.06em;color:var(--muted)}.bulk-check.disabled{opacity:.35;cursor:not-allowed}
.prop-filter-row{width:100%;display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:8px;align-items:end}.build-side-control>span{display:block;margin-bottom:6px;font:500 7px 'DM Mono';letter-spacing:.1em;color:var(--muted)}.build-side-control>div{height:44px;display:grid;grid-template-columns:repeat(3,1fr);padding:3px;border:1px solid var(--line);background:var(--surface)}.build-side-control button{border:0;background:transparent;color:var(--muted);font:700 8px 'DM Mono';letter-spacing:.04em}.build-side-control button.active{background:var(--selection-bg);color:var(--selection-text)}
.scoreboard{background:var(--contrast);color:var(--on-contrast)}
.score-ring{height:auto!important;background:none!important;--muted:#a8afa4}
.score-ring:after{display:none!important}
.score-ring:after{background:var(--contrast)}
.score-copy p{color:#aeb3aa}
.score-copy>small{color:#d5d8d1}
.score-actions button{color:var(--on-contrast)}
.score-actions>small{max-width:180px;color:#d5d8d1;font:600 7px/1.4 'DM Mono';text-align:center}
.recommend{color:var(--selection-text)!important}
@media(max-width:760px){.prop-filter-row{grid-template-columns:1fr}}
.hero-tools{width:min(840px,58vw)}.props-hero{grid-template-columns:minmax(300px,1fr) minmax(0,840px)}
.slate-toolbar>*{min-width:0}.slate-toolbar :deep(.custom-select),.slate-toolbar :deep(.date-picker),.slate-toolbar :deep(.range-picker),.slate-toolbar :deep(.refresh-control),.slate-toolbar :deep(.refresh-control button){width:100%;min-width:0}
@media(min-width:761px){.slate-toolbar{grid-template-columns:135px minmax(160px,1fr) 105px 110px 135px 110px}}
@media(max-width:1200px){.props-hero{grid-template-columns:1fr}.hero-tools{width:100%}}
@media(max-width:760px){.slate-toolbar{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:460px){.slate-toolbar{grid-template-columns:1fr}.slate-toolbar>:last-child{grid-column:auto}}
.alternate{width:100%;min-height:50px;padding:9px 11px;border:1px solid var(--line);background:var(--surface);color:var(--text);display:flex;align-items:center;gap:10px;text-align:left;cursor:pointer}.alternate:hover:not(:disabled){border-color:var(--accent);background:color-mix(in srgb,var(--accent) 8%,var(--surface))}.alternate svg{width:16px;flex:none;color:var(--accent)}.alternate span,.alternate small,.alternate b{display:block;min-width:0}.alternate small{color:var(--muted);font:700 7px 'DM Mono';letter-spacing:.04em}.alternate b{margin-top:4px;font-size:9px;line-height:1.45}.alternate:disabled{opacity:.48;cursor:not-allowed}
.selected-header-actions{display:flex;align-items:center;gap:12px}.selected-header-actions button{min-height:38px;padding:9px 12px;border:1px solid var(--accent);background:var(--selection-bg);color:var(--selection-text);display:flex;align-items:center;gap:7px;font:800 8px 'DM Mono';letter-spacing:.03em;white-space:nowrap}.selected-header-actions button:disabled{opacity:.45;cursor:not-allowed}.selected-header-actions svg{width:14px}@media(max-width:760px){.selected-header-actions{width:100%;align-items:flex-start;flex-direction:column}.selected-header-actions button{width:100%;justify-content:center}}
.advanced-controls{width:100%;border:1px solid var(--line);background:var(--surface)}.advanced-controls summary{height:42px;padding:0 13px;display:flex;align-items:center;justify-content:space-between;gap:12px;cursor:pointer;list-style:none}.advanced-controls summary::-webkit-details-marker{display:none}.advanced-controls summary span{font:800 8px 'DM Mono';letter-spacing:.08em}.advanced-controls summary b{color:var(--muted);font-size:9px;text-transform:uppercase}.advanced-grid{padding:10px;border-top:1px solid var(--line);display:grid;grid-template-columns:140px 170px minmax(220px,1fr) 220px;gap:8px;align-items:end}.advanced-grid>*{min-width:0}.advanced-grid :deep(.custom-select){width:100%;min-width:0}.advanced-grid :deep(.custom-select .trigger>span){flex:1 1 auto;max-width:none}.prop-market-filter,.strongest-summary{grid-column:3/5}.rotation-control{grid-column:1/3}.build-side-control{grid-column:3/5}.strongest-summary>span{display:block;margin-bottom:6px;font:500 7px 'DM Mono';letter-spacing:.1em;color:var(--muted)}.strongest-summary>p{min-height:44px;margin:0;padding:9px 11px;border:1px solid var(--line);background:var(--surface);color:var(--text);font:700 8px/1.55 'DM Mono'}.reset-rotation{grid-column:1/-1;justify-self:end;padding:7px 10px;border:1px solid var(--line);background:var(--surface-2);color:var(--muted);font:800 7px 'DM Mono';letter-spacing:.04em}
.prop-side-preferences{grid-column:1/-1;border:1px solid var(--line);background:var(--surface-2)}.prop-side-preferences>header{min-height:36px;padding:8px 10px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:12px}.prop-side-preferences>header span{font:800 8px 'DM Mono';letter-spacing:.08em}.prop-side-preferences>header small{color:var(--muted);font:700 7px 'DM Mono';text-transform:uppercase}.prop-side-list{max-height:224px;overflow:auto;padding:7px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.prop-side-row{min-height:50px;padding:7px 8px;border:1px solid var(--line);background:var(--surface);display:grid;grid-template-columns:minmax(0,1fr) 184px;gap:8px;align-items:center}.prop-side-row>span{min-width:0}.prop-side-row b,.prop-side-row small{display:block}.prop-side-row b{font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.prop-side-row small{margin-top:3px;color:var(--muted);font-size:7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.prop-side-row>div{height:32px;padding:3px;border:1px solid var(--line);display:grid;grid-template-columns:repeat(4,1fr)}.prop-side-row button{border:0;background:transparent;color:var(--muted);font:800 7px 'DM Mono'}.prop-side-row button.active{background:var(--selection-bg);color:var(--selection-text)}
.card-style{display:grid;grid-template-columns:1fr 1fr;padding:3px;border:1px solid #ffffff35}.card-style button{padding:8px!important;border:0!important;background:transparent!important;color:#d5d8d1!important;font-size:8px!important}.card-style button.active{background:var(--accent)!important;color:var(--selection-text)!important}.leg-actions{display:grid;grid-template-columns:1fr 1fr;gap:7px}.leg-actions button{min-width:0;padding:9px 10px;border:1px solid var(--line);background:var(--surface);color:var(--text);display:flex;align-items:center;gap:8px;text-align:left}.leg-actions button:disabled{opacity:.42}.leg-actions svg{width:14px;color:var(--accent);flex:none}.leg-actions span,.leg-actions small,.leg-actions b{display:block;min-width:0}.leg-actions small{font:800 7px 'DM Mono';color:var(--muted)}.leg-actions b{margin-top:3px;font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media(min-width:761px){.slate-toolbar{grid-template-columns:135px minmax(160px,1fr) 105px 135px 110px}}
@media(max-width:900px) and (min-width:761px){.advanced-grid{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.advanced-grid>.prop-market-filter,.advanced-grid>.strongest-summary{grid-column:1/-1}.advanced-grid>.rotation-control,.advanced-grid>.build-side-control{grid-column:auto}.prop-side-list{grid-template-columns:1fr}}
@media(max-width:760px){.advanced-grid{grid-template-columns:1fr}.advanced-grid>*{grid-column:auto!important}.leg-actions{grid-template-columns:1fr}.advanced-controls summary b{max-width:65%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.prop-side-list{grid-template-columns:1fr}.prop-side-row{grid-template-columns:minmax(0,1fr) 176px}}
.props-page :is(.market-control>span,.market-control a,.seg button,.refresh,.score-copy>small,.score-metrics small,.score-actions button,.score-actions>small,.selected-line small,.board-note span,.board-note p,.game-time,.team small,.versus,.game-selection small,.open-props,.modal-matchup small,.modal-toolbar p,.player small,.player em,.sides button small,.player-card footer,.selected-card footer,.market-notice,.alternate small,.alternate b,.selected-header-actions button,.advanced-controls summary span,.advanced-controls summary b,.strongest-summary>span,.strongest-summary>p,.reset-rotation,.prop-side-preferences>header span,.prop-side-preferences>header small,.prop-side-row b,.prop-side-row small,.prop-side-row button,.card-style button,.leg-actions small,.leg-actions b,.build-side-control>span,.build-side-control button){font-size:12px!important}.props-page :is(.game-card,.alternate,.selected-header-actions button,.prop-side-row>div,.leg-actions button,.build-side-control>div){min-height:46px}.props-page .advanced-controls summary{min-height:54px;height:auto}.props-page .prop-side-row{min-height:72px}.props-page .score-copy p{font-size:13px!important}
</style>
