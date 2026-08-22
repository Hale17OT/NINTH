<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { Check, ChevronDown, Search, X } from "lucide-vue-next";
import { AnimatePresence, motion, useReducedMotion } from "motion-v";
import { useFloatingPanel } from "../../composables/useFloatingPanel";

const props = defineProps({
  modelValue: [String, Number],
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: "Select" },
  searchable: Boolean,
  disabled: Boolean,
  label: String,
});
const emit = defineEmits(["update:modelValue", "change"]);
const root = ref();
const trigger = ref();
const panel = ref();
const searchInput = ref();
const open = ref(false);
const query = ref("");
const active = ref(0);
const reduced = useReducedMotion();
const menuId = `select-${Math.random().toString(36).slice(2)}`;
const { floatingStyle, mobile } = useFloatingPanel({ open, trigger, panel });
const elementOf = (value) => value?.$el ?? value;

const selected = computed(() =>
  props.options.find(
    (option) => String(option.value) === String(props.modelValue),
  ),
);
const filtered = computed(() => {
  const term = query.value.toLowerCase().trim();
  return term
    ? props.options.filter((option) =>
        `${option.label} ${option.meta || ""}`.toLowerCase().includes(term),
      )
    : props.options;
});

const close = ({ restoreFocus = false } = {}) => {
  if (!open.value) return;
  open.value = false;
  query.value = "";
  if (restoreFocus) nextTick(() => elementOf(trigger.value)?.focus());
};
const toggle = async () => {
  if (props.disabled) return;
  if (open.value) close();
  else open.value = true;
  active.value = Math.max(
    0,
    filtered.value.findIndex(
      (option) => String(option.value) === String(props.modelValue),
    ),
  );
  if (open.value && props.searchable)
    await nextTick(() => searchInput.value?.focus());
};
const choose = (option) => {
  if (option.disabled) return;
  emit("update:modelValue", option.value);
  emit("change", option.value);
  close({ restoreFocus: true });
};
const keydown = (event) => {
  if (!open.value && ["ArrowDown", "Enter", " "].includes(event.key)) {
    event.preventDefault();
    toggle();
    return;
  }
  if (!open.value) return;
  if (event.key === "Escape") {
    event.preventDefault();
    close({ restoreFocus: true });
  }
  if (event.key === "ArrowDown") {
    event.preventDefault();
    active.value = Math.min(filtered.value.length - 1, active.value + 1);
  }
  if (event.key === "ArrowUp") {
    event.preventDefault();
    active.value = Math.max(0, active.value - 1);
  }
  if (event.key === "Enter" && filtered.value[active.value]) {
    event.preventDefault();
    choose(filtered.value[active.value]);
  }
};
const outside = (event) => {
  const panelElement = elementOf(panel.value);
  if (
    !root.value?.contains(event.target) &&
    !panelElement?.contains(event.target)
  )
    close();
};
onMounted(() => document.addEventListener("pointerdown", outside));
onBeforeUnmount(() => document.removeEventListener("pointerdown", outside));
</script>

<template>
  <div
    ref="root"
    class="custom-select"
    :class="{ open, disabled }"
    @keydown="keydown"
  >
    <span v-if="label" class="select-label">{{ label }}</span>
    <motion.button
      ref="trigger"
      type="button"
      class="trigger"
      :disabled="disabled"
      :aria-label="label || placeholder"
      :aria-controls="menuId"
      :aria-expanded="open"
      aria-haspopup="listbox"
      :while-hover="disabled || reduced ? undefined : { y: -1 }"
      :while-press="disabled || reduced ? undefined : { scale: 0.985 }"
      @click="toggle"
    >
      <span>{{ selected?.label || placeholder }}</span>
      <small v-if="selected?.meta">{{ selected.meta }}</small>
      <ChevronDown :size="16" />
    </motion.button>
  </div>

  <Teleport to="body">
    <AnimatePresence>
      <motion.div
        v-if="open && mobile"
        class="select-backdrop"
        :initial="reduced ? false : { opacity: 0 }"
        :animate="{ opacity: 1 }"
        :exit="reduced ? undefined : { opacity: 0 }"
        @pointerdown.self="close({ restoreFocus: true })"
      />
    </AnimatePresence>
    <AnimatePresence>
      <motion.div
        v-if="open"
        :id="menuId"
        ref="panel"
        class="select-menu"
        :class="{ 'is-mobile': mobile }"
        :style="floatingStyle"
        :initial="
          reduced
            ? false
            : mobile
              ? { opacity: 0, y: 28 }
              : { opacity: 0, y: -7, scale: 0.985 }
        "
        :animate="{ opacity: 1, y: 0, scale: 1 }"
        :exit="
          reduced
            ? undefined
            : mobile
              ? { opacity: 0, y: 22 }
              : { opacity: 0, y: -5, scale: 0.99 }
        "
        :transition="{ type: 'spring', stiffness: 420, damping: 35 }"
        @keydown="keydown"
      >
        <header class="select-menu-header">
          <div>
            <small>CHOOSE OPTION</small><b>{{ label || placeholder }}</b>
          </div>
          <button
            type="button"
            aria-label="Close options"
            @click="close({ restoreFocus: true })"
          >
            <X :size="18" />
          </button>
        </header>
        <label v-if="searchable" class="select-search">
          <Search :size="16" />
          <input
            ref="searchInput"
            v-model="query"
            placeholder="Type to filter…"
            @keydown.stop="keydown"
          />
        </label>
        <div
          class="select-options"
          role="listbox"
          :aria-label="label || placeholder"
        >
          <motion.button
            v-for="(option, index) in filtered"
            :key="option.value"
            type="button"
            role="option"
            :disabled="option.disabled"
            :aria-selected="String(option.value) === String(modelValue)"
            :class="{
              active: index === active,
              selected: String(option.value) === String(modelValue),
            }"
            :while-hover="option.disabled || reduced ? undefined : { x: 2 }"
            :while-press="
              option.disabled || reduced ? undefined : { scale: 0.99 }
            "
            @mouseenter="active = index"
            @click="choose(option)"
          >
            <span
              ><b>{{ option.label }}</b
              ><small v-if="option.meta">{{ option.meta }}</small></span
            >
            <Check
              v-if="String(option.value) === String(modelValue)"
              :size="16"
            />
          </motion.button>
          <p v-if="!filtered.length">No matching options.</p>
        </div>
      </motion.div>
    </AnimatePresence>
  </Teleport>
</template>

<style scoped>
.custom-select {
  position: relative;
  width: 100%;
  min-width: 0;
}
.select-label {
  display: block;
  margin-bottom: 8px;
  color: var(--muted);
  font: 700 11px "DM Mono";
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.trigger {
  width: 100%;
  height: 48px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.trigger > span {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.trigger > small {
  min-width: 0;
  max-width: 44%;
  margin-left: auto;
  overflow: hidden;
  color: var(--muted);
  font: 500 11px "DM Mono";
  text-overflow: ellipsis;
  white-space: nowrap;
}
.trigger svg {
  flex: none;
  transition: 0.2s var(--ease-emphasized);
}
.open .trigger {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 35%, transparent);
}
.open .trigger svg {
  transform: rotate(180deg);
}
.trigger:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.select-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1198;
  background: rgba(2, 4, 3, 0.72);
  backdrop-filter: blur(3px);
}
.select-menu {
  position: fixed;
  z-index: 1199;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--line-strong);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: 0 22px 70px rgba(0, 0, 0, 0.28);
}
.select-menu-header {
  display: none;
}
.select-search {
  min-height: 48px;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 0 13px;
  border-bottom: 1px solid var(--line);
}
.select-search input {
  width: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text);
  font-size: 14px;
}
.select-options {
  min-height: 0;
  max-height: inherit;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 6px;
}
.select-options > button {
  width: 100%;
  min-height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 9px;
  padding: 9px 11px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.select-options > button.active {
  background: var(--wash);
}
.select-options > button.selected {
  background: var(--selection-bg);
  color: var(--selection-text);
}
.select-options > button:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}
.select-options span {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.select-options b {
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.select-options small {
  margin-top: 4px;
  color: var(--muted);
  font: 500 11px "DM Mono";
}
.select-options > button.selected small {
  color: color-mix(in srgb, var(--selection-text) 70%, transparent);
}
.select-options p {
  padding: 14px;
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}
@media (max-width: 760px) {
  .select-menu.is-mobile {
    inset: auto 0 0 !important;
    width: auto !important;
    max-height: min(76dvh, 620px) !important;
    border-width: 1px 0 0;
    border-radius: 18px 18px 0 0;
    padding-bottom: env(safe-area-inset-bottom);
  }
  .select-menu-header {
    min-height: 66px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--line);
  }
  .select-menu-header > div {
    min-width: 0;
    display: grid;
    gap: 3px;
  }
  .select-menu-header small {
    color: var(--accent);
    font: 700 10px "DM Mono";
    letter-spacing: 0.08em;
  }
  .select-menu-header b {
    overflow: hidden;
    font-size: 15px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .select-menu-header button {
    width: 44px;
    height: 44px;
    flex: none;
    display: grid;
    place-items: center;
    border: 1px solid var(--line);
    background: var(--surface-2);
    color: var(--text);
  }
  .select-search {
    min-height: 52px;
    margin: 10px 12px 4px;
    border: 1px solid var(--line);
    border-radius: 8px;
  }
  .select-options {
    padding: 8px 12px 12px;
  }
  .select-options > button {
    min-height: 52px;
    padding: 11px 12px;
  }
  .select-options b {
    font-size: 14px;
  }
}
</style>
