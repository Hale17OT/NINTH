<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { Check, ChevronDown, X } from "lucide-vue-next";
import { AnimatePresence, motion, useReducedMotion } from "motion-v";
import { useFloatingPanel } from "../../composables/useFloatingPanel";

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  options: { type: Array, default: () => [] },
  label: String,
  placeholder: { type: String, default: "Select options" },
  disabled: Boolean,
});
const emit = defineEmits(["update:modelValue"]);
const root = ref();
const trigger = ref();
const panel = ref();
const open = ref(false);
const reduced = useReducedMotion();
const menuId = `multi-select-${Math.random().toString(36).slice(2)}`;
const { floatingStyle, mobile } = useFloatingPanel({
  open,
  trigger,
  panel,
  minimumWidth: 300,
});
const elementOf = (value) => value?.$el ?? value;
const selected = computed(() => new Set(props.modelValue.map(String)));
const summary = computed(() => {
  if (!props.modelValue.length) return props.placeholder;
  if (props.modelValue.length === props.options.length)
    return `All ${props.options.length} selected`;
  if (props.modelValue.length === 1)
    return (
      props.options.find(
        (option) => String(option.value) === String(props.modelValue[0]),
      )?.label || "1 selected"
    );
  return `${props.modelValue.length} of ${props.options.length} selected`;
});

const close = ({ restoreFocus = false } = {}) => {
  open.value = false;
  if (restoreFocus) nextTick(() => elementOf(trigger.value)?.focus());
};
const toggle = () => {
  if (!props.disabled) open.value = !open.value;
};
const toggleOption = (value) => {
  const next = new Set(props.modelValue.map(String));
  next.has(String(value))
    ? next.delete(String(value))
    : next.add(String(value));
  emit(
    "update:modelValue",
    props.options
      .filter((option) => next.has(String(option.value)))
      .map((option) => option.value),
  );
};
const chooseAll = () =>
  emit(
    "update:modelValue",
    props.options.map((option) => option.value),
  );
const clear = () => emit("update:modelValue", []);
const outside = (event) => {
  const panelElement = elementOf(panel.value);
  if (
    !root.value?.contains(event.target) &&
    !panelElement?.contains(event.target)
  )
    close();
};
const keydown = (event) => {
  if (event.key === "Escape" && open.value) {
    event.preventDefault();
    close({ restoreFocus: true });
  }
};
onMounted(() => document.addEventListener("pointerdown", outside));
onBeforeUnmount(() => document.removeEventListener("pointerdown", outside));
</script>

<template>
  <div
    ref="root"
    class="multi-select"
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
      <span>{{ summary }}</span
      ><small>{{ modelValue.length }}</small
      ><ChevronDown :size="16" />
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
        class="select-menu multi-menu"
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
            <small>CHOOSE OPTIONS</small><b>{{ label || placeholder }}</b>
          </div>
          <button
            type="button"
            aria-label="Close options"
            @click="close({ restoreFocus: true })"
          >
            <X :size="18" />
          </button>
        </header>
        <nav class="select-actions" aria-label="Selection actions">
          <button type="button" @click="chooseAll">SELECT ALL</button>
          <button type="button" @click="clear">CLEAR</button>
          <button type="button" @click="close({ restoreFocus: true })">
            DONE
          </button>
        </nav>
        <div
          class="select-options"
          role="listbox"
          :aria-label="label || placeholder"
          aria-multiselectable="true"
        >
          <motion.button
            v-for="option in options"
            :key="option.value"
            type="button"
            role="option"
            :disabled="option.disabled"
            :aria-selected="selected.has(String(option.value))"
            :class="{ selected: selected.has(String(option.value)) }"
            :while-hover="option.disabled || reduced ? undefined : { x: 2 }"
            :while-press="
              option.disabled || reduced ? undefined : { scale: 0.99 }
            "
            @click="toggleOption(option.value)"
          >
            <span
              ><b>{{ option.label }}</b
              ><small v-if="option.meta">{{ option.meta }}</small></span
            >
            <i
              ><Check v-if="selected.has(String(option.value))" :size="15"
            /></i>
          </motion.button>
          <p v-if="!options.length">No current player markets.</p>
        </div>
      </motion.div>
    </AnimatePresence>
  </Teleport>
</template>

<style scoped>
.multi-select {
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
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
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
  overflow: hidden;
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.trigger > small {
  min-width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  background: var(--wash);
  font: 700 11px "DM Mono";
}
.trigger svg {
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
.select-actions {
  min-height: 48px;
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  border-bottom: 1px solid var(--line);
}
.select-actions button {
  min-height: 44px;
  border: 0;
  border-right: 1px solid var(--line);
  background: transparent;
  color: var(--muted);
  font: 700 10px "DM Mono";
  cursor: pointer;
}
.select-actions button:last-child {
  border-right: 0;
  color: var(--accent);
}
.select-actions button:hover {
  background: var(--wash);
  color: var(--text);
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
  min-height: 50px;
  padding: 9px 11px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.select-options > button:hover {
  background: var(--wash);
}
.select-options > button.selected {
  background: color-mix(in srgb, var(--accent) 14%, var(--surface));
}
.select-options > button:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}
.select-options span,
.select-options b,
.select-options small {
  display: block;
  min-width: 0;
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
.select-options i {
  width: 26px;
  height: 26px;
  flex: none;
  display: grid;
  place-items: center;
  border: 1px solid var(--line);
  background: var(--surface);
}
.select-options > button.selected i {
  border-color: var(--accent);
  background: var(--selection-bg);
  color: var(--selection-text);
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
  .select-actions {
    min-height: 52px;
  }
  .select-actions button {
    min-height: 52px;
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
