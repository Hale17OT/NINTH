<script setup>
import { computed, onMounted, ref, watch } from "vue";
import {
  AlertTriangle,
  CheckCircle2,
  Search,
  ShieldCheck,
  TrendingUp,
} from "lucide-vue-next";
import { api } from "../services/api";
import PlayerHeadshot from "../components/player/PlayerHeadshot.vue";
import LoadingState from "../components/ui/LoadingState.vue";
import CustomSelect from "../components/ui/CustomSelect.vue";

const payload = ref(null);
const loading = ref(true);
const error = ref("");
const query = ref("");
const minimumSamples = ref(3);
const market = ref("all");
const evidence = ref("all");
const page = ref(1);
const pageSize = 50;
const minimumSampleOptions = [
  { value: 1, label: "All records" },
  { value: 3, label: "3+ settled" },
  { value: 5, label: "5+ settled" },
  { value: 10, label: "10+ established" },
];
const evidenceOptions = [
  { value: "all", label: "All maturity levels" },
  { value: "established", label: "Established" },
  { value: "developing", label: "Developing" },
  { value: "early", label: "Early" },
];

const marketOptions = computed(() => {
  const seen = new Map();
  for (const row of payload.value?.records || [])
    seen.set(`${row.kind}:${row.prop}`, `${row.kind} · ${row.label}`);
  return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
});
const marketSelectOptions = computed(() => [
  { value: "all", label: "All player props" },
  ...marketOptions.value.map(([value, label]) => ({ value, label })),
]);
const records = computed(() =>
  (payload.value?.records || []).filter((row) => {
    if (row.samples < minimumSamples.value) return false;
    if (market.value !== "all" && `${row.kind}:${row.prop}` !== market.value)
      return false;
    if (evidence.value !== "all" && row.evidence !== evidence.value)
      return false;
    return (
      !query.value.trim() ||
      row.player_name.toLowerCase().includes(query.value.trim().toLowerCase())
    );
  }),
);
const proven = computed(() =>
  records.value.filter((row) => row.evidence === "established"),
);
const pageCount = computed(() =>
  Math.max(1, Math.ceil(records.value.length / pageSize)),
);
const visibleRecords = computed(() =>
  records.value.slice((page.value - 1) * pageSize, page.value * pageSize),
);
const headline = computed(() => proven.value[0] || records.value[0]);
const totalSettled = computed(() =>
  records.value.reduce((sum, row) => sum + row.samples, 0),
);
const totalCorrect = computed(() =>
  records.value.reduce((sum, row) => sum + row.correct, 0),
);
const percent = (value) => `${(Number(value || 0) * 100).toFixed(1)}%`;
const lineLabel = (row) =>
  `${row.side.toUpperCase()} ${Number(row.line).toFixed(1)}`;
watch([query, minimumSamples, market, evidence], () => {
  page.value = 1;
});

onMounted(async () => {
  try {
    payload.value = await api.playerPropGuarantees(1);
  } catch (caught) {
    error.value = caught?.message || "Guarantee history could not be loaded.";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="guarantee-page">
    <section class="guarantee-hero">
      <div>
        <span class="eyebrow">MLB / GUARANTEE LIST</span>
        <h1>What has kept<br /><i>being right?</i></h1>
        <p>
          Every row follows the same player, role, statistic, side and exact
          line from the first immutable prediction through the latest settled
          game.
        </p>
      </div>
      <aside v-if="headline">
        <span>TOP SAMPLE-AWARE RECORD</span
        ><PlayerHeadshot
          :player="{ id: headline.player_id, name: headline.player_name }"
          :size="68"
        /><b>{{ headline.player_name }}</b
        ><strong class="mono">{{ percent(headline.accuracy) }}</strong
        ><small
          >{{ headline.correct }}/{{ headline.samples }} · {{ headline.label }}
          {{ lineLabel(headline) }}</small
        >
      </aside>
    </section>

    <LoadingState
      v-if="loading"
      label="Calculating historical consistency"
      detail="Reading every immutable, settled player-prop prediction."
    />
    <section v-else-if="error" class="error-state">
      <AlertTriangle /><b>Guarantee history unavailable</b>
      <p>{{ error }}</p>
    </section>
    <template v-else>
      <section class="method-warning">
        <ShieldCheck />
        <div>
          <b>Historical consistency, not future certainty.</b>
          <p>
            The rank uses an 80% Wilson lower bound and penalizes records until
            ten settled observations. A 3/3 start cannot outrank an established
            17/20 record merely because it shows 100%.
          </p>
        </div>
      </section>
      <section class="summary-strip">
        <article>
          <small>VISIBLE EXACT PICKS</small
          ><b class="mono">{{ records.length }}</b>
        </article>
        <article>
          <small>ESTABLISHED RECORDS</small
          ><b class="mono">{{ proven.length }}</b>
        </article>
        <article>
          <small>SETTLED PREDICTIONS</small
          ><b class="mono">{{ totalSettled }}</b>
        </article>
        <article>
          <small>VISIBLE HIT RATE</small
          ><b class="mono">{{
            totalSettled ? percent(totalCorrect / totalSettled) : "—"
          }}</b>
        </article>
      </section>

      <section class="controls">
        <label
          ><span>FIND PLAYER</span>
          <div>
            <Search :size="15" /><input
              v-model="query"
              placeholder="Player name"
            /></div
        ></label>
        <CustomSelect
          v-model="minimumSamples"
          label="Minimum evidence"
          :options="minimumSampleOptions"
        />
        <CustomSelect
          v-model="market"
          label="Market"
          :options="marketSelectOptions"
          searchable
        />
        <CustomSelect
          v-model="evidence"
          label="Evidence"
          :options="evidenceOptions"
        />
      </section>

      <section class="guarantee-list">
        <header>
          <span>PLAYER / EXACT PICK</span><span>ALL-TIME</span
          ><span>RECENT 10</span><span>STREAK</span><span>LOWER BOUND</span
          ><span>EVIDENCE</span>
        </header>
        <article
          v-for="row in visibleRecords"
          :key="`${row.player_id}:${row.kind}:${row.prop}:${row.side}:${row.line}`"
        >
          <div class="player">
            <PlayerHeadshot
              :player="{ id: row.player_id, name: row.player_name }"
              :size="44"
            /><span
              ><b>{{ row.player_name }}</b
              ><small
                >{{ row.kind.toUpperCase() }} · {{ row.label.toUpperCase() }} ·
                {{ lineLabel(row) }}</small
              ></span
            >
          </div>
          <div class="record" data-label="ALL-TIME">
            <strong class="mono">{{ percent(row.accuracy) }}</strong
            ><small
              >{{ row.correct }} / {{ row.samples }} · Brier
              {{ row.brier_score.toFixed(3) }}</small
            >
          </div>
          <div data-label="RECENT 10">
            <b class="mono"
              >{{ row.recent_10_correct }}/{{ row.recent_10_samples }}</b
            ><small>LAST {{ row.recent_10_samples }}</small>
          </div>
          <div data-label="STREAK">
            <b class="mono">{{ row.current_streak }}</b
            ><small>CURRENT WINS</small>
          </div>
          <div data-label="LOWER BOUND">
            <b class="mono">{{ percent(row.wilson_lower) }}</b
            ><small>SAMPLE-AWARE</small>
          </div>
          <em :class="row.evidence"
            ><CheckCircle2
              v-if="row.evidence === 'established'"
              :size="13"
            /><TrendingUp v-else :size="13" />{{
              row.evidence.toUpperCase()
            }}</em
          >
        </article>
        <div v-if="!records.length" class="empty">
          No exact player-prop record matches these filters.
        </div>
      </section>
      <nav
        v-if="pageCount > 1"
        class="pagination"
        aria-label="Guarantee list pages"
      >
        <button :disabled="page === 1" @click="page--">PREVIOUS</button
        ><span
          >PAGE {{ page }} / {{ pageCount }} · {{ records.length }} EXACT
          PICKS</span
        ><button :disabled="page === pageCount" @click="page++">NEXT</button>
      </nav>
      <footer>
        {{ payload.method }} · Updated
        {{
          payload.updated_at
            ? new Date(payload.updated_at).toLocaleString()
            : "pending"
        }}
      </footer>
    </template>
  </div>
</template>

<style scoped>
.guarantee-page {
  display: grid;
  padding-bottom: 45px;
}
.guarantee-hero {
  min-height: 440px;
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 55px;
  align-items: center;
  border-bottom: 1px solid var(--line);
}
h1 {
  margin: 18px 0 25px;
  font-size: clamp(62px, 8vw, 108px);
  line-height: 0.82;
  letter-spacing: -0.085em;
}
h1 i {
  font-style: normal;
  color: var(--accent);
}
.guarantee-hero > div > p {
  max-width: 680px;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.7;
}
.guarantee-hero aside {
  min-height: 295px;
  padding: 25px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  background: var(--contrast);
  color: var(--on-contrast);
  border-top: 4px solid var(--accent);
}
.guarantee-hero aside > span {
  font: 700 12px "DM Mono";
  color: var(--accent);
}
.guarantee-hero aside > .headshot {
  margin: 28px 0 12px;
}
.guarantee-hero aside > b {
  font-size: 18px;
}
.guarantee-hero aside > strong {
  margin-top: auto;
  font-size: 48px;
  letter-spacing: -0.08em;
  color: var(--accent);
}
.guarantee-hero aside > small {
  font: 600 12px "DM Mono";
  color: #aeb4aa;
}
.method-warning {
  margin: 24px 0;
  display: flex;
  gap: 13px;
  padding: 16px;
  border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--line));
  background: color-mix(in srgb, var(--accent) 7%, var(--surface));
}
.method-warning svg {
  color: var(--acid);
  flex: none;
}
.method-warning b {
  font-size: 14px;
}
.method-warning p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}
.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--line);
  border: 1px solid var(--line);
}
.summary-strip article {
  padding: 18px;
  background: var(--surface);
  display: grid;
  gap: 8px;
}
.summary-strip small,
.controls > label > span {
  font: 700 11px "DM Mono";
  letter-spacing: 0.07em;
  color: var(--muted);
}
.summary-strip b {
  font-size: 26px;
}
.controls {
  display: grid;
  grid-template-columns: 1.2fr repeat(3, minmax(0, 1fr));
  align-items: end;
  gap: 10px;
  padding: 24px 0 14px;
}
.controls > label {
  display: grid;
  gap: 8px;
}
.controls > label > div {
  height: 48px;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 0 12px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
}
.controls input {
  width: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text);
  font-size: 13px;
}
.guarantee-list {
  border: 1px solid var(--line);
}
.guarantee-list > header,
.guarantee-list > article {
  display: grid;
  grid-template-columns: minmax(280px, 2fr) repeat(
      4,
      minmax(90px, 0.7fr)
    ) minmax(110px, 0.8fr);
  align-items: center;
  gap: 12px;
  padding: 15px 18px;
}
.guarantee-list > header {
  background: var(--contrast);
  color: #9ba297;
  font: 700 12px "DM Mono";
  letter-spacing: 0.08em;
}
.guarantee-list > article {
  min-height: 88px;
  border-bottom: 1px solid var(--line);
}
.guarantee-list > article:last-of-type {
  border: 0;
}
.guarantee-list > article:hover {
  background: var(--wash);
}
.player {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}
.player > span,
.guarantee-list article > div:not(.player) {
  display: grid;
  gap: 4px;
}
.player b {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.player small,
.guarantee-list article > div small {
  font: 600 12px "DM Mono";
  color: var(--muted);
}
.record strong {
  font-size: 22px;
  color: var(--accent);
}
.guarantee-list article > div > b {
  font-size: 15px;
}
.guarantee-list em {
  justify-self: start;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 7px 8px;
  font: 700 12px "DM Mono";
  font-style: normal;
  background: var(--wash);
  color: var(--muted);
}
.guarantee-list em.established {
  background: color-mix(in srgb, var(--accent) 17%, var(--surface));
  color: var(--green);
}
.empty,
.error-state {
  padding: 40px;
  text-align: center;
  color: var(--muted);
}
.error-state {
  margin-top: 30px;
  border: 1px solid var(--line);
}
.error-state b {
  display: block;
  margin: 10px;
  color: var(--text);
}
.pagination {
  display: grid;
  grid-template-columns: 110px 1fr 110px;
  align-items: center;
  gap: 12px;
  padding: 14px 0;
  border-bottom: 1px solid var(--line);
}
.pagination button {
  width: 100%;
  height: 48px;
  padding: 0 12px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  font: 700 11px "DM Mono";
  cursor: pointer;
}
.pagination button:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.pagination span {
  text-align: center;
  font: 700 11px "DM Mono";
  color: var(--muted);
}
footer {
  padding: 18px 0;
  font: 600 11px "DM Mono";
  color: var(--muted);
}
@media (max-width: 1050px) {
  .controls {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .guarantee-list {
    overflow-x: auto;
  }
  .guarantee-list > header,
  .guarantee-list > article {
    min-width: 1000px;
  }
}
@media (max-width: 720px) {
  .guarantee-hero {
    grid-template-columns: 1fr;
    gap: 28px;
    padding: 38px 0;
  }
  .guarantee-hero aside {
    min-height: 250px;
  }
  .summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .summary-strip article {
    min-width: 0;
    padding: 15px;
  }
  .summary-strip small {
    overflow-wrap: anywhere;
  }
  .controls {
    grid-template-columns: 1fr;
  }
  .guarantee-list {
    overflow: visible;
    border: 0;
    display: grid;
    gap: 12px;
  }
  .guarantee-list > header {
    display: none;
  }
  .guarantee-list > article {
    min-width: 0;
    min-height: 0;
    padding: 16px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start;
    gap: 16px 12px;
    border: 1px solid var(--line);
    background: var(--surface);
  }
  .guarantee-list > article:last-of-type {
    border: 1px solid var(--line);
  }
  .guarantee-list .player {
    grid-column: 1/-1;
    padding-bottom: 14px;
    border-bottom: 1px solid var(--line);
  }
  .guarantee-list .player small {
    display: block;
    margin-top: 5px;
    white-space: normal;
    line-height: 1.4;
  }
  .guarantee-list article > div:not(.player) {
    min-width: 0;
    padding-top: 17px;
    position: relative;
  }
  .guarantee-list article > div:not(.player)::before {
    content: attr(data-label);
    position: absolute;
    top: 0;
    color: var(--muted);
    font: 700 9px "DM Mono";
    letter-spacing: 0.07em;
  }
  .guarantee-list .record strong {
    font-size: 20px;
  }
  .guarantee-list em {
    grid-column: 1/-1;
    min-height: 40px;
    justify-content: center;
    justify-self: stretch;
  }
  .pagination {
    grid-template-columns: 1fr 1fr;
  }
  .pagination span {
    grid-column: 1/-1;
    grid-row: 1;
  }
  .pagination button {
    grid-row: 2;
  }
  h1 {
    font-size: clamp(48px, 16vw, 62px);
  }
}
@media (max-width: 380px) {
  .summary-strip {
    grid-template-columns: 1fr;
  }
  .guarantee-list > article {
    grid-template-columns: 1fr;
  }
  .guarantee-list .player,
  .guarantee-list em {
    grid-column: 1;
  }
  .pagination {
    gap: 8px;
  }
}
</style>
