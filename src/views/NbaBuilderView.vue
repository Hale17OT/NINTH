<script setup>
import { computed, onMounted, ref } from "vue";
import {
  AlertTriangle,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
} from "lucide-vue-next";
import {
  AnimatePresence,
  LayoutGroup,
  motion,
  useReducedMotion,
} from "motion-v";
import SportIdentity from "../components/identity/SportIdentity.vue";
import UnifiedBuilderHero from "../components/builder/UnifiedBuilderHero.vue";
import UnifiedBuilderScore from "../components/builder/UnifiedBuilderScore.vue";
import CustomSelect from "../components/ui/CustomSelect.vue";
import { sentenceCase } from "../domain/sports";
import { api } from "../services/api";

const status = ref(null);
const games = ref([]);
const loading = ref(true);
const error = ref("");
const marketMode = ref("moneyline");
const reduced = useReducedMotion();
const models = computed(() => status.value?.models || []);
const scheduled = computed(() =>
  games.value.filter((row) => row.status !== "Completed"),
);
const marketOptions = [
  { value: "moneyline", label: "MONEYLINE" },
  { value: "totals", label: "TOTALS" },
];
const evidenceOptions = [{ value: "audit", label: "Chronological audit required" }];
const targetOptions = [{ value: 5, label: "5 legs" }];
const load = async () => {
  loading.value = true;
  error.value = "";
  try {
    const [state, slate] = await Promise.all([
      api.sportDirectory("basketball", "status"),
      api.sportDirectory("basketball", "games"),
    ]);
    status.value = state;
    games.value = slate.items || [];
  } catch (caught) {
    error.value =
      caught?.message || "The NBA builder workspace could not be loaded.";
  } finally {
    loading.value = false;
  }
};
onMounted(load);
</script>

<template>
  <div class="unified-builder nba-builder">
    <UnifiedBuilderHero
      eyebrow="NINTH / NBA BUILDER"
      title="Build from"
      accent="possession truth."
      description="The NBA workspace now follows MLB’s compact card-building hierarchy while retaining a hard evidence lock until exact-event moneyline and total-points forecasts are exported."
    >
      <div class="builder-segment">
        <small>MODEL</small>
        <div>
          <button
            v-for="option in marketOptions"
            :key="option.value"
            :class="{ active: marketMode === option.value }"
            @click="marketMode = option.value"
          >
            {{ option.label }}
          </button>
        </div>
      </div>
      <div class="builder-control-bar">
        <CustomSelect model-value="audit" label="Evidence" :options="evidenceOptions" disabled />
        <CustomSelect :model-value="5" label="Target legs" :options="targetOptions" disabled />
        <button class="builder-refresh" :disabled="loading" @click="load">
          <RefreshCw :class="{ spin: loading }" /> REFRESH
        </button>
      </div>
    </UnifiedBuilderHero>

    <UnifiedBuilderScore
      :available="false"
      :selected="0"
      :target="5"
      :average="0"
      title="Automatic NBA card locked"
      description="The model artifacts exist, but Build Best stays unavailable until predictions are bound to exact game IDs and pass recent chronological evaluation."
      detail="No standings-derived favorite or synthetic total is substituted for a missing point-in-time forecast."
      fourth-label="EVIDENCE"
      fourth-value="REQUIRED"
    >
      <template #actions
        ><button class="primary" disabled>
          <LockKeyhole /> BUILD BEST LOCKED</button
        ><button :disabled="loading" @click="load">
          <RefreshCw :class="{ spin: loading }" /> REFRESH BOARD
        </button></template
      >
    </UnifiedBuilderScore>

    <section class="builder-model-strip">
      <article
        v-for="model in models"
        :key="model.market"
        :class="{ ready: model.promotion?.passed }"
      >
        <span>{{ sentenceCase(model.market) }}</span
        ><b>{{
          model.promotion?.passed ? "EVIDENCE PASSED" : "MORE EVIDENCE REQUIRED"
        }}</b
        ><small
          >BRIER
          {{
            model.metrics?.brier != null
              ? Number(model.metrics.brier).toFixed(4)
              : "—"
          }}
          · MODEL PERFORMANCE</small
        >
      </article>
      <article v-if="!models.length">
        <span>NBA model audit</span><b>ARTIFACT PENDING</b
        ><small>No scored NBA model artifact was returned.</small>
      </article>
    </section>

    <section class="builder-board-note">
      <span
        ><i></i>{{ scheduled.length }} CURRENT NBA GAMES · 0 ELIGIBLE
        LINES</span
      >
      <p>
        The schedule is operational. Selection controls unlock automatically
        only after the exact-event prediction exporter and live promotion gate
        both pass.
      </p>
    </section>

    <section class="builder-day">
      <header>
        <div>
          <span class="eyebrow">CURRENT NBA BOARD</span>
          <h2>{{ scheduled.length }} scheduled games</h2>
        </div>
        <small>PROJECTIONS LOCKED</small>
      </header>
      <div v-if="loading" class="builder-state">
        <RefreshCw class="spin" /><b>Joining the NBA slate and audit state</b>
        <p>Loading scheduled games, model artifacts and release eligibility.</p>
      </div>
      <div v-else-if="error" class="builder-state">
        <AlertTriangle /><b>NBA board unavailable</b>
        <p>{{ error }}</p>
      </div>
      <div v-else-if="!scheduled.length" class="builder-state">
        <ShieldCheck /><b>No NBA fixture is currently open</b>
        <p>The builder will populate from the next schedule sync.</p>
      </div>
      <LayoutGroup v-else id="nba-builder"
        ><motion.div layout class="builder-card-grid"
          ><AnimatePresence mode="popLayout"
            ><motion.article
              v-for="game in scheduled"
              :key="game.id"
              layout
              class="builder-choice-card nba-locked-card"
              :initial="reduced ? false : { opacity: 0, y: 12 }"
              :animate="{ opacity: 1, y: 0 }"
              :exit="reduced ? undefined : { opacity: 0, scale: 0.98 }"
              :while-hover="reduced ? undefined : { y: -2 }"
            >
              <div class="builder-card-meta">
                <span>{{ game.date }} · {{ game.time }}</span
                ><strong>PROJECTION EXPORT PENDING</strong>
              </div>
              <div class="builder-matchup">
                <div class="builder-team">
                  <SportIdentity :identity="game.away" :size="38" /><span
                    ><small>AWAY</small><b>{{ game.away?.name }}</b></span
                  >
                </div>
                <i class="builder-versus">AT</i>
                <div class="builder-team home">
                  <SportIdentity :identity="game.home" :size="38" /><span
                    ><small>HOME</small><b>{{ game.home?.name }}</b></span
                  >
                </div>
              </div>
              <div class="builder-market-label">
                {{ marketMode === "moneyline" ? "Moneyline" : "Total points"
                }}<span>NBA</span>
              </div>
              <button class="builder-selection" disabled>
                <span
                  ><small>EXACT-EVENT FORECAST REQUIRED</small
                  ><b>No synthetic selection</b></span
                ><strong>—</strong><LockKeyhole />
              </button>
              <footer class="builder-card-footer">
                <span>{{ game.venue || "Venue pending" }}</span
                ><b>MODEL FORECAST ONLY</b>
              </footer>
            </motion.article></AnimatePresence
          ></motion.div
        ></LayoutGroup
      >
    </section>
  </div>
</template>

<style scoped>
.nba-builder {
  --sport: #f6b945;
}
.builder-control-bar {
  grid-template-columns: minmax(210px, 1fr) minmax(130px, 0.65fr) auto;
}
.nba-locked-card {
  background: var(--surface);
}
.nba-locked-card .builder-selection {
  opacity: 0.62;
}
@media (max-width: 700px) {
  .builder-control-bar {
    grid-template-columns: 1fr 1fr;
  }
  .builder-refresh {
    grid-column: 1/-1;
  }
}
@media (max-width: 480px) {
  .builder-control-bar {
    grid-template-columns: 1fr;
  }
  .builder-refresh {
    grid-column: 1;
  }
}
</style>
