<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { Check, ChevronDown } from "lucide-vue-next";

const props = defineProps({ modelValue: { type: Array, default: () => [] }, options: { type: Array, default: () => [] }, label: String, placeholder: { type: String, default: "Select options" } });
const emit = defineEmits(["update:modelValue"]);
const root = ref();
const open = ref(false);
const selected = computed(() => new Set(props.modelValue.map(String)));
const summary = computed(() => {
  if (!props.modelValue.length) return props.placeholder;
  if (props.modelValue.length === props.options.length) return `All ${props.options.length} selected`;
  if (props.modelValue.length === 1) return props.options.find(option => String(option.value) === String(props.modelValue[0]))?.label || "1 selected";
  return `${props.modelValue.length} of ${props.options.length} selected`;
});
const toggleOption = value => {
  const next = new Set(props.modelValue.map(String));
  next.has(String(value)) ? next.delete(String(value)) : next.add(String(value));
  emit("update:modelValue", props.options.filter(option => next.has(String(option.value))).map(option => option.value));
};
const chooseAll = () => emit("update:modelValue", props.options.map(option => option.value));
const clear = () => emit("update:modelValue", []);
const outside = event => { if (!root.value?.contains(event.target)) open.value = false; };
onMounted(() => document.addEventListener("pointerdown", outside));
onBeforeUnmount(() => document.removeEventListener("pointerdown", outside));
</script>

<template>
  <div ref="root" class="multi-select" :class="{ open }"><span v-if="label" class="select-label">{{ label }}</span><button type="button" class="trigger" :aria-expanded="open" aria-haspopup="listbox" @click="open = !open"><span>{{ summary }}</span><small>{{ modelValue.length }}</small><ChevronDown /></button><div v-if="open" class="menu"><header><button type="button" @click="chooseAll">SELECT ALL</button><button type="button" @click="clear">CLEAR</button></header><div class="options" role="listbox" aria-multiselectable="true"><button v-for="option in options" :key="option.value" type="button" role="option" :aria-selected="selected.has(String(option.value))" :class="{ selected: selected.has(String(option.value)) }" @click="toggleOption(option.value)"><span><b>{{ option.label }}</b><small v-if="option.meta">{{ option.meta }}</small></span><i><Check v-if="selected.has(String(option.value))" /></i></button><p v-if="!options.length">No current player markets.</p></div></div></div>
</template>

<style scoped>
.multi-select{position:relative;width:100%}.select-label{display:block;margin-bottom:6px;font:500 7px 'DM Mono';letter-spacing:.1em;color:var(--muted);text-transform:uppercase}.trigger{width:100%;height:44px;display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:9px;padding:0 12px;border:1px solid var(--line);background:var(--surface);color:var(--text);text-align:left}.trigger>span{font-size:10px}.trigger>small{min-width:22px;height:22px;display:grid;place-items:center;background:var(--wash);font:700 8px 'DM Mono'}.trigger svg{width:15px;transition:.15s}.open .trigger{border-color:var(--ink)}.open .trigger svg{transform:rotate(180deg)}.menu{position:absolute;z-index:90;top:calc(100% + 5px);left:0;right:0;border:1px solid var(--ink);background:var(--surface);box-shadow:var(--shadow)}.menu header{display:flex;justify-content:space-between;padding:6px;border-bottom:1px solid var(--line)}.menu header button{padding:7px 9px;border:0;background:transparent;color:var(--muted);font:700 7px 'DM Mono'}.options{max-height:300px;overflow:auto;padding:5px}.options>button{width:100%;min-height:43px;padding:7px 9px;display:flex;align-items:center;justify-content:space-between;gap:10px;border:0;background:transparent;color:var(--text);text-align:left}.options>button:hover{background:var(--wash)}.options>button.selected{background:color-mix(in srgb,var(--accent) 14%,var(--surface))}.options span,.options b,.options small{display:block}.options b{font-size:10px}.options small{margin-top:3px;color:var(--muted);font:7px 'DM Mono'}.options i{width:20px;height:20px;display:grid;place-items:center;border:1px solid var(--line);background:var(--surface)}.options i svg{width:13px}.options>button.selected i{background:var(--selection-bg);color:var(--selection-text);border-color:var(--accent)}.options p{padding:14px;color:var(--muted);font-size:9px}
@media(max-width:600px){.menu{position:fixed;left:13px;right:13px;top:auto;bottom:72px}.options{max-height:50vh}}
</style>
