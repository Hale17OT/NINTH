import argparse, json, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'stats-service'))
import statsapi
GAMES=ROOT/'ml'/'data'/'games.jsonl';OUTPUT=ROOT/'ml'/'data'/'contexts.jsonl'

def number(value, default=0.0):
    try:return float(value)
    except:return default

def pregame_batting(player):
    season=player.get('seasonStats',{}).get('batting',{});game=player.get('stats',{}).get('batting',{})
    values={key:max(0,number(season.get(key))-number(game.get(key))) for key in ('hits','baseOnBalls','hitByPitch','atBats','sacFlies','totalBases')}
    obp=(values['hits']+values['baseOnBalls']+values['hitByPitch'])/max(1,values['atBats']+values['baseOnBalls']+values['hitByPitch']+values['sacFlies']);slg=values['totalBases']/max(1,values['atBats'])
    pa=values['atBats']+values['baseOnBalls']+values['hitByPitch']+values['sacFlies'];ops=obp+slg
    return {'ops':ops,'pa':pa,'shrunk_ops':(ops*pa+.710*100)/(pa+100)}

def side_context(box,side,people):
    team=box.get(side,{});players=team.get('players',{});order=team.get('battingOrder',[])[:9];batters=[{'player_id':pid,**pregame_batting(players.get('ID'+str(pid),{}))} for pid in order]
    pitchers=team.get('pitchers',[]);starter_id=pitchers[0] if pitchers else None;starter=players.get('ID'+str(starter_id),{}) if starter_id else {};season=starter.get('seasonStats',{}).get('pitching',{});game=starter.get('stats',{}).get('pitching',{})
    outs=max(0,number(season.get('outs'))-number(game.get('outs')));earned=max(0,number(season.get('earnedRuns'))-number(game.get('earnedRuns')));hits=max(0,number(season.get('hits'))-number(game.get('hits')));walks=max(0,number(season.get('baseOnBalls'))-number(game.get('baseOnBalls')));homers=max(0,number(season.get('homeRuns'))-number(game.get('homeRuns')));strikeouts=max(0,number(season.get('strikeOuts'))-number(game.get('strikeOuts')));hit_batters=max(0,number(season.get('hitBatsmen'))-number(game.get('hitBatsmen')));innings=max(1/3,outs/3)
    bullpen=sum(number(players.get('ID'+str(pid),{}).get('stats',{}).get('pitching',{}).get('numberOfPitches')) for pid in pitchers[1:])
    fip=(13*homers+3*(walks+hit_batters)-2*strikeouts)/innings+3.1
    return {'starter_id':starter_id,'starter_name':people.get('ID'+str(starter_id),{}).get('fullName') if starter_id else None,'starter_era':9*earned/innings,'starter_whip':(hits+walks)/innings,'starter_fip':fip,'starter_innings':outs/3,'starter_strikeouts':strikeouts,'starter_walks':walks,'starter_home_runs':homers,'starter_game_outs':number(game.get('outs')),'starter_game_earned_runs':number(game.get('earnedRuns')),'starter_game_strikeouts':number(game.get('strikeOuts')),'starter_game_walks':number(game.get('baseOnBalls')),'starter_game_home_runs':number(game.get('homeRuns')),'starter_game_pitches':number(game.get('numberOfPitches')),'lineup_ids':order,'lineup_players':batters,'lineup_confirmed':len(order)>=9,'lineup_ops':sum(item['ops'] for item in batters)/len(batters) if batters else 0.0,'lineup_ops_shrunk':sum(item['shrunk_ops'] for item in batters)/len(batters) if batters else .710,'lineup_average_pa':sum(item['pa'] for item in batters)/len(batters) if batters else 0.0,'bullpen_ids':team.get('bullpen',[]),'bullpen_pitches':bullpen}

def enrich(game):
    for attempt in range(4):
        try:
            feed=statsapi.get('game',{'gamePk':game['game_id']});data=feed.get('gameData',{});weather=data.get('weather',{});wind=re.search(r'(\d+)\s*mph',weather.get('wind',''))
            return {'game_id':game['game_id'],'date':game['date'],'season':game['season'],'away':side_context(feed['liveData']['boxscore']['teams'],'away',data.get('players',{})),'home':side_context(feed['liveData']['boxscore']['teams'],'home',data.get('players',{})),'weather':{'temperature':number(weather.get('temp'),65),'wind_speed':number(wind.group(1),0) if wind else 0,'condition':weather.get('condition'),'source':'MLB recorded game weather'}}
        except Exception:
            if attempt==3:raise
            time.sleep(2**attempt)

def main(start,end,workers,limit=None,output=OUTPUT):
    output=Path(output)
    games=[json.loads(x) for x in GAMES.read_text(encoding='utf8').splitlines() if x.strip()];existing=set()
    if output.exists():existing={str(json.loads(x)['game_id']) for x in output.read_text(encoding='utf-8-sig').splitlines() if x.strip()}
    pending=[g for g in games if start<=g['season']<=end and str(g['game_id']) not in existing]
    if limit:pending=pending[:limit]
    output.parent.mkdir(parents=True,exist_ok=True);done=0
    print(f'Backfilling {len(pending)} games ({start}-{end})',flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool,output.open('a',encoding='utf8') as handle:
        futures={pool.submit(enrich,g):g for g in pending}
        for future in as_completed(futures):
            try:handle.write(json.dumps(future.result())+'\n');handle.flush();done+=1
            except Exception as exc:print('FAILED',futures[future]['game_id'],exc,flush=True)
            if done%100==0:print(f'{done}/{len(pending)}',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--start-season',type=int,default=2023);p.add_argument('--end-season',type=int,default=2025);p.add_argument('--workers',type=int,default=8);p.add_argument('--limit',type=int);p.add_argument('--output',default=str(OUTPUT));a=p.parse_args();main(a.start_season,a.end_season,a.workers,a.limit,a.output)
