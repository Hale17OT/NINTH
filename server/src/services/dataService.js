import { mlbStatsProvider } from "./mlbStatsProvider.js";
import { weatherProvider } from "./weatherProvider.js";
import { oddsProvider } from "./oddsProvider.js";

const aliases = {
  nyy: 147,
  lad: 119,
  atl: 144,
  bal: 110,
  judge: 592450,
  ohtani: 660271,
  trout: 545361,
};
const isoDate = (offset = 0) => {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() + offset);
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
};
const isLive = (status) => /live|progress|delay|warmup/i.test(status || "");
const isFinal = (status) => /final|completed|game over/i.test(status || "");
const num = (value) => Number(value || 0);
const pct = (value) => Number(value || 0);
const initials = (name) =>
  (name || "")
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2);
const resolveId = (value) => String(aliases[value] || value);

function activeRoster(roster = []) {
  const players = roster.map((item) => {
    const groups = Object.fromEntries(
      (item.person?.stats || []).map((group) => [
        group.group?.displayName,
        group.splits?.[0]?.stat || {},
      ]),
    );
    const pitching = groups.pitching || {},
      hitting = groups.hitting || {},
      position = item.position?.abbreviation || "—";
    return {
      id: item.person?.id,
      name: item.person?.fullName,
      number: item.jerseyNumber || item.person?.primaryNumber || "—",
      position,
      positionName: item.position?.name || "Player",
      positionType: item.position?.type || "",
      status: item.status?.description || "Active",
      games: num(hitting.gamesPlayed || pitching.gamesPlayed),
      starts: num(pitching.gamesStarted),
      innings: pitching.inningsPitched,
      ops:
        item.position?.type === "Pitcher" || position === "P"
          ? null
          : hitting.ops,
    };
  });
  const pitchers = players
    .filter(
      (player) => player.positionType === "Pitcher" || player.position === "P",
    )
    .sort((a, b) => b.starts - a.starts || b.games - a.games);
  const rotation = new Set(
    pitchers
      .filter((player) => player.starts > 0)
      .slice(0, 5)
      .map((player) => player.id),
  );
  const hitters = players.filter((player) => !pitchers.includes(player));
  const starting = new Set();
  const take = (test, count = 1) =>
    hitters
      .filter(test)
      .sort((a, b) => b.games - a.games)
      .slice(0, count)
      .forEach((player) => starting.add(player.id));
  take((player) => ["LF", "CF", "RF", "OF"].includes(player.position), 3);
  ["1B", "2B", "3B", "SS"].forEach((position) =>
    take((player) => player.position === position),
  );
  take((player) => player.position === "C");
  take((player) => player.position === "DH");
  return players
    .map((player) => {
      let group = "Bench",
        role = `Reserve ${player.positionName.toLowerCase()}`;
      if (pitchers.includes(player)) {
        group = rotation.has(player.id) ? "Starting rotation" : "Bullpen";
        role =
          group === "Starting rotation" ? "Starting pitcher" : "Relief pitcher";
      } else if (starting.has(player.id)) {
        group = "Starting lineup";
        role = ["LF", "CF", "RF", "OF"].includes(player.position)
          ? "Starting outfield"
          : player.position === "C"
            ? "Starting catcher"
            : player.position === "DH"
              ? "Designated hitter"
              : "Starting infield";
      }
      return { ...player, group, role };
    })
    .sort(
      (a, b) =>
        ["Starting rotation", "Bullpen", "Starting lineup", "Bench"].indexOf(
          a.group,
        ) -
          ["Starting rotation", "Bullpen", "Starting lineup", "Bench"].indexOf(
            b.group,
          ) ||
        b.starts - a.starts ||
        b.games - a.games ||
        a.name.localeCompare(b.name),
    );
}

function timeLabel(value) {
  if (!value) return "TBD";
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/New_York",
    timeZoneName: "short",
  }).format(new Date(value));
}

function weatherLabel(weather) {
  return weather
    ? `${weather.temperature}°F · ${weather.windSpeed} mph ${weather.windDirection}`
    : "Forecast pending";
}

async function normalizeGame(game, includeWeather = true) {
  const detail = game.details || {},
    venue = detail.venue || {};
  let weather = null;
  if (includeWeather === "cached")
    try {
      weather = await weatherProvider.cached(
        venue.latitude,
        venue.longitude,
        game.game_datetime,
      );
    } catch {}
  else if (includeWeather)
    try {
      weather = await weatherProvider.forecast(
        venue.latitude,
        venue.longitude,
        game.game_datetime,
      );
    } catch {}
  const status = game.status || detail.status || "Scheduled",
    awayDetail = detail.away || {},
    homeDetail = detail.home || {};
  const inning = isFinal(status)
    ? "FINAL"
    : /delay|postpon|suspend/i.test(status)
      ? status
      : [game.inning_state, game.current_inning].filter(Boolean).join(" ") ||
        status.toUpperCase();
  return {
    id: String(game.game_id),
    gamePk: game.game_id,
    status,
    inning,
    bases: [false, false, false],
    time: timeLabel(game.game_datetime),
    gameTime: game.game_datetime,
    stadium: game.venue_name || venue.name || "Venue TBD",
    venue,
    weather: weatherLabel(weather),
    weatherData: weather,
    weatherPending: Boolean(
      includeWeather &&
      !weather &&
      venue.latitude != null &&
      venue.longitude != null,
    ),
    away: {
      id: game.away_id,
      name: game.away_name,
      abbr: awayDetail.abbr || game.away_name?.slice(0, 3).toUpperCase(),
      score: num(game.away_score),
      record:
        awayDetail.wins != null
          ? `${awayDetail.wins}-${awayDetail.losses}`
          : null,
    },
    home: {
      id: game.home_id,
      name: game.home_name,
      abbr: homeDetail.abbr || game.home_name?.slice(0, 3).toUpperCase(),
      score: num(game.home_score),
      record:
        homeDetail.wins != null
          ? `${homeDetail.wins}-${homeDetail.losses}`
          : null,
    },
    pitchers: [
      game.away_probable_pitcher || "TBD",
      game.home_probable_pitcher || "TBD",
    ],
    odds: null,
    insight: isLive(status)
      ? `${game.inning_state || ""} ${game.current_inning || ""}`.trim()
      : status,
    source: "MLB-StatsAPI",
  };
}

function matchOdds(game, events) {
  return events.find(
    (event) =>
      event.homeTeam === game.home.name &&
      event.awayTeam === game.away.name &&
      Math.abs(new Date(event.commenceTime) - new Date(game.gameTime)) <
        6 * 60 * 60 * 1000,
  );
}

async function attachOdds(games) {
  if (!oddsProvider.configured()) return games;
  try {
    const response = await oddsProvider.mlbOdds();
    return games.map((game) => {
      const odds = matchOdds(game, response.events);
      return odds
        ? {
            ...game,
            odds,
            oddsSummary: `${game.away.abbr} ${odds.awayMoneyline ?? "—"} · ${game.home.abbr} ${odds.homeMoneyline ?? "—"}`,
          }
        : game;
    });
  } catch (error) {
    return games.map((game) => ({ ...game, oddsError: error.message }));
  }
}

async function providerGames(
  date = isoDate(),
  includeWeather = true,
  includeOdds = true,
) {
  const rawGames = await mlbStatsProvider.games(date);
  const games = await Promise.all(
    rawGames.map((game) =>
      normalizeGame(game, includeWeather ? "cached" : false),
    ),
  );
  if (includeWeather)
    rawGames.forEach((game) => {
      const venue = game.details?.venue || {};
      if (venue.latitude != null && venue.longitude != null)
        weatherProvider
          .forecast(venue.latitude, venue.longitude, game.game_datetime)
          .catch(() => {});
    });
  return includeOdds ? attachOdds(games) : games;
}

function runProgression(innings = []) {
  let away = 0,
    home = 0;
  const values = [0];
  innings.forEach((inning) => {
    away += num(inning.away?.runs);
    home += num(inning.home?.runs);
    values.push(away - home);
  });
  return values.length > 1 ? values : [0, 0];
}

function teamExplorer(teams, type) {
  const byPct = [...teams].sort((a, b) => pct(b.pct) - pct(a.pct));
  const byDiff = [...teams].sort(
    (a, b) => b.run_differential - a.run_differential,
  );
  const byLastTen = [...teams].sort(
    (a, b) => pct(b.last_ten?.pct) - pct(a.last_ten?.pct),
  );
  const source = { provider: "MLB-StatsAPI", season: 2026 };
  if (type === "rankings")
    return {
      source,
      metrics: [
        {
          label: "Best record",
          value: `${byPct[0].abbr} ${byPct[0].wins}-${byPct[0].losses}`,
          delta: `${byPct[0].pct} win pct`,
        },
        {
          label: "Best run differential",
          value: `${byDiff[0].abbr} +${byDiff[0].run_differential}`,
          delta: "Official standings",
        },
        {
          label: "Most runs scored",
          value: [...teams].sort((a, b) => b.runs_scored - a.runs_scored)[0]
            .abbr,
          delta: `${[...teams].sort((a, b) => b.runs_scored - a.runs_scored)[0].runs_scored} runs`,
        },
        {
          label: "Fewest runs allowed",
          value: [...teams].sort((a, b) => a.runs_allowed - b.runs_allowed)[0]
            .abbr,
          delta: `${[...teams].sort((a, b) => a.runs_allowed - b.runs_allowed)[0].runs_allowed} allowed`,
        },
      ],
      featureTitle: "MLB standings leaders",
      features: byPct
        .slice(0, 5)
        .map((team, index) => ({
          name: team.name,
          detail: `${team.wins}-${team.losses} · ${team.run_differential >= 0 ? "+" : ""}${team.run_differential} run diff`,
          value: `#${index + 1}`,
          score: Math.round(pct(team.pct) * 100),
        })),
      chart: byPct.slice(0, 10).map((team) => Math.round(pct(team.pct) * 100)),
      chartLabels: byPct.slice(0, 10).map((team) => team.abbr),
      chartType: "bar",
      chartUnit: "win %",
      insight:
        "Rankings are ordered strictly by official winning percentage; no proprietary weighting is applied.",
      tableTitle: "Official MLB rankings",
      table: {
        headers: ["Rank", "Team", "W", "L", "PCT", "Run diff", "Streak"],
        rows: byPct.map((team, index) => [
          index + 1,
          team.name,
          team.wins,
          team.losses,
          team.pct,
          team.run_differential,
          team.streak || "—",
        ]),
      },
    };
  return {
    source,
    metrics: [
      {
        label: "Hottest last 10",
        value: byLastTen[0].abbr,
        delta: `${byLastTen[0].last_ten?.wins}-${byLastTen[0].last_ten?.losses}`,
      },
      {
        label: "Best run differential",
        value: byDiff[0].abbr,
        delta: `+${byDiff[0].run_differential}`,
      },
      {
        label: "Most runs scored",
        value: [...teams].sort((a, b) => b.runs_scored - a.runs_scored)[0].abbr,
        delta: `${[...teams].sort((a, b) => b.runs_scored - a.runs_scored)[0].runs_scored} runs`,
      },
      {
        label: "Longest streak",
        value:
          [...teams].sort(
            (a, b) =>
              num((b.streak || "").slice(1)) - num((a.streak || "").slice(1)),
          )[0].streak || "—",
        delta: "Official standings",
      },
    ],
    featureTitle: "Last 10 leaders",
    features: byLastTen
      .slice(0, 5)
      .map((team) => ({
        name: team.name,
        detail: `${team.last_ten?.wins}-${team.last_ten?.losses} last 10`,
        value: team.streak || "—",
        score: Math.round(pct(team.last_ten?.pct) * 100),
      })),
    chart: byLastTen
      .slice(0, 10)
      .map((team) => Math.round(pct(team.last_ten?.pct) * 100)),
    chartLabels: byLastTen.slice(0, 10).map((team) => team.abbr),
    chartType: "bar",
    chartUnit: "last-10 win %",
    insight:
      "Momentum is based only on official last-10 records and run differential.",
    tableTitle: "Current team trends",
    table: {
      headers: ["Team", "Last 10", "Streak", "Home", "Away", "Run diff"],
      rows: byLastTen.map((team) => [
        team.name,
        `${team.last_ten?.wins || 0}-${team.last_ten?.losses || 0}`,
        team.streak || "—",
        `${team.home?.wins || 0}-${team.home?.losses || 0}`,
        `${team.away?.wins || 0}-${team.away?.losses || 0}`,
        team.run_differential,
      ]),
    },
  };
}

function unavailable(type, provider) {
  return {
    unavailable: true,
    title: type,
    provider,
    message:
      provider === "The Odds API"
        ? "Real betting markets will appear after an API key is configured. No simulated odds are shown."
        : "This data is not exposed by the currently configured official providers. No mock values are shown.",
  };
}

export const dataService = {
  async model() {
    return mlbStatsProvider.model();
  },
  async modelResults(date, page, pageSize, market, propTypes) {
    return mlbStatsProvider.modelResults(date, page, pageSize, market, propTypes);
  },
  async projectionBoard(startDate, days) {
    return mlbStatsProvider.projectionBoard(startDate || isoDate(), days || 7);
  },
  async playerProps(startDate, days, refresh = false) {
    return mlbStatsProvider.playerProps(startDate || isoDate(), days || 1, refresh);
  },
  async playerPropGuarantees(minimumSamples, search, propTypes) {
    return mlbStatsProvider.playerPropGuarantees(minimumSamples, search, propTypes);
  },
  async recordPlayerPropBuild(payload) {
    return mlbStatsProvider.recordPlayerPropBuild(payload);
  },
  async dashboard() {
    const [today, yesterday, teams, projectionBoard] = await Promise.all([
      providerGames(),
      providerGames(isoDate(-1), false, false),
      mlbStatsProvider.teams(),
      mlbStatsProvider
        .projectionBoard(isoDate(), 7)
        .catch(() => ({ games: [] })),
    ]);
    const active = today.filter((game) => isLive(game.status)),
      scheduled = today.filter(
        (game) => !isLive(game.status) && !isFinal(game.status),
      );
    const finals = [...today, ...yesterday]
      .filter((game) => isFinal(game.status))
      .slice(-10)
      .reverse();
    const weatherCount = today.filter((game) => game.weatherData).length;
    const teamById = new Map(teams.map((team) => [String(team.id), team]));
    const projectionById = new Map(
      (projectionBoard.games || []).map((game) => [String(game.game_id), game]),
    );
    const normalizedUpcoming = (projectionBoard.games || []).map((game) => ({
      id: String(game.game_id),
      gamePk: game.game_id,
      status: game.status || "Scheduled",
      inning: String(game.status || "Scheduled").toUpperCase(),
      time: timeLabel(game.starts_at),
      gameTime: game.starts_at,
      stadium: game.venue || "Venue TBD",
      weather: "Forecast pending",
      weatherData: null,
      away: { ...game.away, score: 0 },
      home: { ...game.home, score: 0 },
      pitchers: ["TBD", "TBD"],
      source: "MLB-StatsAPI",
    }));
    const candidates = [...active, ...scheduled, ...normalizedUpcoming].filter(
      (game, index, all) =>
        all.findIndex((item) => String(item.id) === String(game.id)) === index,
    );
    const ratedCandidates = candidates
      .map((game) => {
        const awayStanding = teamById.get(String(game.away.id)),
          homeStanding = teamById.get(String(game.home.id));
        const awayPct = pct(awayStanding?.pct),
          homePct = pct(homeStanding?.pct),
          projection = projectionById.get(String(game.id));
        const combinedStanding = (awayPct + homePct) / 2;
        const modelProbability = projection?.recommended_probability || null;
        const modelSide = projection?.recommended_side || null;
        const ratedGame = {
          ...game,
          away: {
            ...game.away,
            name: awayStanding?.name || game.away.name,
            abbr: awayStanding?.abbr || game.away.abbr,
            record: awayStanding
              ? `${awayStanding.wins}-${awayStanding.losses}`
              : game.away.record,
          },
          home: {
            ...game.home,
            name: homeStanding?.name || game.home.name,
            abbr: homeStanding?.abbr || game.home.abbr,
            record: homeStanding
              ? `${homeStanding.wins}-${homeStanding.losses}`
              : game.home.record,
          },
          brief: {
            combinedStanding,
            combinedStandingLabel: `${Math.round(combinedStanding * 100)}% combined win rate`,
            modelProbability,
            modelConfidence: projection?.model_confidence ?? null,
            modelSide,
            projectionUpdatedAt: projection?.projection_updated_at || null,
          },
        };
        ratedGame.brief.modelTeam = modelSide ? ratedGame[modelSide] : null;
        return ratedGame;
      })
      .sort(
        (a, b) =>
          b.brief.combinedStanding - a.brief.combinedStanding ||
          (b.brief.modelProbability || 0) - (a.brief.modelProbability || 0),
      );
    const featured = ratedCandidates[0] || null;
    return {
      live: active,
      today: scheduled,
      completed: finals,
      featured,
      metrics: [
        {
          label: "Games live",
          value: String(active.length),
          delta: `${today.length} games today`,
        },
        {
          label: "Scheduled",
          value: String(scheduled.length),
          delta: "Official MLB schedule",
        },
        {
          label: "Recent finals",
          value: String(finals.length),
          delta: "Latest completed games",
        },
        {
          label: "Forecast coverage",
          value: `${weatherCount}/${today.length}`,
          delta: "Open-Meteo game-time weather",
        },
      ],
      standings: [...teams].sort((a, b) => pct(b.pct) - pct(a.pct)).slice(0, 6),
      provider: { name: "MLB-StatsAPI", status: "live" },
      oddsStatus: oddsProvider.status(),
      updatedAt: new Date().toISOString(),
    };
  },
  async games(kind, date = isoDate()) {
    const games = await providerGames(date);
    if (kind === "live") return games.filter((game) => isLive(game.status));
    if (kind === "completed")
      return games.filter((game) => isFinal(game.status));
    return games;
  },
  async game(id) {
    const detail = await mlbStatsProvider.game(resolveId(id));
    const contextWeather = detail.model_context?.weather;
    const weather = contextWeather
      ? {
          temperature: Math.round(num(contextWeather.temperature)),
          windSpeed: Math.round(num(contextWeather.wind_speed)),
          windDirection: "",
          condition: contextWeather.condition,
          source: contextWeather.source,
        }
      : await weatherProvider
          .forecast(
            detail.venue?.latitude,
            detail.venue?.longitude,
            detail.datetime,
          )
          .catch(() => null);
    const awayStats = detail.team_stats?.away || {},
      homeStats = detail.team_stats?.home || {};
    const awayBat = awayStats.batting || {},
      homeBat = homeStats.batting || {},
      awayPitch = awayStats.pitching || {},
      homePitch = homeStats.pitching || {};
    const line = detail.linescore?.teams || {};
    let gameOdds = null;
    if (oddsProvider.configured())
      try {
        gameOdds =
          matchOdds(
            { away: detail.away, home: detail.home, gameTime: detail.datetime },
            (await oddsProvider.mlbOdds()).events,
          ) || null;
      } catch {}
    return {
      id: String(detail.game_id),
      partial: Boolean(detail.partial),
      status: detail.status,
      statusCode: detail.status_code,
      time: timeLabel(detail.datetime),
      gameTime: detail.datetime,
      stadium: detail.venue?.name,
      weather: weatherLabel(weather),
      weatherData: weather,
      contextUpdatedAt: detail.context_updated_at,
      projectionRefreshSeconds: detail.projection_refresh_seconds,
      away: { ...detail.away, score: num(line.away?.runs) },
      home: { ...detail.home, score: num(line.home?.runs) },
      metrics: [
        {
          label: `${detail.away.abbr} OPS`,
          value: awayBat.ops || "—",
          delta: "Official season stat",
        },
        {
          label: `${detail.home.abbr} OPS`,
          value: homeBat.ops || "—",
          delta: "Official season stat",
        },
        {
          label: `${detail.away.abbr} ERA`,
          value: awayPitch.era || "—",
          delta: "Official season stat",
        },
        {
          label: `${detail.home.abbr} ERA`,
          value: homePitch.era || "—",
          delta: "Official season stat",
        },
      ],
      starterProfiles: ["away", "home"]
        .map((side) =>
          detail.probable_pitchers?.[side]
            ? {
                ...detail.probable_pitchers[side],
                side,
                team_id: detail[side]?.id,
                team: detail[side]?.name,
                status:
                  detail.model_context?.[side]?.starter_status || "predicted",
              }
            : null,
        )
        .filter(Boolean),
      pitchingMatchup: detail.pitching_matchup || {},
      leagueContext: detail.league_context || null,
      recentForm: {
        away: detail.recent_form?.away || [],
        home: detail.recent_form?.home || [],
      },
      projection: detail.projection || {
        available: false,
        message: "The local model is unavailable.",
      },
      totalsProjection: detail.totals_projection || {
        available: false,
        message: "The totals projection is unavailable.",
      },
      modelContext: detail.model_context || null,
      teamProfiles: [
        {
          name: detail.away.name,
          team: detail.away.abbr,
          stats: {
            AVG: awayBat.avg || "—",
            OPS: awayBat.ops || "—",
            ERA: awayPitch.era || "—",
            WHIP: awayPitch.whip || "—",
          },
        },
        {
          name: detail.home.name,
          team: detail.home.abbr,
          stats: {
            AVG: homeBat.avg || "—",
            OPS: homeBat.ops || "—",
            ERA: homePitch.era || "—",
            WHIP: homePitch.whip || "—",
          },
        },
      ],
      comparison: [
        {
          team: detail.away.abbr,
          values: [
            awayBat.avg || "—",
            awayBat.obp || "—",
            awayBat.slg || "—",
            awayBat.ops || "—",
            awayBat.homeRuns ?? "—",
            awayBat.strikeOuts ?? "—",
            awayBat.runs ?? "—",
            awayPitch.era || "—",
          ],
        },
        {
          team: detail.home.abbr,
          values: [
            homeBat.avg || "—",
            homeBat.obp || "—",
            homeBat.slg || "—",
            homeBat.ops || "—",
            homeBat.homeRuns ?? "—",
            homeBat.strikeOuts ?? "—",
            homeBat.runs ?? "—",
            homePitch.era || "—",
          ],
        },
      ],
      plays: detail.plays || [],
      pitches: detail.pitches || [],
      count: detail.count || {},
      linescore: detail.linescore || {},
      runProgression: runProgression(detail.linescore?.innings),
      liveStats: detail.live_stats || null,
      odds: gameOdds,
      dataNotice: `Official MLB season statistics and game feed.${gameOdds ? " Current markets supplied by The Odds API." : " Betting markets are unavailable until The Odds API is configured."}`,
    };
  },
  async gameSummary(id) {
    const detail = await mlbStatsProvider.gameSummary(resolveId(id));
    return {
      id: String(detail.game_id),
      status: detail.status,
      time: timeLabel(detail.datetime),
      gameTime: detail.datetime,
      stadium: detail.venue?.name || "Venue TBD",
      weather: "Weather and model inputs loading",
      away: detail.away,
      home: detail.home,
      partial: true,
    };
  },
  async live(id) {
    const game = await this.game(id),
      line = game.linescore || {},
      offense = line.offense || {},
      defense = line.defense || {};
    return {
      game: {
        ...game,
        inning: isFinal(game.status)
          ? "FINAL"
          : /delay|postpon|suspend/i.test(game.status)
            ? game.status
            : [line.inning_state, line.inning_ordinal]
                .filter(Boolean)
                .join(" ") || game.status,
        bases: [
          Boolean(offense.first),
          Boolean(offense.second),
          Boolean(offense.third),
        ],
      },
      pitcher: {
        id: defense.pitcher?.id,
        name: defense.pitcher?.fullName || "Not available",
      },
      batter: {
        id: offense.batter?.id,
        name: offense.batter?.fullName || "Not available",
      },
      count: game.count,
      pitches: game.pitches.map((pitch, index) => ({
        ...pitch,
        x:
          pitch.px == null ? 50 : Math.max(8, Math.min(92, 50 + pitch.px * 20)),
        y:
          pitch.pz == null ? 50 : Math.max(8, Math.min(92, 90 - pitch.pz * 22)),
        label: pitch.result,
        location: `Zone ${pitch.zone || "—"}`,
        result: /ball/i.test(pitch.result || "") ? "ball" : "strike",
      })),
      plays: game.plays.map((play) => ({
        time: `${play.half || ""} ${play.inning || ""}`,
        count: `${play.balls}-${play.strikes}, ${play.outs} out`,
        text: play.description,
        impact: `${play.away_score}-${play.home_score}`,
        type: play.is_out ? "out" : "hit",
      })),
      runProgression: game.runProgression,
      liveStats: game.liveStats,
      oddsAvailable: false,
    };
  },
  async teams() {
    return mlbStatsProvider.teams();
  },
  async slips() {
    return mlbStatsProvider.slips();
  },
  async importSlip(payload) {
    return mlbStatsProvider.importSlip(payload);
  },
  async alterEgo() {
    return mlbStatsProvider.alterEgo();
  },
  async importMelbetHistory(payload) {
    return mlbStatsProvider.importMelbetHistory(payload);
  },
  async importMelbetHistoryBatch(payload) {
    return mlbStatsProvider.importMelbetHistoryBatch(payload);
  },
  async team(id) {
    const all = await mlbStatsProvider.teams(),
      detail = await mlbStatsProvider.team(resolveId(id)),
      team = detail.team,
      hit = detail.stats?.hitting || {},
      pitch = detail.stats?.pitching || {};
    const divisionTeams = all
      .filter((item) => item.division === team.division)
      .sort((a, b) => pct(b.pct) - pct(a.pct));
    const schedule = detail.schedule || [],
      completed = schedule.filter((game) => game.is_final && !/postponed|cancelled|suspended/i.test(game.status || "")),
      recent = completed.slice(-20),
      leagueRankings = detail.league_rankings || [],
      rankingByKey = new Map(leagueRankings.map((row) => [row.key, row])),
      progress = [];
    let diff = 0;
    recent.forEach((game) => {
      diff += num(game.team_score) - num(game.opponent_score);
      progress.push(diff);
    });
    const roster = activeRoster(detail.roster || []);
    const hitterKRate = rankingByKey.get("hitter_k_rate");
    const pitcherKRate = rankingByKey.get("pitcher_k_rate");
    return {
      name: team.name,
      abbr: team.abbr,
      teamId: team.id,
      kicker: `${team.division} · OFFICIAL MLB DATA`,
      subtitle: `${team.wins}-${team.losses} · ${team.streak || "—"} · RUN DIFF ${team.run_differential >= 0 ? "+" : ""}${team.run_differential}`,
      highlightLabel: "MLB STANDINGS RANK",
      highlight: `#${team.rank || "—"}`,
      metrics: [
        {
          label: "Record",
          value: `${team.wins}-${team.losses}`,
          delta: `${team.pct} win pct`,
        },
        {
          label: "Run differential",
          value: `${team.run_differential >= 0 ? "+" : ""}${team.run_differential}`,
          delta: `${team.runs_scored} RS · ${team.runs_allowed} RA`,
        },
        {
          label: "Team OPS",
          value: hit.ops || "—",
          delta: `AVG ${hit.avg || "—"}`,
        },
        {
          label: "Hitter K rate",
          value: hitterKRate?.display || "—",
          delta: hitterKRate ? `#${hitterKRate.rank} of ${hitterKRate.teams} MLB teams` : "League rank pending",
        },
        {
          label: "Team ERA",
          value: pitch.era || "—",
          delta: `WHIP ${pitch.whip || "—"}`,
        },
        {
          label: "Pitcher K rate",
          value: pitcherKRate?.display || "—",
          delta: pitcherKRate ? `#${pitcherKRate.rank} of ${pitcherKRate.teams} MLB teams` : "League rank pending",
        },
      ],
      chartTitle: "Cumulative run differential · latest 20 completed games",
      chart: progress.length ? progress : [0, 0],
      chartLabels: progress.length
        ? recent.map((game) => String(game.date || "").slice(5))
        : ["No data", ""],
      chartType: "line",
      chartUnit: "runs",
      insight:
        "Each point adds the run differential from the next completed game in chronological order. All values come from official MLB feeds.",
      rankingTitle: "Official standing",
      ranks: [
        {
          label: "MLB rank",
          value: `#${team.rank || "—"}`,
          score: Math.max(5, 100 - (num(team.rank) - 1) * 3),
          note: `Division rank #${team.division_rank || "—"}`,
        },
        {
          label: "Winning percentage",
          value: team.pct || "—",
          score: Math.round(pct(team.pct) * 100),
          note: `${team.games_back || "—"} GB`,
        },
        {
          label: "Last 10",
          value: `${team.last_ten?.wins || 0}-${team.last_ten?.losses || 0}`,
          score: Math.round(pct(team.last_ten?.pct) * 100),
          note: team.streak || "—",
        },
      ],
      leaderTitle: "Active roster",
      leaders: roster
        .slice(0, 4)
        .map((item) => ({
          id: item.id,
          name: item.name,
          initials: initials(item.name),
          role: `#${item.number} · ${item.role}`,
          stats: { POS: item.position, STATUS: item.status },
        })),
      roster,
      season: detail.season,
      through: detail.through,
      leagueRankings,
      leagueTeamCount: detail.league_team_count || 30,
      inningDistribution: detail.inning_distribution || null,
      schedule,
      scheduleSummary: {
        total: schedule.length,
        active: schedule.filter((game) => !/postponed|cancelled|suspended/i.test(game.status || "")).length,
        completed: completed.length,
        upcoming: schedule.filter((game) => !game.is_final && !/postponed|cancelled|suspended/i.test(game.status || "")).length,
        postponed: schedule.filter((game) => /postponed|cancelled|suspended/i.test(game.status || "")).length,
        home: schedule.filter((game) => game.is_home).length,
        away: schedule.filter((game) => !game.is_home).length,
      },
      statusTitle: "Recent results",
      status: completed
        .slice(-5)
        .reverse()
        .map((game) => {
          return {
            name: `${game.is_home ? "vs" : "@"} ${game.opponent}`,
            detail: game.date,
            value: `${game.result || "—"} ${game.team_score}-${game.opponent_score}`,
            tone: game.result === "W" ? "teal" : "pink",
          };
        }),
      tableTitle: `${team.division} standings`,
      table: {
        headers: ["Team", "W", "L", "PCT", "GB", "Run diff"],
        rows: divisionTeams.map((item, index) => [
          `${index + 1} · ${item.name}`,
          item.wins,
          item.losses,
          item.pct,
          item.games_back || "—",
          item.run_differential,
        ]),
      },
    };
  },
  async players() {
    return mlbStatsProvider.players();
  },
  async player(id) {
    const player = await mlbStatsProvider.player(resolveId(id)),
      hitting = player.stats?.find((item) => item.group === "hitting")?.stats,
      pitching = player.stats?.find((item) => item.group === "pitching")?.stats,
      stat = hitting || pitching || {},
      hitter = Boolean(hitting);
    const allGameLogs = player.game_log || [],
      gameLog = allGameLogs.filter((item) => item.group === (hitter ? "hitting" : "pitching")),
      trendLog = gameLog.slice(-30),
      primaryKey = hitter ? "hits" : "strikeOuts",
      secondaryKey = hitter ? "totalBases" : "numberOfPitches",
      gameValues = gameLog.map((item) => Number(item.stats?.[primaryKey] || 0)),
      trendValues = trendLog.map((item) => Number(item.stats?.[primaryKey] || 0)),
      secondaryValues = trendLog.map((item) => Number(item.stats?.[secondaryKey] || 0)),
      lastFive = gameValues.slice(-5),
      seasonGameAverage = gameValues.length ? gameValues.reduce((sum, value) => sum + value, 0) / gameValues.length : null,
      recentAverage = lastFive.length ? lastFive.reduce((sum, value) => sum + value, 0) / lastFive.length : null,
      peerMetrics = player.peer_profile?.metrics || [],
      leadPeerMetric = [...peerMetrics].filter((item) => item.percentile != null).sort((a, b) => b.percentile - a.percentile)[0];
    const gameLogDefinitions = {
      hitting: {
        label: "Hitting game log",
        columns: [
          ["plateAppearances", "PA"], ["atBats", "AB"], ["runs", "R"], ["hits", "H"],
          ["doubles", "2B"], ["triples", "3B"], ["homeRuns", "HR"], ["rbi", "RBI"],
          ["baseOnBalls", "BB"], ["strikeOuts", "K"], ["stolenBases", "SB"], ["totalBases", "TB"],
          ["leftOnBase", "LOB"], ["numberOfPitches", "Pitches"], ["avg", "AVG"], ["obp", "OBP"],
          ["slg", "SLG"], ["ops", "OPS"],
        ],
      },
      pitching: {
        label: "Pitching game log",
        columns: [
          ["gamesStarted", "GS"], ["inningsPitched", "IP"], ["hits", "H"], ["runs", "R"],
          ["earnedRuns", "ER"], ["homeRuns", "HR"], ["baseOnBalls", "BB"], ["strikeOuts", "K"],
          ["numberOfPitches", "Pitches"], ["strikes", "Strikes"], ["battersFaced", "BF"], ["strikePercentage", "Strike %"],
          ["era", "ERA"], ["whip", "WHIP"], ["pitchesPerInning", "P / IP"], ["strikeoutWalkRatio", "K / BB"],
          ["groundOuts", "GO"], ["airOuts", "AO"],
        ],
      },
      fielding: {
        label: "Fielding game log",
        columns: [
          ["gamesStarted", "GS"], ["innings", "Inn"], ["putOuts", "PO"], ["assists", "A"],
          ["errors", "E"], ["chances", "Ch"], ["doublePlays", "DP"], ["fielding", "FLD %"],
        ],
      },
    };
    const gameLogLabelOverrides = {
      gamesPlayed: "G", gamesStarted: "GS", atBats: "AB", plateAppearances: "PA",
      runs: "R", hits: "H", doubles: "2B", triples: "3B", homeRuns: "HR", rbi: "RBI",
      baseOnBalls: "BB", intentionalWalks: "IBB", strikeOuts: "K", hitByPitch: "HBP",
      stolenBases: "SB", caughtStealing: "CS", totalBases: "TB", leftOnBase: "LOB",
      sacBunts: "SAC", sacFlies: "SF", groundIntoDoublePlay: "GIDP", numberOfPitches: "Pitches",
      avg: "AVG", obp: "OBP", slg: "SLG", ops: "OPS", babip: "BABIP",
      inningsPitched: "IP", earnedRuns: "ER", battersFaced: "BF", strikes: "Strikes",
      strikePercentage: "Strike %", pitchesPerInning: "P / IP", strikeoutWalkRatio: "K / BB",
      strikeoutsPer9Inn: "K / 9", walksPer9Inn: "BB / 9", hitsPer9Inn: "H / 9",
      homeRunsPer9: "HR / 9", groundOuts: "GO", airOuts: "AO", groundOutsToAirouts: "GO / AO",
      wins: "W", losses: "L", saves: "SV", saveOpportunities: "SVO", holds: "HLD",
      blownSaves: "BS", era: "ERA", whip: "WHIP", completeGames: "CG", shutouts: "SHO",
      innings: "Inn", putOuts: "PO", assists: "A", errors: "E", chances: "Ch",
      doublePlays: "DP", fielding: "FLD %",
    };
    const gameLogColumnLabel = (key) => gameLogLabelOverrides[key]
      || String(key).replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/^./, (letter) => letter.toUpperCase());
    const gameLogs = Object.entries(gameLogDefinitions)
      .map(([group, definition]) => {
        const rows = allGameLogs.filter((row) => row.group === group),
          preferredKeys = new Set(definition.columns.map(([key]) => key)),
          extraKeys = [...new Set(rows.flatMap((row) => Object.keys(row.stats || {})))]
            .filter((key) => !preferredKeys.has(key))
            .sort((left, right) => gameLogColumnLabel(left).localeCompare(gameLogColumnLabel(right)));
        return {
          group,
          label: definition.label,
          columns: [
            ...definition.columns.map(([key, label]) => ({ key, label })),
            ...extraKeys.map((key) => ({ key, label: gameLogColumnLabel(key) })),
          ],
          rows,
        };
      })
      .filter((section) => section.rows.length);
    const metrics = hitter
      ? [
          {
            label: "Batting average",
            value: stat.avg || "—",
            delta: `${stat.gamesPlayed || 0} games`,
          },
          {
            label: "OPS",
            value: stat.ops || "—",
            delta: `OBP ${stat.obp || "—"}`,
          },
          {
            label: "Home runs",
            value: String(stat.homeRuns ?? "—"),
            delta: `${stat.rbi || 0} RBI`,
          },
          {
            label: "Walks",
            value: String(stat.baseOnBalls ?? "—"),
            delta: `${stat.strikeOuts || 0} strikeouts`,
          },
        ]
      : [
          {
            label: "ERA",
            value: stat.era || "—",
            delta: `${stat.gamesPlayed || 0} games`,
          },
          {
            label: "WHIP",
            value: stat.whip || "—",
            delta: `${stat.inningsPitched || 0} IP`,
          },
          {
            label: "Strikeouts",
            value: String(stat.strikeOuts ?? "—"),
            delta: `${stat.baseOnBalls || 0} walks`,
          },
          {
            label: "Wins",
            value: String(stat.wins ?? "—"),
            delta: `${stat.losses || 0} losses`,
          },
        ];
    return {
      playerId: player.id,
      season: Number(player.stats?.find((item) => item?.season)?.season || new Date().getUTCFullYear()),
      name: `${player.first_name} ${player.last_name}`,
      number: `#${player.id}`,
      kicker: `${player.current_team || "MLB"} · ${player.position || "PLAYER"}`,
      subtitle: `${player.bat_side || "—"} BAT · ${player.pitch_hand || "—"} THROW · MLB DEBUT ${player.mlb_debut || "—"}`,
      highlightLabel: hitter ? "2026 OPS" : "2026 ERA",
      highlight: hitter ? stat.ops || "—" : stat.era || "—",
      metrics,
      chartTitle: hitter ? "2026 batting totals" : "2026 pitching totals",
      chart: hitter
        ? [stat.hits || 0, stat.runs || 0, stat.homeRuns || 0, stat.rbi || 0]
        : [
            Number(stat.inningsPitched || 0),
            stat.strikeOuts || 0,
            stat.wins || 0,
            stat.saves || 0,
          ],
      chartLabels: hitter
        ? ["Hits", "Runs", "Home runs", "RBI"]
        : ["Innings", "Strikeouts", "Wins", "Saves"],
      chartType: "bar",
      insight:
        "Bars show the labeled official season totals directly; unlike a trend line, they do not imply a time sequence. No modeled player values are displayed.",
      rankingTitle: "Season rates",
      ranks: hitter
        ? [
            {
              label: "AVG",
              value: stat.avg || "—",
              score: Math.round(pct(stat.avg) * 100),
              note: `${stat.hits || 0} hits`,
            },
            {
              label: "OBP",
              value: stat.obp || "—",
              score: Math.round(pct(stat.obp) * 100),
              note: `${stat.baseOnBalls || 0} walks`,
            },
            {
              label: "SLG",
              value: stat.slg || "—",
              score: Math.round(pct(stat.slg) * 100),
              note: `${stat.totalBases || 0} total bases`,
            },
          ]
        : [
            {
              label: "ERA",
              value: stat.era || "—",
              score: Math.max(0, 100 - num(stat.era) * 12),
              note: `${stat.inningsPitched || 0} IP`,
            },
            {
              label: "WHIP",
              value: stat.whip || "—",
              score: Math.max(0, 100 - num(stat.whip) * 35),
              note: `${stat.strikeOuts || 0} SO`,
            },
          ],
      leaderTitle: "Season production",
      leaders: [
        {
          id: player.id,
          name: `${player.first_name} ${player.last_name}`,
          initials: player.position || "—",
          role: `${player.stats?.[0]?.season || 2026} season`,
          stats: hitter
            ? { H: stat.hits || 0, RBI: stat.rbi || 0 }
            : { IP: stat.inningsPitched || 0, SO: stat.strikeOuts || 0 },
        },
      ],
      statusTitle: "Provider status",
      gameLogs,
      gameLogCount: new Set(allGameLogs.map((row) => row.game_id)).size,
      analytics: {
        positionGroup: hitter ? "Position players" : "Pitchers",
        peerSample: player.peer_profile?.sample || 0,
        metrics: peerMetrics,
        trends: {
          labels: trendLog.map((row) => String(row.date || "").slice(5) || `G${row.game_id}`),
          primary: trendValues,
          secondary: secondaryValues,
          primaryLabel: hitter ? "Hits" : "Strikeouts",
          secondaryLabel: hitter ? "Total bases" : "Pitches",
        },
        splits: lastFive.length ? [{ label: "Latest 5", value: Number(recentAverage.toFixed(2)), comparison: Number(seasonGameAverage.toFixed(2)), context: "Captured game average" }] : [],
        interpretation: leadPeerMetric
          ? `${player.first_name} ${player.last_name}'s strongest captured peer rate is ${leadPeerMetric.label} at the ${leadPeerMetric.percentile}th percentile among ${player.peer_profile.sample} ${hitter ? "MLB hitters" : "MLB pitchers"}. ${lastFive.length ? `The latest five average ${recentAverage.toFixed(2)} ${hitter ? "hits" : "strikeouts"}, compared with ${seasonGameAverage.toFixed(2)} across the captured game log.` : "A chronological game sample is not available."}`
          : `Official season totals are available, but a sufficiently comparable league peer sample is not attached to this response.`,
        source: "Official MLB Stats API season and game-log records",
      },
      status: [
        {
          name: "Official MLB feed",
          detail: "Current season totals",
          value: "LIVE",
          tone: "teal",
        },
      ],
      tableTitle: "Current season statistics",
      table: hitter
        ? {
            headers: ["G", "AB", "H", "HR", "RBI", "AVG", "OBP", "SLG", "OPS"],
            rows: [
              [
                stat.gamesPlayed,
                stat.atBats,
                stat.hits,
                stat.homeRuns,
                stat.rbi,
                stat.avg,
                stat.obp,
                stat.slg,
                stat.ops,
              ],
            ],
          }
        : {
            headers: ["G", "GS", "IP", "W", "L", "ERA", "WHIP", "SO", "BB"],
            rows: [
              [
                stat.gamesPlayed,
                stat.gamesStarted,
                stat.inningsPitched,
                stat.wins,
                stat.losses,
                stat.era,
                stat.whip,
                stat.strikeOuts,
                stat.baseOnBalls,
              ],
            ],
          },
    };
  },
  async betting() {
    if (!oddsProvider.configured())
      return unavailable("Betting intelligence", "The Odds API");
    try {
      const response = await oddsProvider.mlbOdds(),
        events = response.events;
      const priced = events.filter(
        (event) => event.awayMoneyline != null && event.homeMoneyline != null,
      );
      return {
        source: { provider: "The Odds API", quota: response.quota },
        metrics: [
          {
            label: "MLB events",
            value: String(events.length),
            delta: "Live and upcoming",
          },
          {
            label: "Books tracked",
            value: String(
              new Set(
                events.flatMap((event) =>
                  event.bookmakers.map((book) => book.key),
                ),
              ).size,
            ),
            delta: "Configured region",
          },
          {
            label: "Markets",
            value: "3",
            delta: "Moneyline · spreads · totals",
          },
          {
            label: "Credits remaining",
            value: response.quota.remaining || "—",
            delta: "Provider quota",
          },
        ],
        featureTitle: "Current MLB markets",
        features: priced
          .slice(0, 6)
          .map((event) => ({
            name: `${event.awayTeam} @ ${event.homeTeam}`,
            detail: `${event.bookmakers.length} bookmakers · ${new Date(event.commenceTime).toLocaleString()}`,
            value: `${event.awayMoneyline} / ${event.homeMoneyline}`,
            score: Math.min(100, event.bookmakers.length * 8),
          })),
        chart: priced.slice(0, 10).map((event) => event.bookmakers.length),
        insight:
          "Prices are current bookmaker markets supplied directly by The Odds API. No proprietary edge or confidence claim is applied.",
        tableTitle: "MLB odds board",
        table: {
          headers: [
            "Matchup",
            "Away ML",
            "Home ML",
            "Run line",
            "Total",
            "Books",
          ],
          rows: events.map((event) => [
            `${event.awayTeam} @ ${event.homeTeam}`,
            event.awayMoneyline ?? "—",
            event.homeMoneyline ?? "—",
            event.homeSpread
              ? `${event.homeSpread.point} (${event.homeSpread.price})`
              : "—",
            event.over ? `${event.over.point} O ${event.over.price}` : "—",
            event.bookmakers.length,
          ]),
        },
      };
    } catch (error) {
      return {
        ...unavailable("Betting intelligence", "The Odds API"),
        message: `The configured provider could not be reached: ${error.message}`,
      };
    }
  },
  injuries: () => unavailable("Injuries & lineups", "MLB-StatsAPI"),
  async trends() {
    return teamExplorer(await mlbStatsProvider.teams(), "trends");
  },
  async rankings() {
    return teamExplorer(await mlbStatsProvider.teams(), "rankings");
  },
  async health() {
    try {
      return {
        status: "ok",
        stats: await mlbStatsProvider.health(),
        weather: { provider: "Open-Meteo", status: "ready" },
        odds: oddsProvider.status(),
        syntheticData: false,
      };
    } catch (error) {
      return {
        status: "degraded",
        error: error.message,
        odds: oddsProvider.status(),
        syntheticData: false,
      };
    }
  },
  async search(query) {
    const term = query.trim().toLowerCase();
    if (term.length < 2) return { Teams: [], Players: [], Games: [] };
    const [teams, players, gameDays] = await Promise.all([
      mlbStatsProvider.teams(),
      mlbStatsProvider.players(),
      Promise.all(
        [isoDate(-1), isoDate(), isoDate(1)].map((day) =>
          providerGames(day, false, false).catch(() => []),
        ),
      ),
    ]);
    const includes = (...values) =>
      values
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(term));
    const teamResults = teams
      .filter((item) =>
        includes(item.name, item.abbr, item.division, item.venue),
      )
      .slice(0, 12)
      .map((item) => ({
        ...item,
        detail: `${item.division} · ${item.wins}-${item.losses}`,
        path: `/teams/${item.id}`,
      }));
    const playerResults = players
      .filter((item) =>
        includes(
          item.name,
          item.team_name,
          item.team_abbr,
          item.position,
          item.position_abbr,
        ),
      )
      .slice(0, 16)
      .map((item) => ({
        id: item.id,
        abbr: item.position_abbr || "MLB",
        name: item.name,
        teamId: item.team_id,
        detail: `${item.position} · ${item.team_name}`,
        path: `/players/${item.id}`,
      }));
    const seen = new Set();
    const gameResults = gameDays
      .flat()
      .filter((game) =>
        includes(
          game.away?.name,
          game.away?.abbr,
          game.home?.name,
          game.home?.abbr,
          game.stadium,
          game.status,
        ),
      )
      .filter((game) => !seen.has(game.id) && seen.add(game.id))
      .slice(0, 12)
      .map((game) => ({
        id: game.id,
        abbr: `${game.away.abbr} @ ${game.home.abbr}`,
        name: `${game.away.name} at ${game.home.name}`,
        detail: `${game.time} · ${game.stadium} · ${game.status}`,
        path: `/games/${game.id}`,
      }));
    return { Teams: teamResults, Players: playerResults, Games: gameResults };
  },
};
