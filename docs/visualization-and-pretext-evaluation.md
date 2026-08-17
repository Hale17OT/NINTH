# NINTH visualization and Pretext evaluation

## Existing technology

NINTH already depends on Chart.js and vue-chartjs. They remain a good fit for responsive line and bar charts, animated transitions, index tooltips and small multi-series comparisons. Replacing them would add migration cost without solving a current limitation.

The deeper analytics pass adds shared Chart.js-backed `AnalyticsChart` plus lightweight CSS/SVG primitives for probability, relative metric comparison, percentiles and zone-shaped matrices. Custom spatial visuals can therefore be added without forcing every graphic through one library.

## Pretext proof of concept

The isolated experiment is at `experiments/pretext-poc/index.html` and is not linked from product navigation or included in the production entrypoint. It compares the same oversized NINTH heading in native DOM/CSS and Pretext-driven Canvas at responsive widths.

Pretext is technically strong for cached multiline measurement, manual per-line layout, Canvas/SVG annotations, virtualization and collision-aware labeling. Its requirements—`Intl.Segmenter`, Canvas text measurement, a synchronized named font string, and manual semantic duplication—are reasonable for specialized graphics.

## Decision

Do not adopt Pretext for the current DOM hero or ordinary chart labels. Native CSS is more accessible, selectable, maintainable, Vue-native and already responsive. The Canvas version adds lifecycle, DPR, font-load, resize and ARIA duplication code without a visible improvement.

Keep the proof of concept isolated. Re-evaluate Pretext when NINTH builds dense Canvas/SVG pitch-zone annotations, collision-aware map labels, or a virtualized analytical canvas where DOM measurement reflow is a demonstrated performance problem.
