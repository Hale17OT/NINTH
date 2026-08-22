<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-vue-next";
import { useFloatingPanel } from "../../composables/useFloatingPanel";

const props = defineProps({
  modelValue: { type: String, required: true },
  label: String,
});
const emit = defineEmits(["update:modelValue"]);
const root = ref();
const trigger = ref();
const panel = ref();
const open = ref(false);
const { floatingStyle, mobile } = useFloatingPanel({
  open,
  trigger,
  panel,
  minimumWidth: 292,
});
const cursor = ref(new Date(`${props.modelValue}T12:00:00Z`));
const weekdays = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const pad = (value) => String(value).padStart(2, "0");
const iso = (date) =>
  `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
const selectedLabel = computed(() =>
  new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${props.modelValue}T12:00:00Z`)),
);
const monthLabel = computed(() =>
  new Intl.DateTimeFormat("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(cursor.value),
);
const cells = computed(() => {
  const year = cursor.value.getUTCFullYear(),
    month = cursor.value.getUTCMonth(),
    first = new Date(Date.UTC(year, month, 1)),
    count = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  return [
    ...Array(first.getUTCDay()).fill(null),
    ...Array.from(
      { length: count },
      (_, index) => new Date(Date.UTC(year, month, index + 1)),
    ),
  ];
});
watch(
  () => props.modelValue,
  (value) => {
    cursor.value = new Date(`${value}T12:00:00Z`);
  },
);
const toggle = async () => {
  open.value = !open.value;
  await nextTick();
};
const moveMonth = (amount) => {
  cursor.value = new Date(
    Date.UTC(
      cursor.value.getUTCFullYear(),
      cursor.value.getUTCMonth() + amount,
      1,
    ),
  );
};
const choose = (date) => {
  emit("update:modelValue", iso(date));
  open.value = false;
};
const outside = (event) => {
  if (!root.value?.contains(event.target) && !panel.value?.contains(event.target)) open.value = false;
};
onMounted(() => document.addEventListener("pointerdown", outside));
onBeforeUnmount(() => document.removeEventListener("pointerdown", outside));
</script>

<template>
  <div ref="root" class="date-picker">
    <span v-if="label" class="picker-label">{{ label }}</span
    ><button
      ref="trigger"
      type="button"
      class="date-trigger"
      :aria-expanded="open"
      @click="toggle"
    >
      <CalendarDays :size="15" /><b>{{ selectedLabel }}</b
      ><ChevronRight :size="14" />
    </button>
  </div>
  <Teleport to="body">
    <div v-if="open && mobile" class="calendar-backdrop" @pointerdown.self="open = false" />
    <div v-if="open" ref="panel" class="calendar" :class="{ 'is-mobile': mobile }" :style="floatingStyle">
      <header>
        <button
          type="button"
          aria-label="Previous month"
          @click="moveMonth(-1)"
        >
          <ChevronLeft :size="16" /></button
        ><b>{{ monthLabel }}</b
        ><button type="button" aria-label="Next month" @click="moveMonth(1)">
          <ChevronRight :size="16" />
        </button>
      </header>
      <div class="week">
        <span v-for="day in weekdays" :key="day">{{ day }}</span>
      </div>
      <div class="days">
        <span
          v-for="(day, index) in cells"
          :key="index"
          :class="{ empty: !day }"
          ><button
            v-if="day"
            type="button"
            :class="{
              selected: iso(day) === modelValue,
              today: iso(day) === iso(new Date()),
            }"
            @click="choose(day)"
          >
            {{ day.getUTCDate() }}
          </button></span
        >
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.date-picker {
  position: relative;
  min-width: 205px;
}
.picker-label {
  display: block;
  margin-bottom: 8px;
  font: 700 11px "DM Mono";
  letter-spacing: 0.08em;
  color: var(--muted);
  text-transform: uppercase;
}
.date-trigger {
  width: 100%;
  height: 48px;
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 9px;
  padding: 0 12px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.date-trigger b {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.calendar-backdrop{position:fixed;inset:0;z-index:1198;background:rgba(2,4,3,.72);backdrop-filter:blur(3px)}
.calendar {
  position: fixed;
  z-index: 1199;
  padding: 10px;
  border: 1px solid var(--ink);
  background: var(--surface);
  box-shadow: 0 15px 40px rgba(20, 22, 18, 0.15);
}
.calendar header {
  display: grid;
  grid-template-columns: 34px 1fr 34px;
  align-items: center;
  border-bottom: 1px solid var(--line);
  padding-bottom: 8px;
}
.calendar header b {
  text-align: center;
  font-size: 11px;
}
.calendar header button {
  height: 32px;
  border: 0;
  background: transparent;
  display: grid;
  place-items: center;
  cursor: pointer;
}
.week,
.days {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
}
.week span {
  padding: 10px 0 6px;
  text-align: center;
  font: 600 6px "DM Mono";
  color: var(--muted);
}
.days > span {
  height: 36px;
  display: grid;
  place-items: center;
}
.days button {
  width: 32px;
  height: 32px;
  border: 0;
  background: transparent;
  font: 600 9px "DM Mono";
  cursor: pointer;
}
.days button:hover {
  background: var(--wash);
}
.days button.today {
  outline: 1px solid var(--line);
}
.days button.selected {
  background: var(--ink);
  color: var(--accent);
}
@media (max-width: 760px) {
  .date-picker {
    width: 100%;
  }
  .calendar.is-mobile {
    inset: auto 0 0 !important;
    width: auto !important;
    padding: 16px 14px calc(16px + env(safe-area-inset-bottom));
    border-width: 1px 0 0;
    border-radius: 18px 18px 0 0;
  }
  .calendar header button {
    width: 44px;
    height: 44px;
  }
  .week span {
    font-size: 9px;
  }
  .days > span {
    height: 44px;
  }
  .days button {
    width: 40px;
    height: 40px;
    font-size: 11px;
  }
}
</style>
