<template>
  <section class="not-found panel">
    <span class="eyebrow">NINTH / 404</span>
    <p class="code mono">404</p>
    <h1>This page is out of play.</h1>
    <p>The address may have changed, or the page may no longer exist.</p>
    <div class="actions">
      <RouterLink to="/">GO HOME</RouterLink>
      <RouterLink to="/schedule">VIEW GAMES</RouterLink>
    </div>
  </section>
</template>

<style scoped>
.not-found {
  min-height: min(620px, calc(100vh - 190px));
  margin-top: 20px;
  padding: clamp(32px, 7vw, 90px);
  display: grid;
  align-content: center;
  justify-items: start;
  background: radial-gradient(circle at 82% 22%, color-mix(in srgb, var(--acid) 24%, transparent), transparent 34%), var(--surface);
}
.code {
  margin: 20px 0 0;
  color: var(--acid);
  font-size: clamp(70px, 15vw, 180px);
  font-weight: 800;
  line-height: .75;
}
h1 {
  max-width: 760px;
  margin: 26px 0 12px;
  font-size: clamp(38px, 6vw, 78px);
  line-height: .92;
  letter-spacing: -.065em;
}
.not-found > p:not(.code) {
  max-width: 520px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.7;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 20px;
}
.actions a {
  min-height: 42px;
  padding: 0 18px;
  display: grid;
  place-items: center;
  border: 1px solid var(--line);
  color: var(--ink);
  font: 700 8px "DM Mono";
  text-decoration: none;
}
.actions a:first-child {
  border-color: var(--ink);
  background: var(--ink);
  color: var(--paper);
}
</style>
