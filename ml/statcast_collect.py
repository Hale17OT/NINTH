"""Resumable, streaming Baseball Savant collector.

Downloads one day at a time, keeps only compact per-game aggregates, and discards
raw pitch rows. Nothing from this file enters production until walk-forward
ablation in train.py proves that it improves unseen seasons.
"""
import argparse,csv,io,json,time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import date,timedelta
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'ml'/'data';OUTPUT=DATA/'statcast_games.jsonl';MANIFEST=DATA/'statcast_days.txt';OFFICIAL_GAMES=DATA/'games.jsonl'
URL='https://baseballsavant.mlb.com/statcast_search/csv'

def number(value):
    try:return float(value)
    except (TypeError,ValueError):return None

def fresh():
    return {'pitches':0,'pa':set(),'bip':0,'ev_sum':0.0,'hard_hit':0,'barrels':0,'xwoba_sum':0.0,'xwoba_n':0,'woba_sum':0.0,'woba_denom':0.0,'whiffs':0,'strikeouts':0,'walks':0,'velocity_sum':0.0,'velocity_n':0,'hand':None,'first_at_bat':None}

def finish(value):
    return {'pitches':value['pitches'],'plate_appearances':len(value['pa']),'balls_in_play':value['bip'],'avg_exit_velocity':round(value['ev_sum']/value['bip'],3) if value['bip'] else None,'hard_hit_rate':round(value['hard_hit']/value['bip'],4) if value['bip'] else None,'barrel_rate':round(value['barrels']/value['bip'],4) if value['bip'] else None,'xwoba':round(value['xwoba_sum']/value['xwoba_n'],4) if value['xwoba_n'] else None,'woba':round(value['woba_sum']/value['woba_denom'],4) if value['woba_denom'] else None,'whiff_rate':round(value['whiffs']/value['pitches'],4) if value['pitches'] else None,'strikeouts':value['strikeouts'],'walks':value['walks'],'avg_velocity':round(value['velocity_sum']/value['velocity_n'],3) if value['velocity_n'] else None}

def collect_day(day,session):
    params={'all':'true','type':'details','game_date_gt':day,'game_date_lt':day,'hfGT':'R|','group_by':'name-date','sort_col':'pitches','player_type':'batter'}
    response=session.get(URL,params=params,timeout=90);response.raise_for_status()
    games={}
    reader=csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')))
    for row in reader:
        game_pk=row.get('game_pk');home=row.get('home_team');away=row.get('away_team');half=row.get('inning_topbot','')
        if not game_pk or not home or not away or half not in ('Top','Bot'):continue
        game=games.setdefault(game_pk,{'game_id':int(game_pk),'date':row.get('game_date') or day,'home_abbr':home,'away_abbr':away,'home':fresh(),'away':fresh(),'home_vs_left':fresh(),'home_vs_right':fresh(),'away_vs_left':fresh(),'away_vs_right':fresh(),'home_pitching':fresh(),'away_pitching':fresh(),'home_pitchers':{},'away_pitchers':{},'home_batters':{},'away_batters':{},'home_batters_vs_left':{},'home_batters_vs_right':{},'away_batters_vs_left':{},'away_batters_vs_right':{}})
        batting='away' if half=='Top' else 'home';pitching='home_pitching' if half=='Top' else 'away_pitching';pitcher_side='home_pitchers' if half=='Top' else 'away_pitchers';offense=game[batting];defense=game[pitching];pitcher_id=row.get('pitcher');pitcher=game[pitcher_side].setdefault(pitcher_id,fresh()) if pitcher_id else None;defensive_targets=(defense,pitcher) if pitcher else (defense,)
        pitcher_hand=row.get('p_throws');split=game[f"{batting}_vs_left" if pitcher_hand=='L' else f"{batting}_vs_right"]
        if pitcher:
            pitcher['hand']=pitcher_hand or pitcher['hand']
            at_bat=number(row.get('at_bat_number'))
            if at_bat is not None and (pitcher['first_at_bat'] is None or at_bat<pitcher['first_at_bat']):pitcher['first_at_bat']=at_bat
        batter_id=row.get('batter');batter=game[f'{batting}_batters'].setdefault(batter_id,fresh()) if batter_id else None;batter_split=game[f"{batting}_batters_vs_left" if pitcher_hand=='L' else f"{batting}_batters_vs_right"].setdefault(batter_id,fresh()) if batter_id else None
        offense_targets=(offense,split,batter,batter_split) if batter else (offense,split)
        for target in (*offense_targets,*defensive_targets):target['pitches']+=1
        pa=(row.get('batter'),row.get('at_bat_number'))
        for target in offense_targets:target['pa'].add(pa)
        for target in defensive_targets:target['pa'].add(pa)
        ev=number(row.get('launch_speed'));angle=number(row.get('launch_speed_angle'));in_play=row.get('type')=='X'
        if ev is not None and in_play:
            for target in (*offense_targets,*defensive_targets):target['bip']+=1;target['ev_sum']+=ev;target['hard_hit']+=int(ev>=95);target['barrels']+=int(angle==6)
        xwoba=number(row.get('estimated_woba_using_speedangle'))
        woba,denom=number(row.get('woba_value')),number(row.get('woba_denom'))
        if xwoba is not None and denom:
            for target in (*offense_targets,*defensive_targets):target['xwoba_sum']+=xwoba;target['xwoba_n']+=1
        if woba is not None and denom:
            for target in (*offense_targets,*defensive_targets):target['woba_sum']+=woba;target['woba_denom']+=denom
        description=row.get('description','');event=row.get('events','')
        whiff=int('swinging_strike' in description)
        for target in offense_targets:target['whiffs']+=whiff
        for target in defensive_targets:target['whiffs']+=whiff
        strikeout=int(event in ('strikeout','strikeout_double_play'));walk=int(event in ('walk','intent_walk'))
        for target in offense_targets:target['strikeouts']+=strikeout;target['walks']+=walk
        for target in defensive_targets:target['strikeouts']+=strikeout;target['walks']+=walk
        velocity=number(row.get('release_speed'))
        if velocity is not None:
            for target in defensive_targets:target['velocity_sum']+=velocity;target['velocity_n']+=1
    output=[]
    for game in games.values():
        def starter(side):
            pitchers=game[side]
            if not pitchers:return None
            pitcher_id,value=min(pitchers.items(),key=lambda item:(item[1]['first_at_bat'] if item[1]['first_at_bat'] is not None else float('inf'),-item[1]['pitches']))
            return {'pitcher_id':int(pitcher_id),'pitcher_hand':value.get('hand'),**finish(value)}
        aggregates=('home','away','home_vs_left','home_vs_right','away_vs_left','away_vs_right','home_pitching','away_pitching')
        players=('home_pitchers','away_pitchers','home_batters','away_batters','home_batters_vs_left','home_batters_vs_right','away_batters_vs_left','away_batters_vs_right')
        output.append({key:value for key,value in game.items() if key not in (*players,*aggregates)}|{key:finish(game[key]) for key in aggregates}|{'home_starter':starter('home_pitchers'),'away_starter':starter('away_pitchers'),'home_pitcher_lines':[{'pitcher_id':int(pid),'pitcher_hand':value.get('hand'),**finish(value)} for pid,value in game['home_pitchers'].items()],'away_pitcher_lines':[{'pitcher_id':int(pid),'pitcher_hand':value.get('hand'),**finish(value)} for pid,value in game['away_pitchers'].items()],'home_batters':[{'batter_id':int(pid),**finish(value)} for pid,value in game['home_batters'].items()],'away_batters':[{'batter_id':int(pid),**finish(value)} for pid,value in game['away_batters'].items()],'home_batters_vs_left':[{'batter_id':int(pid),**finish(value)} for pid,value in game['home_batters_vs_left'].items()],'home_batters_vs_right':[{'batter_id':int(pid),**finish(value)} for pid,value in game['home_batters_vs_right'].items()],'away_batters_vs_left':[{'batter_id':int(pid),**finish(value)} for pid,value in game['away_batters_vs_left'].items()],'away_batters_vs_right':[{'batter_id':int(pid),**finish(value)} for pid,value in game['away_batters_vs_right'].items()]})
    return output

def collect_with_retries(day,pause):
    session=requests.Session();session.headers['User-Agent']='NINTH baseball research (personal, resumable daily aggregate)'
    for attempt in range(4):
        try:return day,collect_day(day,session)
        except Exception as exc:
            if attempt==3:raise
            print(f'{day}: retry {attempt+1} ({exc})',flush=True);time.sleep(2**attempt+pause)

def main(start,end,pause,workers,output=OUTPUT,manifest=MANIFEST):
    output,manifest=Path(output),Path(manifest);DATA.mkdir(parents=True,exist_ok=True);existing={};done=set(manifest.read_text(encoding='utf8').splitlines()) if manifest.exists() else set()
    if output.exists():
        for line in output.read_text(encoding='utf8').splitlines():
            if line.strip():row=json.loads(line);existing[str(row['game_id'])]=row
    target_days=None
    if OFFICIAL_GAMES.exists():
        target_days={row['date'][:10] for row in (json.loads(line) for line in OFFICIAL_GAMES.read_text(encoding='utf8').splitlines() if line.strip()) if start<=row['date'][:10]<=end}
        print(f'Official schedule limits collection to {len(target_days)} game dates',flush=True)
    current=date.fromisoformat(start);finish_date=date.fromisoformat(end);pending=[]
    while current<=finish_date:
        day=current.isoformat()
        if day not in done and (target_days is None or day in target_days):
            pending.append(day)
        current+=timedelta(days=1)
    print(f'Collecting {len(pending)} unfinished game dates with {workers} workers',flush=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as pool,output.open('a',encoding='utf8') as handle:
        futures={pool.submit(collect_with_retries,day,pause):day for day in pending}
        for future in as_completed(futures):
            day=futures[future]
            try:
                _,rows=future.result()
                if target_days is not None and day in target_days and not rows:
                    raise RuntimeError("official completed games exist but Baseball Savant returned no rows; leaving day pending")
                for row in rows:
                    existing[str(row['game_id'])]=row;handle.write(json.dumps(row,separators=(',',':'))+'\n')
                handle.flush();done.add(day);manifest.write_text('\n'.join(sorted(done))+'\n',encoding='utf8');print(f'{day}: {len(rows)} games',flush=True)
            except Exception as exc:print(f'{day}: FAILED ({exc})',flush=True)
    output.write_text('\n'.join(json.dumps(row,separators=(',',':')) for row in sorted(existing.values(),key=lambda x:(x['date'],x['game_id'])))+'\n',encoding='utf8')
    print(f'Saved {len(existing)} Statcast game aggregates to {output}')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--start',required=True);parser.add_argument('--end',required=True);parser.add_argument('--pause',type=float,default=.35);parser.add_argument('--workers',type=int,default=3);parser.add_argument('--output',default=str(OUTPUT));parser.add_argument('--manifest',default=str(MANIFEST));args=parser.parse_args();main(args.start,args.end,args.pause,max(1,min(args.workers,6)),args.output,args.manifest)
