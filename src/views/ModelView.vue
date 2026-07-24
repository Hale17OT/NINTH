<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api } from "../services/api";
import {
  ArrowUpRight,
  BrainCircuit,
  ChevronLeft,
  ChevronRight,
  Database,
  ShieldCheck,
} from "lucide-vue-next";
import TeamLogo from "../components/team/TeamLogo.vue";
import PlayerHeadshot from "../components/player/PlayerHeadshot.vue";
import CustomDatePicker from "../components/ui/CustomDatePicker.vue";
import CustomMultiSelect from "../components/ui/CustomMultiSelect.vue";

const emptyLedger = () => ({
  games: [],
  evaluated: 0,
  correct: 0,
  accuracy: null,
  page: 1,
  total_pages: 1,
});
const report = ref();
const ledger = ref(emptyLedger());
const daily = ref(emptyLedger());
const totalsLedger = ref(emptyLedger());
const totalsDaily = ref(emptyLedger());
const propsLedger = ref(emptyLedger());
const propsDaily = ref(emptyLedger());
const selectedDate = ref(new Date().toISOString().slice(0, 10));
const totalsSelectedDate = ref(new Date().toISOString().slice(0, 10));
const propsSelectedDate = ref(new Date().toISOString().slice(0, 10));
const dailyPropTypes = ref([]);
const finishedPropTypes = ref([]);
const page = ref(1);
const totalsPage = ref(1);
const propsPage = ref(1);
const loading = ref(true);
const error = ref("");
let refreshTimer;
let propsFilterInitialized = false;

const loadReport = async () => {
  const payload = await api.model();
  report.value = payload;
  if (!propsFilterInitialized) {
    const allPropTypes = Object.values(
      payload?.player_props_model?.models || {},
    ).map((item) => `${item.kind}:${item.prop}`);
    dailyPropTypes.value = [...allPropTypes];
    finishedPropTypes.value = [...allPropTypes];
    propsFilterInitialized = true;
  }
};
const loadLedger = async () => {
  ledger.value = await api.modelResults("", page.value, 10);
  page.value = ledger.value.page;
};
const loadDaily = async () => {
  daily.value = await api.modelResults(selectedDate.value, 1, 50);
};
const loadTotalsLedger = async () => {
  totalsLedger.value = await api.modelResults("", totalsPage.value, 10, "totals");
  totalsPage.value = totalsLedger.value.page;
};
const loadTotalsDaily = async () => {
  totalsDaily.value = await api.modelResults(totalsSelectedDate.value, 1, 50, "totals");
};
const loadPropsLedger = async () => {
  propsLedger.value = await api.modelResults(
    "", propsPage.value, 10, "player_props",
    propsFilterInitialized ? finishedPropTypes.value : undefined,
  );
  propsPage.value = propsLedger.value.page;
};
const loadPropsDaily = async () => {
  propsDaily.value = await api.modelResults(
    propsSelectedDate.value, 1, 50, "player_props",
    propsFilterInitialized ? dailyPropTypes.value : undefined,
  );
};
const load = async () => {
  error.value = "";
  try {
    await Promise.all([loadReport(), loadLedger(), loadTotalsLedger(), loadPropsLedger()]);
    await Promise.all([loadDaily(), loadTotalsDaily(), loadPropsDaily()]);
  } catch (caught) {
    error.value = caught?.message || "The model report could not be loaded.";
  } finally {
    loading.value = false;
  }
};
const changePage = async (value) => {
  page.value = value;
  await loadLedger();
};
const changeTotalsPage = async (value) => {
  totalsPage.value = value;
  await loadTotalsLedger();
};
const changePropsPage = async (value) => {
  propsPage.value = value;
  await loadPropsLedger();
};

onMounted(() => {
  load();
  refreshTimer = window.setInterval(load, 60000);
});
onBeforeUnmount(() => window.clearInterval(refreshTimer));
watch(selectedDate, () =>
  loadDaily().catch((caught) => {
    error.value = caught?.message || "Daily results could not be loaded.";
  }),
);
watch(totalsSelectedDate, () =>
  loadTotalsDaily().catch((caught) => {
    error.value = caught?.message || "Daily totals results could not be loaded.";
  }),
);
watch(propsSelectedDate, () =>
  loadPropsDaily().catch((caught) => {
    error.value = caught?.message || "Daily player-prop results could not be loaded.";
  }),
);
watch(dailyPropTypes, () => {
  if (!propsFilterInitialized) return;
  loadPropsDaily().catch((caught) => {
    error.value =
      caught?.message || "Filtered daily player-prop results could not be loaded.";
  });
});
watch(finishedPropTypes, () => {
  if (!propsFilterInitialized) return;
  propsPage.value = 1;
  loadPropsLedger().catch((caught) => {
    error.value =
      caught?.message || "Filtered finished player-prop results could not be loaded.";
  });
});

const tiers = computed(() =>
  (report.value?.selective_accuracy || []).filter(
    (tier) => tier.minimum_probability <= 0.75,
  ),
);
const parlayRates = computed(
  () => report.value?.slip_calibration?.per_leg || [],
);
const totalsReport = computed(() => report.value?.totals_model || null);
const totalsBrier = computed(() =>
  Number(totalsReport.value?.unseen_2025_2026?.mean_brier || 0),
);
const totalsBaselineBrier = computed(() =>
  Number(
    totalsReport.value?.unseen_baseline?.mean_brier ||
      totalsReport.value?.incumbent_unseen_brier ||
      0,
  ),
);
const totalsBrierSkill = computed(() => {
  const explicit = Number(totalsReport.value?.unseen_brier_skill);
  if (Number.isFinite(explicit)) return explicit;
  return totalsBaselineBrier.value > 0
    ? (totalsBaselineBrier.value - totalsBrier.value) /
        totalsBaselineBrier.value
    : 0;
});
const totalsVersion = computed(() => {
  const match = String(totalsReport.value?.model || "").match(/_v(\d+)$/i);
  return match ? `V${match[1]}` : "CURRENT";
});
const playerPropsReport = computed(() => report.value?.player_props_model || null);
const allPlayerPropModels = computed(() =>
  Object.values(playerPropsReport.value?.models || {}),
);
const playerPropOptions = computed(() =>
  allPlayerPropModels.value.map((item) => ({
    value: `${item.kind}:${item.prop}`,
    label: `${item.kind === "pitcher" ? "Pitcher" : "Batter"} · ${item.prop.replaceAll("_", " ")}`,
    meta: "Training audit and deployed results",
  })),
);
const playerPropModels = allPlayerPropModels;
const playerPropSkill = computed(() => playerPropModels.value.length ? playerPropModels.value.reduce((total, item) => total + Number(item.brier_skill_vs_climatology || 0), 0) / playerPropModels.value.length : 0);
const pageNumbers = computed(() => {
  const total = ledger.value.total_pages || 1;
  const length = Math.min(7, total);
  const start = Math.max(1, Math.min(page.value - 3, total - length + 1));
  return Array.from({ length }, (_, index) => start + index);
});
const totalsPageNumbers = computed(() => {
  const total = totalsLedger.value.total_pages || 1;
  const length = Math.min(7, total);
  const start = Math.max(1, Math.min(totalsPage.value - 3, total - length + 1));
  return Array.from({ length }, (_, index) => start + index);
});
const propsPageNumbers = computed(() => {
  const total = propsLedger.value.total_pages || 1;
  const length = Math.min(7, total);
  const start = Math.max(1, Math.min(propsPage.value - 3, total - length + 1));
  return Array.from({ length }, (_, index) => start + index);
});
const propActual = (result) => `${Number(result.actual).toFixed(Number(result.actual) % 1 ? 1 : 0)} ${result.label}`;
const gameDate = (value) =>
  new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "America/New_York",
  }).format(new Date(value));
const fullDate = (value) =>
  new Intl.DateTimeFormat("en-US", {
    dateStyle: "long",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
const lockTime = (value) =>
  new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
    timeZoneName: "short",
  }).format(new Date(value));
const groups = [
  {
    title: "Team baseline",
    summary:
      "Long-horizon quality and whether the record is supported by runs scored and allowed.",
    features: [
      "Elo rating",
      "Season win percentage",
      "Pythagorean expected record",
    ],
  },
  {
    title: "Recent results",
    summary:
      "Several windows prevent one hot or cold week from dominating the forecast.",
    features: [
      "Last 5 win rate",
      "Last 10 win rate",
      "Last 20 win rate",
      "Last 10 run margin",
      "Last 20 run margin",
    ],
  },
  {
    title: "Rolling production",
    summary:
      "Current offensive output and run prevention, measured before the matchup.",
    features: ["Rolling runs scored", "Rolling runs allowed"],
  },
  {
    title: "Schedule and venue",
    summary:
      "Situational performance without using sportsbook or market information.",
    features: ["Home/road split", "Team rest difference"],
  },
  {
    title: "Starter fundamentals",
    summary: "Traditional starter quality, track record and readiness.",
    features: ["Starter Elo", "Starter rest", "Starter ERA", "Starter WHIP"],
  },
  {
    title: "Starter Statcast",
    summary: "Leakage-safe pitch and contact quality from prior starts only.",
    features: [
      "Expected wOBA allowed",
      "Hard-hit suppression",
      "Barrel suppression",
      "Whiff rate",
      "Strikeout-minus-walk rate",
      "Velocity profile",
      "Sample reliability",
      "Prior-start history depth",
    ],
  },
  {
    title: "Lineup and bullpen",
    summary: "Confirmed or projected personnel plus recent relief workload.",
    features: ["Lineup OPS composition", "Bullpen pitches · prior 3 days"],
  },
  {
    title: "Game environment",
    summary: "Official venue forecast at expected game time.",
    features: ["Temperature", "Wind speed"],
  },
  {
    title: "Input reliability",
    summary:
      "Tells the model how much official matchup context is actually available.",
    features: ["Live context availability"],
  },
];
</script>
<style scoped>
.model-page .model-grid {
  grid-template-columns: 1.15fr 0.85fr;
  align-items: start;
}
.factor-intro {
  font-size: 9px;
  line-height: 1.55;
  color: var(--muted);
  margin: 0 0 14px;
}
.factor-intro b {
  color: var(--text);
}
.model-grid .feature-group {
  padding: 14px 0;
}
.feature-group header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.feature-group header b {
  font-size: 11px;
}
.feature-group header em {
  font: 600 6px "DM Mono";
  font-style: normal;
  color: var(--acid);
}
.model-grid .feature-group p {
  font-size: 8px;
  line-height: 1.45;
  margin: 5px 0 8px;
}
.factor-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.factor-tags span {
  padding: 4px 6px;
  background: var(--wash);
  font: 600 6px "DM Mono";
  color: var(--text);
}
@media (max-width: 850px) {
  .model-page .model-grid {
    grid-template-columns: 1fr;
  }
}
</style>
<style scoped>
.totals-audit{display:grid;gap:1px;border:1px solid var(--line);background:var(--line)}.totals-audit>header{display:flex;justify-content:space-between;gap:28px;align-items:end;padding:27px;background:var(--contrast);color:var(--on-contrast)}.totals-audit h2{max-width:720px;margin:8px 0;font-size:28px}.totals-audit header p{max-width:760px;margin:0;color:var(--muted);font-size:9px;line-height:1.65}.totals-audit header>strong{font-size:40px;color:var(--accent);text-align:right;white-space:nowrap}.totals-audit header>strong small{display:block;margin-top:5px;font:600 7px 'DM Mono';color:var(--muted)}.totals-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line)}.totals-metrics article{display:flex;flex-direction:column;gap:6px;padding:18px;background:var(--surface)}.totals-metrics small,.line-audit small{font:600 7px 'DM Mono';color:var(--muted)}.totals-metrics b{font-size:21px;color:var(--acid)}.totals-metrics span{font-size:8px;color:var(--muted)}.line-audit{display:grid;grid-template-columns:repeat(6,1fr);gap:1px;background:var(--line)}.line-audit span{display:flex;flex-direction:column;gap:6px;padding:12px;background:var(--raised)}.line-audit b{font-size:12px}.totals-note{padding:14px 18px;margin:0;background:var(--surface);font-size:8px;line-height:1.6;color:var(--muted)}@media(max-width:850px){.totals-audit>header{align-items:flex-start;flex-direction:column}.totals-audit header>strong{text-align:left}.totals-metrics{grid-template-columns:repeat(2,1fr)}.line-audit{grid-template-columns:repeat(3,1fr)}}@media(max-width:520px){.totals-metrics{grid-template-columns:1fr}.line-audit{grid-template-columns:repeat(2,1fr)}}
</style>
<template>
  <div v-if="report" class="model-page">
    <section class="model-hero">
      <div>
        <span class="eyebrow">NINTH / MODEL LAB</span>
        <h1>Know what the<br /><i>model knows.</i></h1>
        <p>
          A transparent view of training data, real out-of-sample results,
          confidence tiers, and the stricter recent-season audit.
        </p>
      </div>
      <div class="hero-score">
        <BrainCircuit :size="28" /><small>WALK-FORWARD ACCURACY</small
        ><strong class="mono"
          >{{ (report.walk_forward.accuracy * 100).toFixed(1) }}%</strong
        ><span
          >2022–{{ report.training_through_season }} ·
          {{ report.walk_forward.games.toLocaleString() }} picks</span
        >
      </div>
    </section>
    <section class="model-stats">
      <div>
        <Database /><span>TRAINING GAMES</span
        ><strong class="mono">{{
          report.deployment_training_games.toLocaleString()
        }}</strong>
      </div>
      <div>
        <ShieldCheck /><span>RECENT OUTER TEST</span
        ><strong class="mono"
          >{{
            ((report.recent_outer?.accuracy || report.accuracy) * 100).toFixed(
              1,
            )
          }}%</strong
        >
      </div>
      <div>
        <BrainCircuit /><span>QUALIFIED ACCURACY</span
        ><strong class="mono"
          >{{ ((report.qualified_accuracy || 0) * 100).toFixed(1) }}%</strong
        >
      </div>
      <div>
        <BrainCircuit /><span>BRIER SCORE</span
        ><strong class="mono">{{
          report.walk_forward.brier_score.toFixed(3)
        }}</strong>
      </div>
    </section>
    <section v-if="totalsReport" class="totals-audit">
      <header><div><span class="eyebrow">TOTAL RUNS MODEL · {{ totalsVersion }}</span><h2>A full threshold forecast, audited without market prices.</h2><p>The totals model forecasts six run thresholds, selects its architecture on older rolling-origin folds, and reserves 2025–2026 as the final temporal audit.</p></div><strong class="mono">{{ (totalsBrierSkill*100).toFixed(2) }}%<small>BRIER IMPROVEMENT VS PRIOR MODEL</small></strong></header>
      <div class="totals-metrics"><article><small>UNSEEN BRIER</small><b class="mono">{{ totalsBrier.toFixed(5) }}</b><span>Prior production {{ totalsBaselineBrier.toFixed(5) }}</span></article><article><small>SELECTED-LINE ACCURACY</small><b class="mono">{{ (totalsReport.unseen_recommended.accuracy*100).toFixed(1) }}%</b><span>{{ totalsReport.unseen_recommended.games.toLocaleString() }} unseen games</span></article><article><small>SELECTED-LINE BRIER</small><b class="mono">{{ totalsReport.unseen_recommended.brier_score.toFixed(5) }}</b><span>Mean probability {{ (totalsReport.unseen_recommended.mean_probability*100).toFixed(1) }}%</span></article><article><small>TRAINING GAMES</small><b class="mono">{{ totalsReport.training_games.toLocaleString() }}</b><span>Through {{ totalsReport.trained_through_date }}</span></article></div>
      <div class="line-audit"><span v-for="line in totalsReport.lines" :key="line"><small>OVER / UNDER {{ line }}</small><b class="mono">{{ totalsReport.unseen_2025_2026.per_line[String(line)].toFixed(5) }}</b></span></div>
      <p class="totals-note">A {{ (totalsReport.unseen_recommended.accuracy*100).toFixed(1) }}% selected-line hit rate is not a profitability claim: the model chooses its own run threshold and intentionally has no sportsbook line or price. Mixed-card confidence remains an independence estimate until a separate joint calibration passes its promotion gate.</p>
    </section>
    <section v-if="playerPropsReport" class="props-audit">
      <header><div><span class="eyebrow">PLAYER PROP MODELS · V{{ playerPropsReport.version }}</span><h2>Every threshold earns its probability.</h2><p>Official player-game box scores are replayed chronologically. Models train through 2023, calibrate on 2024, and report the untouched 2025–26 Brier result shown below.</p></div><strong class="mono">{{ (playerPropSkill * 100).toFixed(2) }}%<small>MEAN BRIER SKILL VS LINE CLIMATOLOGY</small></strong></header>
      <div class="props-table"><article v-for="item in playerPropModels" :key="`${item.kind}:${item.prop}`"><span><small>{{ item.kind.toUpperCase() }}</small><b>{{ item.prop.replaceAll('_', ' ') }}</b></span><span><small>UNSEEN BRIER</small><b class="mono">{{ item.unseen.brier.toFixed(5) }}</b></span><span><small>BASELINE</small><b class="mono">{{ item.climatology.brier.toFixed(5) }}</b></span><span><small>BRIER SKILL</small><b class="mono" :class="{ positive: item.brier_skill_vs_climatology > 0 }">{{ (item.brier_skill_vs_climatology * 100).toFixed(2) }}%</b></span><span><small>60%+ COVERAGE / HIT</small><b class="mono">{{ (item.confidence_60.coverage * 100).toFixed(1) }}% / {{ item.confidence_60.accuracy == null ? '—' : `${(item.confidence_60.accuracy * 100).toFixed(1)}%` }}</b></span></article></div>
      <p class="props-note">Low raw Brier scores for rare outcomes such as home runs and steals are not compared directly with high-frequency props. Brier skill measures each model against its own line-specific baseline; negative skill is a warning, not hidden.</p>
    </section>
    <section class="model-grid">
      <article>
        <header>
          <span class="eyebrow">SELECTIVITY CURVE</span>
          <h2>Confidence earns its name.</h2>
          <p>
            Accuracy rises when the model is allowed to pass on weak matchups.
            Coverage shows how rarely each threshold occurs.
          </p>
        </header>
        <div class="tier" v-for="tier in tiers" :key="tier.minimum_probability">
          <div>
            <b class="mono"
              >{{ Math.round(tier.minimum_probability * 100) }}%+</b
            ><span>displayed win probability</span>
          </div>
          <strong class="mono">{{ (tier.accuracy * 100).toFixed(1) }}%</strong>
          <div class="bar">
            <i :style="{ width: `${tier.accuracy * 100}%` }"></i>
          </div>
          <small
            >{{ tier.games.toLocaleString() }} games /
            {{ (tier.coverage * 100).toFixed(1) }}% coverage</small
          >
        </div>
      </article>
      <aside>
        <span class="eyebrow">ALL DEPLOYED SIGNALS</span>
        <h2>What moves a projection.</h2>
        <p class="factor-intro">
          <b
            >{{
              report.selected_features?.length || report.features?.length || 29
            }}
            model features</b
          >
          grouped below. The matchup page shows only the strongest contributors
          for that specific game.
        </p>
        <div
          v-for="(group, index) in groups"
          :key="group.title"
          class="feature-group"
        >
          <span class="mono">{{ String(index + 1).padStart(2, "0") }}</span>
          <div>
            <header>
              <b>{{ group.title }}</b
              ><em>{{ group.features.length }} SIGNALS</em>
            </header>
            <p>{{ group.summary }}</p>
            <div class="factor-tags">
              <span v-for="feature in group.features" :key="feature">{{
                feature
              }}</span>
            </div>
          </div>
        </div>
      </aside>
    </section>
    <section v-if="parlayRates.length" class="parlay-audit">
      <header>
        <div>
          <span class="eyebrow">OUT-OF-FOLD PARLAY RESULTS</span>
          <h2>How often every leg actually hit.</h2>
          <p>
            Each card takes that day's highest-probability model picks. A card
            counts as a hit only when every selected leg won. These are
            historical baseball-only results, not sportsbook returns.
          </p>
        </div>
        <span class="parlay-window mono"
          >2022–{{ report.training_through_season }} WALK-FORWARD</span
        >
      </header>
      <div class="parlay-grid">
        <article v-for="item in parlayRates" :key="item.legs">
          <div class="parlay-label">
            <b>{{ item.legs }} LEG</b
            ><span>{{ item.hits }} / {{ item.samples }} cards</span>
          </div>
          <strong class="mono"
            >{{ (item.observed_all_correct * 100).toFixed(1) }}%</strong
          >
          <div class="parlay-meter">
            <i :style="{ width: `${item.observed_all_correct * 100}%` }"></i>
          </div>
          <footer>
            <span>2025–26</span>
            <b class="mono"
              >{{ (item.recent_observed_all_correct * 100).toFixed(1) }}%</b
            >
            <small>{{ item.recent_hits }} / {{ item.recent_samples }}</small>
          </footer>
        </article>
      </div>
      <p class="parlay-note">
        The thin range beneath each percentage is the observed hit indicator;
        sample counts matter more as parlays get longer and successful cards
        become rare.
      </p>
    </section>
    <section class="prediction-ledger daily-audit">
      <header>
        <div>
          <span class="eyebrow">DAILY MODEL AUDIT</span>
          <h2>How did NINTH do that day?</h2>
          <p>
            Choose any MLB date to review every eligible locked forecast, the
            official winner, and the complete daily hit rate.
          </p>
        </div>
        <div class="daily-controls">
          <CustomDatePicker v-model="selectedDate" label="Evaluation date" />
          <div class="ledger-score">
            <small>{{ fullDate(selectedDate).toUpperCase() }}</small>
            <strong class="mono">{{
              daily.accuracy === null
                ? "—"
                : `${(daily.accuracy * 100).toFixed(1)}%`
            }}</strong>
            <span
              >{{ daily.correct }} correct ·
              {{ daily.evaluated - daily.correct }} missed ·
              {{ daily.evaluated }} evaluated</span
            >
          </div>
        </div>
      </header>
      <div v-if="daily.daily_parlays?.length" class="daily-parlays">
        <div class="daily-parlay-heading">
          <div>
            <span class="eyebrow">TOP PICKS BY CARD SIZE</span
            ><b>Daily parlay outcomes</b>
          </div>
          <small>Percentage is legs won; the card hits only at 100%.</small>
        </div>
        <div class="daily-parlay-grid">
          <article
            v-for="card in daily.daily_parlays"
            :key="card.legs"
            :class="{ hit: card.all_correct }"
          >
            <header>
              <b>{{ card.legs }} LEG</b
              ><em>{{ card.all_correct ? "HIT" : "MISSED" }}</em>
            </header>
            <strong class="mono"
              >{{ (card.leg_accuracy * 100).toFixed(0) }}%</strong
            >
            <div><i :style="{ width: `${card.leg_accuracy * 100}%` }"></i></div>
            <small>{{ card.correct_legs }} of {{ card.legs }} picks won</small>
          </article>
        </div>
      </div>
      <div v-if="daily.games.length" class="result-list">
        <RouterLink
          v-for="result in daily.games"
          :key="result.game_id"
          :to="`/games/${result.game_id}`"
          class="result-row"
        >
          <time class="mono">{{ lockTime(result.starts_at) }}</time>
          <div class="result-match">
            <span
              ><TeamLogo :team="result.away" :size="34" /><b>{{
                result.away.name
              }}</b></span
            >
            <strong class="mono"
              >{{ result.away_score }}–{{ result.home_score }}</strong
            >
            <span class="home"
              ><b>{{ result.home.name }}</b
              ><TeamLogo :team="result.home" :size="34"
            /></span>
          </div>
          <div class="result-pick">
            <small>LOCKED MODEL PICK</small>
            <b
              >{{ result.projected_team.name }} ·
              {{
                (
                  (result.projected_side === "home"
                    ? result.home_win_probability
                    : result.away_win_probability) * 100
                ).toFixed(1)
              }}%</b
            >
            <span>Snapshot {{ lockTime(result.snapshot_at) }}</span>
          </div>
          <em :class="result.correct ? 'correct' : 'missed'">{{
            result.correct ? "CORRECT" : "MISSED"
          }}</em>
        </RouterLink>
      </div>
      <div v-else class="ledger-empty">
        No eligible finished predictions were found for
        {{ fullDate(selectedDate) }}.
      </div>
    </section>
    <section class="prediction-ledger">
      <header>
        <div>
          <span class="eyebrow">LIVE DEPLOYMENT RECORD</span>
          <h2>Finished predictions.</h2>
          <p>
            Only projections archived before first pitch are eligible. Every
            result is joined to the official MLB final and cannot be rewritten
            afterward.
          </p>
        </div>
        <div class="ledger-score">
          <small>RUNNING ACCURACY</small
          ><strong class="mono">{{
            ledger.accuracy === null
              ? "—"
              : `${(ledger.accuracy * 100).toFixed(1)}%`
          }}</strong
          ><span
            >{{ ledger.correct }} correct /
            {{ ledger.evaluated }} evaluated</span
          >
        </div>
      </header>
      <div v-if="ledger.games.length" class="result-list">
        <RouterLink
          v-for="result in ledger.games"
          :key="result.game_id"
          :to="`/games/${result.game_id}`"
          class="result-row"
          ><time class="mono">{{ gameDate(result.starts_at) }}</time>
          <div class="result-match">
            <span
              ><TeamLogo :team="result.away" :size="34" /><b>{{
                result.away.name
              }}</b></span
            ><strong class="mono"
              >{{ result.away_score }}–{{ result.home_score }}</strong
            ><span class="home"
              ><b>{{ result.home.name }}</b
              ><TeamLogo :team="result.home" :size="34"
            /></span>
          </div>
          <div class="result-pick">
            <small>LOCKED MODEL PICK</small
            ><b
              >{{ result.projected_team.name }} ·
              {{
                (
                  (result.projected_side === "home"
                    ? result.home_win_probability
                    : result.away_win_probability) * 100
                ).toFixed(1)
              }}%</b
            ><span>Snapshot {{ lockTime(result.snapshot_at) }}</span>
          </div>
          <em :class="result.correct ? 'correct' : 'missed'">{{
            result.correct ? "CORRECT" : "MISSED"
          }}</em></RouterLink
        >
      </div>
      <div v-else class="ledger-empty">
        Completed predictions will appear after a game with a valid
        pre-first-pitch snapshot reaches an official final.
      </div>
      <nav
        v-if="ledger.total_pages > 1"
        class="ledger-pagination"
        aria-label="Completed prediction pages"
      >
        <button
          type="button"
          :disabled="page === 1"
          aria-label="Previous results page"
          @click="changePage(page - 1)"
        >
          <ChevronLeft />
        </button>
        <button
          v-for="number in pageNumbers"
          :key="number"
          type="button"
          :class="{ current: page === number }"
          :aria-current="page === number ? 'page' : undefined"
          @click="changePage(number)"
        >
          {{ number }}
        </button>
        <button
          type="button"
          :disabled="page === ledger.total_pages"
          aria-label="Next results page"
          @click="changePage(page + 1)"
        >
          <ChevronRight />
        </button>
      </nav>
      <footer>{{ ledger.snapshot_rule }} · refreshes every 60 seconds</footer>
    </section>
    <section class="prediction-ledger daily-audit totals-ledger">
      <header>
        <div><span class="eyebrow">DAILY TOTAL-RUNS AUDIT</span><h2>How did the run model do that day?</h2><p>Every result uses the last archived Over/Under recommendation before first pitch and the official combined score.</p></div>
        <div class="daily-controls"><CustomDatePicker v-model="totalsSelectedDate" label="Totals evaluation date"/><div class="ledger-score"><small>{{ fullDate(totalsSelectedDate).toUpperCase() }}</small><strong class="mono">{{ totalsDaily.accuracy === null ? '—' : `${(totalsDaily.accuracy*100).toFixed(1)}%` }}</strong><span>{{ totalsDaily.correct }} correct · {{ totalsDaily.evaluated-totalsDaily.correct }} missed · Brier {{ totalsDaily.brier_score == null ? '—' : totalsDaily.brier_score.toFixed(3) }}</span></div></div>
      </header>
      <div v-if="totalsDaily.games.length" class="result-list">
        <RouterLink v-for="result in totalsDaily.games" :key="`total-day-${result.game_id}`" :to="`/games/${result.game_id}`" class="result-row">
          <time class="mono">{{ lockTime(result.starts_at) }}</time>
          <div class="result-match"><span><TeamLogo :team="result.away" :size="34"/><b>{{result.away.name}}</b></span><strong class="mono">{{result.away_score}}–{{result.home_score}}</strong><span class="home"><b>{{result.home.name}}</b><TeamLogo :team="result.home" :size="34"/></span></div>
          <div class="result-pick"><small>LOCKED RUN PICK</small><b>{{result.total_side.toUpperCase()}} {{result.total_line}} · {{(result.total_probability*100).toFixed(1)}}%</b><span>Final total {{result.total_runs}} · Snapshot {{lockTime(result.snapshot_at)}}</span></div>
          <em :class="result.correct?'correct':'missed'">{{result.correct?'CORRECT':'MISSED'}}</em>
        </RouterLink>
      </div>
      <div v-else class="ledger-empty">No eligible locked total-runs predictions were found for {{fullDate(totalsSelectedDate)}}.</div>
    </section>
    <section class="prediction-ledger totals-ledger">
      <header>
        <div><span class="eyebrow">LIVE TOTAL-RUNS RECORD</span><h2>Finished Over/Under predictions.</h2><p>This is deployment performance, separate from the training audit. The probability is scored against the model-selected line.</p></div>
        <div class="ledger-score"><small>RUNNING HIT RATE</small><strong class="mono">{{totalsLedger.accuracy===null?'—':`${(totalsLedger.accuracy*100).toFixed(1)}%`}}</strong><span>{{totalsLedger.correct}} / {{totalsLedger.evaluated}} · Brier {{totalsLedger.brier_score==null?'—':totalsLedger.brier_score.toFixed(3)}}</span></div>
      </header>
      <div v-if="totalsLedger.games.length" class="result-list">
        <RouterLink v-for="result in totalsLedger.games" :key="`total-${result.game_id}`" :to="`/games/${result.game_id}`" class="result-row">
          <time class="mono">{{gameDate(result.starts_at)}}</time>
          <div class="result-match"><span><TeamLogo :team="result.away" :size="34"/><b>{{result.away.name}}</b></span><strong class="mono">{{result.away_score}}–{{result.home_score}}</strong><span class="home"><b>{{result.home.name}}</b><TeamLogo :team="result.home" :size="34"/></span></div>
          <div class="result-pick"><small>LOCKED RUN PICK</small><b>{{result.total_side.toUpperCase()}} {{result.total_line}} · {{(result.total_probability*100).toFixed(1)}}%</b><span>Final total {{result.total_runs}} · Snapshot {{lockTime(result.snapshot_at)}}</span></div>
          <em :class="result.correct?'correct':'missed'">{{result.correct?'CORRECT':'MISSED'}}</em>
        </RouterLink>
      </div>
      <div v-else class="ledger-empty">Completed total-runs predictions will appear after a pre-first-pitch forecast reaches an official final.</div>
      <nav v-if="totalsLedger.total_pages>1" class="ledger-pagination" aria-label="Completed totals prediction pages">
        <button type="button" :disabled="totalsPage===1" @click="changeTotalsPage(totalsPage-1)"><ChevronLeft/></button>
        <button v-for="number in totalsPageNumbers" :key="`total-page-${number}`" type="button" :class="{current:totalsPage===number}" @click="changeTotalsPage(number)">{{number}}</button>
        <button type="button" :disabled="totalsPage===totalsLedger.total_pages" @click="changeTotalsPage(totalsPage+1)"><ChevronRight/></button>
      </nav>
      <footer>{{totalsLedger.snapshot_rule}} · refreshes every 60 seconds</footer>
    </section>
    <section class="prediction-ledger daily-audit props-deployment-ledger">
      <header>
        <div>
          <span class="eyebrow">DAILY PLAYER-PROP AUDIT</span>
          <h2>How did the player models do that day?</h2>
          <p>Each result is the final displayed recommendation locked before first pitch. Players who did not participate and exact-line pushes are voided.</p>
        </div>
        <div class="daily-controls">
          <CustomDatePicker v-model="propsSelectedDate" label="Player props evaluation date"/>
          <CustomMultiSelect v-model="dailyPropTypes" label="Prop statistics" placeholder="No prop statistics selected" :options="playerPropOptions"/>
          <div class="ledger-score">
            <small>{{fullDate(propsSelectedDate).toUpperCase()}}</small>
            <strong class="mono">{{propsDaily.accuracy===null?'—':`${(propsDaily.accuracy*100).toFixed(1)}%`}}</strong>
            <span>{{propsDaily.correct}} correct · {{propsDaily.evaluated-propsDaily.correct}} missed · Brier {{propsDaily.brier_score==null?'—':propsDaily.brier_score.toFixed(3)}}</span>
          </div>
        </div>
      </header>
      <div v-if="propsDaily.prop_breakdown?.length" class="props-deployment-breakdown">
        <article v-for="item in propsDaily.prop_breakdown" :key="`daily-prop-${item.kind}-${item.prop}`">
          <small>{{item.kind.toUpperCase()}} · {{item.label.toUpperCase()}}</small><b class="mono">{{(item.accuracy*100).toFixed(1)}}%</b>
          <span>{{item.correct}} / {{item.evaluated}} · Brier {{item.brier_score.toFixed(3)}}</span>
        </article>
      </div>
      <div v-if="propsDaily.games.length" class="result-list">
        <RouterLink v-for="result in propsDaily.games" :key="`prop-day-${result.game_id}-${result.player_id}-${result.prop}`" :to="`/games/${result.game_id}`" class="result-row prop-result-row">
          <time class="mono">{{lockTime(result.starts_at)}}</time>
          <div class="prop-player"><PlayerHeadshot :player="{id:result.player_id,name:result.player_name}" :size="48"/><span><b>{{result.player_name}}</b><small>{{result.away.name}} AT {{result.home.name}}</small></span></div>
          <div class="result-pick"><small>LOCKED {{result.label.toUpperCase()}}</small><b>{{result.side.toUpperCase()}} {{result.line}} · {{(result.probability*100).toFixed(1)}}%</b><span>Official result {{propActual(result)}} · Snapshot {{lockTime(result.snapshot_at)}}</span></div>
          <em :class="result.correct?'correct':'missed'">{{result.correct?'CORRECT':'MISSED'}}</em>
        </RouterLink>
      </div>
      <div v-else class="ledger-empty">No settled pregame player-prop recommendations were found for {{fullDate(propsSelectedDate)}}.</div>
    </section>
    <section class="prediction-ledger props-deployment-ledger">
      <header>
        <div><span class="eyebrow">LIVE PLAYER-PROP RECORD</span><h2>Finished player-prop predictions.</h2><p>This deployment audit is separate from the 2025–26 training backtest above. Only exact recommendations archived before first pitch are scored.</p></div>
        <div class="prop-record-controls"><CustomMultiSelect v-model="finishedPropTypes" label="Prop statistics" placeholder="No prop statistics selected" :options="playerPropOptions"/><div class="ledger-score"><small>RUNNING HIT RATE</small><strong class="mono">{{propsLedger.accuracy===null?'—':`${(propsLedger.accuracy*100).toFixed(1)}%`}}</strong><span>{{propsLedger.correct}} / {{propsLedger.evaluated}} · Brier {{propsLedger.brier_score==null?'—':propsLedger.brier_score.toFixed(3)}}</span></div></div>
      </header>
      <div v-if="propsLedger.prop_breakdown?.length" class="props-deployment-breakdown">
        <article v-for="item in propsLedger.prop_breakdown" :key="`overall-prop-${item.kind}-${item.prop}`">
          <small>{{item.kind.toUpperCase()}} · {{item.label.toUpperCase()}}</small><b class="mono">{{(item.accuracy*100).toFixed(1)}}%</b>
          <span>{{item.correct}} / {{item.evaluated}} · Brier {{item.brier_score.toFixed(3)}}</span>
        </article>
      </div>
      <div v-if="propsLedger.games.length" class="result-list">
        <RouterLink v-for="result in propsLedger.games" :key="`prop-${result.game_id}-${result.player_id}-${result.prop}`" :to="`/games/${result.game_id}`" class="result-row prop-result-row">
          <time class="mono">{{gameDate(result.starts_at)}}</time>
          <div class="prop-player"><PlayerHeadshot :player="{id:result.player_id,name:result.player_name}" :size="48"/><span><b>{{result.player_name}}</b><small>{{result.away.name}} AT {{result.home.name}}</small></span></div>
          <div class="result-pick"><small>LOCKED {{result.label.toUpperCase()}}</small><b>{{result.side.toUpperCase()}} {{result.line}} · {{(result.probability*100).toFixed(1)}}%</b><span>Official result {{propActual(result)}} · Snapshot {{lockTime(result.snapshot_at)}}</span></div>
          <em :class="result.correct?'correct':'missed'">{{result.correct?'CORRECT':'MISSED'}}</em>
        </RouterLink>
      </div>
      <div v-else class="ledger-empty">The deployment ledger is active. Settled predictions will appear after an archived player-prop slate reaches an official final.</div>
      <nav v-if="propsLedger.total_pages>1" class="ledger-pagination" aria-label="Completed player-prop prediction pages">
        <button type="button" :disabled="propsPage===1" @click="changePropsPage(propsPage-1)"><ChevronLeft/></button>
        <button v-for="number in propsPageNumbers" :key="`prop-page-${number}`" type="button" :class="{current:propsPage===number}" @click="changePropsPage(number)">{{number}}</button>
        <button type="button" :disabled="propsPage===propsLedger.total_pages" @click="changePropsPage(propsPage+1)"><ChevronRight/></button>
      </nav>
      <footer>{{propsLedger.snapshot_rule}} · refreshes every 60 seconds</footer>
    </section>
    <section class="next-step">
      <span class="eyebrow">V4 / CALIBRATED BLEND</span>
      <h2>Probability quality comes first.</h2>
      <p>
        V4 combines the stable capped-run-margin signal with a conservative
        nonlinear challenger and shrinks measured overconfidence. Recent and
        live deployment audits remain visible because this is decision support,
        not a guarantee.
      </p>
      <a
        href="https://baseballsavant.mlb.com/en/statcast_search"
        target="_blank"
        >BASEBALL SAVANT SOURCE <ArrowUpRight :size="14"
      /></a>
    </section>
  </div>
  <div v-else class="state">
    {{ loading ? "LOADING MODEL AUDIT…" : "MODEL REPORT UNAVAILABLE" }}
  </div>
</template>
<style scoped>
.model-page {
  display: grid;
}
.model-hero {
  min-height: 470px;
  display: grid;
  grid-template-columns: 1fr 330px;
  align-items: center;
  gap: 50px;
  border-bottom: 1px solid var(--line);
}
h1 {
  font-size: clamp(56px, 8vw, 110px);
  line-height: 0.84;
  letter-spacing: -0.09em;
  margin: 18px 0 28px;
}
h1 i {
  font-style: normal;
  color: var(--orange);
}
.model-hero p {
  max-width: 620px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--muted);
}
.hero-score {
  height: 310px;
  background: var(--contrast);
  color: var(--on-contrast);
  display: flex;
  flex-direction: column;
  padding: 25px;
}
.hero-score svg {
  color: var(--accent);
  margin-bottom: auto;
}
.hero-score small {
  font: 500 8px "DM Mono";
  color: #979c94;
}
.hero-score strong {
  font-size: 68px;
  letter-spacing: -0.09em;
  color: var(--accent);
  margin: 8px 0;
}
.hero-score span {
  font: 8px "DM Mono";
  color: #979c94;
}
.model-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  border-bottom: 1px solid var(--line);
}
.model-stats > div {
  display: grid;
  padding: 22px;
  border-right: 1px solid var(--line);
}
.model-stats svg {
  width: 16px;
  color: var(--muted);
}
.model-stats span {
  font: 500 8px "DM Mono";
  color: var(--muted);
  margin: 22px 0 8px;
}
.model-stats strong {
  font-size: 26px;
}
.model-grid {
  display: grid;
  grid-template-columns: 1.35fr 0.65fr;
  gap: 45px;
  padding: 48px 0;
  border-bottom: 1px solid var(--line);
}
.model-grid h2,
.next-step h2,
.prediction-ledger h2 {
  font-size: 33px;
  letter-spacing: -0.055em;
  margin: 7px 0 10px;
}
.model-grid header p {
  font-size: 11px;
  color: var(--muted);
  line-height: 1.6;
  max-width: 580px;
}
.tier {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  padding: 16px 0;
  border-top: 1px solid var(--line);
}
.tier > div:first-child {
  display: flex;
  gap: 10px;
  align-items: baseline;
}
.tier > div b {
  font-size: 13px;
}
.tier > div span,
.tier small {
  font-size: 8px;
  color: var(--muted);
}
.tier > strong {
  font-size: 15px;
}
.bar {
  grid-column: 1/-1;
  height: 7px;
  background: var(--wash);
}
.bar i {
  display: block;
  height: 100%;
  background: var(--orange);
}
.feature-group {
  display: grid;
  grid-template-columns: 30px 1fr;
  gap: 8px;
  padding: 16px 0;
  border-top: 1px solid var(--line);
}
.feature-group > span {
  font-size: 8px;
  color: var(--muted);
}
.feature-group b {
  font-size: 11px;
}
.feature-group p {
  font-size: 9px;
  color: var(--muted);
  line-height: 1.5;
  margin: 5px 0;
}
.parlay-audit {
  padding: 48px 0;
  border-bottom: 1px solid var(--line);
}
.parlay-audit > header {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 22px;
}
.parlay-audit h2 {
  font-size: 33px;
  letter-spacing: -0.055em;
  margin: 7px 0 10px;
}
.parlay-audit header p {
  max-width: 680px;
  margin: 0;
  font-size: 10px;
  line-height: 1.6;
  color: var(--muted);
}
.parlay-window {
  padding: 10px 12px;
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 7px;
  white-space: nowrap;
}
.parlay-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  border: 1px solid var(--line);
  background: var(--surface);
}
.parlay-grid article {
  min-width: 0;
  padding: 15px;
  border-right: 1px solid var(--line);
}
.parlay-grid article:last-child {
  border-right: 0;
}
.parlay-label {
  display: grid;
  gap: 4px;
}
.parlay-label b {
  font: 800 8px "DM Mono";
  color: var(--muted);
}
.parlay-label span,
.parlay-grid footer span,
.parlay-grid footer small {
  font-size: 7px;
  color: var(--muted);
}
.parlay-grid article > strong {
  display: block;
  margin: 18px 0 10px;
  font-size: clamp(22px, 2.2vw, 34px);
  letter-spacing: -0.07em;
  color: var(--acid);
}
.parlay-meter {
  height: 5px;
  background: var(--wash);
}
.parlay-meter i {
  display: block;
  height: 100%;
  min-width: 2px;
  background: var(--orange);
}
.parlay-grid footer {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 4px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}
.parlay-grid footer b {
  font-size: 9px;
}
.parlay-grid footer small {
  grid-column: 1 / -1;
}
.parlay-note {
  margin: 10px 0 0;
  font: 7px/1.6 "DM Mono";
  color: var(--muted);
}
.prediction-ledger {
  padding: 48px 0;
  border-bottom: 1px solid var(--line);
}
.prediction-ledger > header {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 30px;
  margin-bottom: 24px;
}
.prediction-ledger header p {
  max-width: 650px;
  margin: 0;
  font-size: 10px;
  line-height: 1.6;
  color: var(--muted);
}
.ledger-score {
  min-width: 220px;
  padding: 15px 17px;
  background: var(--contrast);
  color: var(--on-contrast);
  display: grid;
}
.ledger-score small {
  font: 7px "DM Mono";
  color: #9da39a;
}
.ledger-score strong {
  font-size: 32px;
  color: var(--accent);
  margin: 7px 0 3px;
}
.ledger-score span {
  font: 7px "DM Mono";
  color: #9da39a;
}
.daily-audit {
  background: color-mix(in srgb, var(--accent) 7%, transparent);
  padding-left: 22px;
  padding-right: 22px;
}
.daily-controls {
  display: flex;
  align-items: end;
  gap: 9px;
}
.daily-controls :deep(.date-picker) {
  width: 215px;
}
.daily-controls :deep(.multi-select) {
  width: 250px;
}
.daily-controls .ledger-score {
  min-width: 230px;
}
.prop-record-controls {
  display: flex;
  align-items: end;
  gap: 9px;
}
.prop-record-controls :deep(.multi-select) {
  width: 260px;
}
.daily-parlays {
  margin-bottom: 14px;
  padding: 14px;
  border: 1px solid var(--line);
  background: var(--surface);
}
.daily-parlay-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
.daily-parlay-heading > div {
  display: grid;
  gap: 5px;
}
.daily-parlay-heading b {
  font-size: 12px;
}
.daily-parlay-heading small {
  font-size: 8px;
  color: var(--muted);
}
.daily-parlay-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 6px;
}
.daily-parlay-grid article {
  padding: 10px;
  border: 1px solid var(--line);
  background: var(--wash);
}
.daily-parlay-grid article > header {
  display: flex;
  justify-content: space-between;
  gap: 5px;
}
.daily-parlay-grid header b,
.daily-parlay-grid header em {
  font: 800 7px "DM Mono";
}
.daily-parlay-grid header em {
  color: var(--orange);
  font-style: normal;
}
.daily-parlay-grid article.hit header em,
.daily-parlay-grid article.hit > strong {
  color: var(--acid);
}
.daily-parlay-grid article > strong {
  display: block;
  margin: 12px 0 7px;
  font-size: 21px;
  color: var(--text);
}
.daily-parlay-grid article > div {
  height: 4px;
  background: var(--surface);
}
.daily-parlay-grid article > div i {
  display: block;
  height: 100%;
  background: var(--orange);
}
.daily-parlay-grid article.hit > div i {
  background: var(--acid);
}
.daily-parlay-grid article > small {
  display: block;
  margin-top: 7px;
  font-size: 7px;
  color: var(--muted);
}
.result-list {
  border: 1px solid var(--line);
  background: var(--surface);
}
.result-row {
  min-height: 82px;
  display: grid;
  grid-template-columns: 62px minmax(330px, 1.2fr) minmax(220px, 0.8fr) 85px;
  align-items: center;
  gap: 15px;
  padding: 11px 15px;
  border-bottom: 1px solid var(--line);
  text-decoration: none;
}
.result-row:last-child {
  border-bottom: 0;
}
.result-row:hover {
  background: var(--wash);
}
.result-row time {
  font-size: 8px;
  color: var(--muted);
  text-transform: uppercase;
}
.result-match {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: 10px;
}
.result-match > span {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.result-match > span.home {
  justify-content: flex-end;
  text-align: right;
}
.result-match b {
  font-size: 9px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.result-match > strong {
  font-size: 16px;
}
.result-pick {
  display: grid;
  gap: 3px;
}
.result-pick small {
  font: 6px "DM Mono";
  color: var(--muted);
}
.result-pick b {
  font-size: 10px;
}
.result-pick span {
  font-size: 7px;
  color: var(--muted);
}
.result-row > em {
  justify-self: end;
  padding: 7px 9px;
  border: 1px solid currentColor;
  font: 800 7px "DM Mono";
  font-style: normal;
}
.result-row > em.correct {
  color: var(--acid);
}
.result-row > em.missed {
  color: var(--orange);
}
.ledger-empty {
  padding: 32px;
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 10px;
  text-align: center;
}
.prediction-ledger > footer {
  margin-top: 10px;
  font: 7px "DM Mono";
  color: var(--muted);
}
.ledger-pagination {
  display: flex;
  justify-content: center;
  gap: 5px;
  margin-top: 16px;
}
.ledger-pagination button {
  width: 38px;
  height: 38px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  display: grid;
  place-items: center;
  font: 700 8px "DM Mono";
  cursor: pointer;
}
.ledger-pagination button.current {
  background: var(--ink);
  color: var(--paper);
}
.ledger-pagination button:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.ledger-pagination svg {
  width: 14px;
}
.next-step {
  padding: 55px 0;
  max-width: 900px;
}
.next-step > p {
  font-size: 13px;
  line-height: 1.8;
  color: var(--muted);
}
.next-step a {
  display: inline-flex;
  gap: 7px;
  align-items: center;
  margin-top: 12px;
  padding: 12px;
  background: var(--ink);
  color: var(--paper);
  font: 600 8px "DM Mono";
  text-decoration: none;
}
.state {
  padding: 90px;
  text-align: center;
  font: 9px "DM Mono";
}
@media (max-width: 900px) {
  .parlay-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
  .parlay-grid article:nth-child(4) {
    border-right: 0;
  }
  .parlay-grid article:nth-child(-n + 4) {
    border-bottom: 1px solid var(--line);
  }
  .result-row {
    grid-template-columns: 52px 1fr auto;
  }
  .result-pick {
    grid-column: 2;
  }
  .result-row > em {
    grid-column: 3;
    grid-row: 1/3;
  }
  .result-match {
    grid-template-columns: 1fr auto 1fr;
  }
}
@media (max-width: 850px) {
  .model-hero {
    grid-template-columns: 1fr;
    padding: 40px 0;
  }
  .hero-score {
    height: 250px;
  }
  .model-grid {
    grid-template-columns: 1fr;
  }
  .model-stats {
    grid-template-columns: repeat(2, 1fr);
  }
  .model-stats > div:nth-child(2) {
    border-right: 0;
  }
  .prediction-ledger > header {
    align-items: stretch;
    flex-direction: column;
  }
  .daily-controls {
    align-items: stretch;
    flex-direction: column;
  }
  .daily-controls :deep(.date-picker) {
    width: 100%;
  }
  .daily-controls :deep(.multi-select),
  .prop-record-controls :deep(.multi-select) {
    width: 100%;
  }
  .prop-record-controls {
    align-items: stretch;
    flex-direction: column;
  }
  .daily-parlay-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
  .ledger-score {
    width: 100%;
  }
}
@media (max-width: 600px) {
  .daily-parlay-heading {
    align-items: flex-start;
    flex-direction: column;
  }
  .daily-parlay-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .parlay-audit > header {
    align-items: flex-start;
    flex-direction: column;
  }
  .parlay-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .parlay-grid article:nth-child(odd) {
    border-right: 1px solid var(--line);
  }
  .parlay-grid article:nth-child(even) {
    border-right: 0;
  }
  .parlay-grid article {
    border-bottom: 1px solid var(--line);
  }
  .parlay-grid article:last-child {
    border-bottom: 0;
  }
  .result-row {
    grid-template-columns: 1fr auto;
  }
  .result-row time {
    grid-column: 1;
  }
  .result-match {
    grid-column: 1/-1;
    grid-row: 2;
  }
  .result-pick {
    grid-column: 1;
  }
  .result-row > em {
    grid-column: 2;
    grid-row: 3;
  }
  .result-match b {
    display: none;
  }
}
@media (max-width: 520px) {
  h1 {
    font-size: 56px;
  }
  .model-hero {
    gap: 20px;
  }
  .hero-score strong {
    font-size: 55px;
  }
  .model-stats > div {
    padding: 16px;
  }
  .model-grid {
    padding: 33px 0;
  }
}
.props-audit{border:1px solid var(--line);background:var(--surface)}.props-audit>header{display:flex;justify-content:space-between;align-items:end;gap:24px;padding:27px;background:var(--contrast);color:var(--on-contrast)}.props-audit h2{font-size:28px;margin:8px 0}.props-audit header p{max-width:760px;color:var(--muted);font-size:9px;line-height:1.65}.props-audit header>strong{font-size:38px;color:var(--accent);text-align:right}.props-audit header>strong small{display:block;font:600 7px 'DM Mono';color:var(--muted)}.props-table{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--line)}.props-table article{display:grid;grid-template-columns:1.2fr repeat(4,1fr);gap:10px;padding:14px;background:var(--surface)}.props-table span{min-width:0}.props-table small,.props-table b{display:block}.props-table small{font:600 6px 'DM Mono';color:var(--muted)}.props-table b{font-size:10px;margin-top:4px;text-transform:capitalize}.props-table .positive{color:var(--acid)}.props-note{padding:14px 18px;margin:0;color:var(--muted);font-size:8px;line-height:1.6}@media(max-width:980px){.props-table{grid-template-columns:1fr}}@media(max-width:650px){.props-audit>header{align-items:flex-start;flex-direction:column}.props-audit header>strong{text-align:left}.props-table article{grid-template-columns:repeat(2,1fr)}.props-table article>span:first-child{grid-column:1/-1}}
.props-deployment-breakdown{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:1px;margin-bottom:14px;border:1px solid var(--line);background:var(--line)}.props-deployment-breakdown article{display:grid;gap:5px;padding:13px;background:var(--surface)}.props-deployment-breakdown small{font:700 7px 'DM Mono';color:var(--muted)}.props-deployment-breakdown b{font-size:20px;color:var(--acid)}.props-deployment-breakdown span{font-size:7px;color:var(--muted)}.prop-player{min-width:0;display:flex;align-items:center;gap:11px}.prop-player>span{min-width:0;display:grid;gap:4px}.prop-player b{overflow:hidden;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.prop-player small{overflow:hidden;font:600 7px 'DM Mono';color:var(--muted);text-overflow:ellipsis;white-space:nowrap}@media(max-width:600px){.prop-result-row .prop-player{grid-column:1/-1;grid-row:2}.prop-result-row .result-pick{grid-row:3}.prop-result-row>em{grid-row:3}}
</style>
