import argparse, json, sys, time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stats-service"))
import statsapi
DATA_DIR = ROOT / "ml" / "data"

def season_schedule(season):
    start, finish, games = date(season, 3, 1), date(season, 11, 15), []
    while start <= finish:
        end = min(finish, start + timedelta(days=30))
        for attempt in range(4):
            try:
                games.extend(statsapi.schedule(start_date=start.isoformat(), end_date=end.isoformat(), sportId=1))
                break
            except Exception:
                if attempt == 3: raise
                time.sleep(2 ** attempt)
        start = end + timedelta(days=1)
    return games

def collect(start_season, end_season):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output, games_by_id = DATA_DIR / "games.jsonl", {}
    if output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            game = json.loads(line); games_by_id[str(game["game_id"])] = game
    for season in range(start_season, end_season + 1):
        print(f"Collecting {season} regular season...")
        games = season_schedule(season)
        kept = 0
        for game in games:
            if "Final" not in game.get("status", "") or game.get("game_type") not in (None, "R"):
                continue
            home_score, away_score = game.get("home_score"), game.get("away_score")
            if home_score is None or away_score is None or home_score == away_score:
                continue
            row = {"game_id": int(game["game_id"]), "date": game["game_date"], "season": season, "home_id": int(game["home_id"]), "away_id": int(game["away_id"]), "home_name": game["home_name"], "away_name": game["away_name"], "home_score": int(home_score), "away_score": int(away_score)}
            games_by_id[str(row["game_id"])] = row; kept += 1
        print(f"  {kept} completed games")
        output.write_text("\n".join(json.dumps(game) for game in sorted(games_by_id.values(), key=lambda row: (row["date"], row["game_id"]))) + "\n", encoding="utf-8")
    print(f"Saved {len(games_by_id)} games to {output}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--start-season", type=int, default=2018); parser.add_argument("--end-season", type=int, default=date.today().year - 1)
    args = parser.parse_args(); collect(args.start_season, args.end_season)
