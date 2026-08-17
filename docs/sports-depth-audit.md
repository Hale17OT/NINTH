# NINTH sports depth audit

Status language: Missing, Partial, Implemented, Verified.

| Area | MLB | Football | NFL | NBA | Esports |
|---|---|---|---|---|---|
| League structure | Implemented | Implemented | Implemented | Implemented | Implemented from live tournaments |
| Team identity/logos | Verified MLB marks | Partial outside provider coverage | Partial (fallback identity) | Implemented (30 provider teams) | Partial (provider rarely supplies marks) |
| Team pages | Implemented | Implemented | Implemented | Implemented | Implemented |
| Rosters | Implemented | Implemented for EPL; provider-dependent elsewhere | Implemented | Implemented | Partial: team assignments absent in current player source |
| Player pages | Implemented | Implemented where roster source exists | Implemented | Implemented | Implemented for identified players |
| Match pages | Implemented | Implemented | Implemented | Implemented | Implemented |
| Predictions | Production + audited manual markets | Partial, five current exported fixtures | Implemented shadow/market-specific | Partial: model artifacts exist, event exporter missing | Implemented live shadow baseline |
| Builders | Implemented | Implemented league-aware shadow builder | Implemented NFL-specific builder | Partial: slate/audit workspace, selections locked | Implemented tournament-aware shadow builder |
| Advanced analytics | Implemented and expanded | Implemented from open result/shot ledger | Partial | Implemented from 20k+ possession rows | Partial and discipline-dependent |
| Navigation | Implemented | Implemented | Implemented | Implemented | Implemented with honest roster gaps |

This audit deliberately distinguishes source availability from UI completeness. A fallback identity is not counted as a real logo, and an unassigned esports player is not counted as a verified roster member.
