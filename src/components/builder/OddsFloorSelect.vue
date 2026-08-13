<script setup>
import { computed } from "vue";
import CustomSelect from "../ui/CustomSelect.vue";

const props = defineProps({
  modelValue: { type: String, default: "1.50" },
  label: { type: String, default: "Minimum MelBet odds" },
  minimum: { type: Number, default: 1.1 },
  includeAll: { type: Boolean, default: true },
});
defineEmits(["update:modelValue"]);

const options = computed(() => [
  ...(props.includeAll ? [{ value: "all", label: "All odds" }] : []),
  ...[1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.75, 2, 2.5, 3].filter(value => value >= props.minimum).map(value => ({
    value: value.toFixed(2),
    label: `${value.toFixed(2)}+`,
  })),
]);
</script>

<template>
  <CustomSelect
    :model-value="modelValue"
    :label="label"
    :options="options"
    @update:model-value="$emit('update:modelValue', $event)"
  />
</template>
