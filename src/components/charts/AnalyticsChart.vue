<script setup>
import { computed } from 'vue'
import { Bar, Line } from 'vue-chartjs'
import { BarElement, CategoryScale, Chart as ChartJS, Filler, Legend, LinearScale, LineElement, PointElement, Tooltip } from 'chart.js'
import { useAppStore } from '../../stores/app'

ChartJS.register(BarElement, CategoryScale, Filler, Legend, LinearScale, LineElement, PointElement, Tooltip)
const props = defineProps({
  labels: { type: Array, default: () => [] },
  series: { type: Array, default: () => [] },
  type: { type: String, default: 'line' },
  unit: { type: String, default: '' },
  beginAtZero: Boolean,
  height: { type: Number, default: 280 },
  emptyLabel: { type: String, default: 'No chronological data is available for this view.' },
})
const store = useAppStore()
const palette = ['#d6ff61', '#809fff', '#ff7168', '#36d5b3', '#f6b945']
const labels = computed(() => props.labels.map(value => value == null ? '—' : String(value)))
const cleanSeries = computed(() => props.series.map(row => ({
  ...row,
  values: labels.value.map((_, index) => {
    const value = Number(row?.values?.[index])
    return Number.isFinite(value) ? value : null
  }),
})).filter(row => row.values.some(value => value != null)))
const hasData = computed(() => labels.value.length > 0 && cleanSeries.value.length > 0)
const pointCount = computed(() => labels.value.length)
const data = computed(() => ({ labels: labels.value, datasets: cleanSeries.value.map((row, index) => ({
  label: row.label || `Series ${index + 1}`,
  data: row.values,
  borderColor: row.color || palette[index % palette.length],
  backgroundColor: row.fill === false ? 'transparent' : `${row.color || palette[index % palette.length]}22`,
  fill: props.type === 'line' && row.fill !== false,
  tension: pointCount.value <= 2 ? 0 : .34,
  spanGaps: false,
  borderWidth: 2,
  pointRadius: pointCount.value === 1 ? 5 : pointCount.value > 18 ? 0 : 2.5,
  pointHoverRadius: 6,
  borderRadius: props.type === 'bar' ? 3 : 0,
})) }))
const dark = computed(() => store.theme === 'dark')
const formatValue = value => {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 'Unavailable'
  const absolute = Math.abs(numeric)
  const precision = absolute < 1 ? 3 : absolute < 10 ? 2 : 1
  return `${numeric.toFixed(precision)}${props.unit ? ` ${props.unit}` : ''}`
}
const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const options = computed(() => ({
  responsive: true,
  maintainAspectRatio: false,
  normalized: true,
  resizeDelay: 80,
  animation: reducedMotion() ? false : { duration: 720, easing: 'easeOutQuart' },
  transitions: { active: { animation: { duration: reducedMotion() ? 0 : 180 } }, resize: { animation: { duration: 0 } } },
  interaction: { intersect: false, mode: 'index' },
  plugins: {
    legend: { display: cleanSeries.value.length > 1, align: 'start', labels: { usePointStyle: true, boxWidth: 7, boxHeight: 7, padding: 14, color: dark.value ? '#d7ddd2' : '#34382f', font: { family: 'DM Mono', size: 9 } } },
    tooltip: { enabled: true, displayColors: true, backgroundColor: '#111510', borderColor: '#596154', borderWidth: 1, padding: 11, titleColor: '#f2f1e9', bodyColor: '#d7ddd2', titleFont: { family: 'DM Mono', size: 9 }, bodyFont: { family: 'DM Mono', size: 10 }, callbacks: { label: context => `${context.dataset.label}: ${formatValue(context.raw)}` } },
  },
  scales: {
    x: { grid: { display: false }, ticks: { color: dark.value ? '#9da59a' : '#6e7569', maxRotation: 0, autoSkip: true, maxTicksLimit: pointCount.value > 28 ? 8 : 10, font: { family: 'DM Mono', size: 8 }, callback(value) { const label = this.getLabelForValue(value); return label.length > 13 ? `${label.slice(0, 11)}…` : label } } },
    y: { beginAtZero: props.beginAtZero, grace: pointCount.value === 1 ? '12%' : '5%', grid: { color: dark.value ? 'rgba(235,240,230,.08)' : 'rgba(20,24,18,.08)' }, ticks: { color: dark.value ? '#9da59a' : '#6e7569', maxTicksLimit: 6, font: { family: 'DM Mono', size: 8 } } },
  },
}))
const summary = computed(() => cleanSeries.value.map(row => `${row.label}: ${row.values.filter(value => value != null).length} values`).join('; '))
</script>

<template>
  <div class="chart-shell" :style="{'--chart-height':`${Math.max(180,height)}px`}">
    <div v-if="hasData" class="analytics-chart" role="img" :aria-label="summary">
      <Bar v-if="type==='bar'" :data="data" :options="options"/>
      <Line v-else :data="data" :options="options"/>
    </div>
    <div v-else class="chart-empty"><i></i><b>NO SERIES TO PLOT</b><p>{{ emptyLabel }}</p></div>
  </div>
</template>

<style scoped>
.chart-shell{width:100%;min-width:0;height:var(--chart-height);position:relative}.analytics-chart{width:100%;height:100%;min-width:0;position:relative}.analytics-chart:deep(canvas){display:block!important;width:100%!important;height:100%!important}.chart-empty{height:100%;min-height:180px;display:grid;place-items:center;align-content:center;gap:8px;padding:24px;border:1px dashed var(--line);background:linear-gradient(135deg,color-mix(in srgb,var(--accent) 3%,var(--surface)),var(--surface));text-align:center}.chart-empty i{width:34px;height:1px;background:var(--accent);box-shadow:10px -7px var(--accent),20px 3px var(--accent);transform:skewY(-20deg)}.chart-empty b{margin-top:11px;font:800 8px 'DM Mono';letter-spacing:.08em}.chart-empty p{max-width:330px;margin:0;color:var(--muted);font-size:9px;line-height:1.5}@media(max-width:520px){.chart-shell{height:max(240px,calc(var(--chart-height) * .82))}}
</style>
