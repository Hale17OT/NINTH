"""Build leakage-safe pregame Statcast features from compact game aggregates."""
import json
from collections import defaultdict,deque
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT/'ml'/'data'/'statcast_games.jsonl';OUTPUT=ROOT/'ml'/'data'/'statcast_contexts.jsonl'
KEYS=('xwoba','xwoba_allowed','hard_hit','barrel','pitching_whiff','velocity')

def state():return {key:deque(maxlen=30) for key in KEYS}
def average(values,size=20):
    sample=list(values)[-size:];return sum(sample)/len(sample) if sample else None
def diff(home,away,key,reverse=False):
    h,a=average(home[key]),average(away[key])
    if h is None or a is None:return None
    return round((a-h) if reverse else (h-a),5)

def main():
    if not SOURCE.exists():raise SystemExit('Run ml/statcast_collect.py first')
    rows=sorted((json.loads(line) for line in SOURCE.read_text(encoding='utf8').splitlines() if line.strip()),key=lambda row:(row['date'],row['game_id']))
    teams=defaultdict(state);output=[]
    for game in rows:
        home,away=teams[game['home_abbr']],teams[game['away_abbr']]
        if len(home['xwoba'])>=10 and len(away['xwoba'])>=10:
            output.append({'game_id':game['game_id'],'date':game['date'],'home_abbr':game['home_abbr'],'away_abbr':game['away_abbr'],'statcast_xwoba_difference':diff(home,away,'xwoba'),'statcast_xwoba_allowed_advantage':diff(home,away,'xwoba_allowed',True),'statcast_hard_hit_difference':diff(home,away,'hard_hit'),'statcast_barrel_difference':diff(home,away,'barrel'),'statcast_pitching_whiff_difference':diff(home,away,'pitching_whiff'),'statcast_velocity_difference':diff(home,away,'velocity')})
        for side,target in (('home',home),('away',away)):
            offense,pitching=game[side],game[f'{side}_pitching']
            values={'xwoba':offense.get('xwoba'),'xwoba_allowed':pitching.get('xwoba'),'hard_hit':offense.get('hard_hit_rate'),'barrel':offense.get('barrel_rate'),'pitching_whiff':pitching.get('whiff_rate'),'velocity':pitching.get('avg_velocity')}
            for key,value in values.items():
                if value is not None:target[key].append(float(value))
    OUTPUT.write_text('\n'.join(json.dumps(row,separators=(',',':')) for row in output)+'\n' if output else '',encoding='utf8')
    print(f'Built {len(output)} leakage-safe pregame Statcast contexts from {len(rows)} games')

if __name__=='__main__':main()
