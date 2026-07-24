from collections import defaultdict, deque
from copy import deepcopy
from datetime import date

FEATURE_NAMES = [
    'elo_difference', 'last_5_win_pct_difference', 'last_10_win_pct_difference',
    'last_20_win_pct_difference', 'last_10_run_margin_difference',
    'last_20_run_margin_difference', 'rolling_runs_scored_difference',
    'rolling_runs_allowed_advantage', 'season_win_pct_difference',
    'pythagorean_win_pct_difference', 'home_away_split_difference',
    'rest_days_difference', 'starter_elo_difference', 'starter_rest_difference',
    'starter_era_difference', 'starter_whip_difference', 'lineup_ops_difference',
    'bullpen_3day_pitches_difference', 'temperature_f', 'wind_speed_mph',
    'context_available', 'prior_season_win_pct_difference',
    'prior_season_pythagorean_difference', 'prior_season_run_margin_difference',
    'shrunk_current_win_pct_difference', 'shrunk_current_pythagorean_difference',
    'shrunk_current_run_margin_difference', 'season_progress',
    'early_prior_strength_interaction', 'mature_current_strength_interaction'
]

def _new_team():
    return {'elo':1500.0,'games':0,'wins':0,'runs_for_total':0,'runs_allowed_total':0,
            'home_games':0,'home_wins':0,'away_games':0,'away_wins':0,
            'results':deque(maxlen=30),'margins':deque(maxlen=30),
            'runs_for':deque(maxlen=30),'runs_allowed':deque(maxlen=30),
            'last_date':None,'bullpen':deque(maxlen=5),'previous_season':{}}

def fresh_state():
    return {'teams':defaultdict(_new_team),'pitchers':{}}

def _team(state, team_id):
    teams, key = state['teams'], str(team_id)
    if key not in teams: teams[key] = _new_team()
    team = teams[key]
    defaults = _new_team()
    for key, value in defaults.items():
        if key not in team: team[key] = value
    for key, size in (('results',30),('margins',30),('runs_for',30),('runs_allowed',30),('bullpen',5)):
        if not isinstance(team[key], deque): team[key] = deque(team[key], maxlen=size)
    return team

def _pitcher(state, pitcher_id):
    if not pitcher_id: return {'elo':1500.0,'starts':0,'last_date':None}
    pitchers = state.setdefault('pitchers', {}); key = str(pitcher_id)
    if key not in pitchers: pitchers[key] = {'elo':1500.0,'starts':0,'last_date':None}
    return pitchers[key]

def _rate(values, size):
    sample=list(values)[-size:]; return sum(sample)/len(sample) if sample else .5

def _avg(values, size):
    sample=list(values)[-size:]; return sum(sample)/len(sample) if sample else 0.0

def _rest(last_date, game_date, default=3.0, cap=10):
    return default if not last_date else float(max(0,min(cap,(date.fromisoformat(game_date)-date.fromisoformat(last_date)).days-1)))

def _bullpen(team, game_date):
    target=date.fromisoformat(game_date)
    return sum(float(pitches) for day,pitches in team.get('bullpen',[]) if 0<(target-date.fromisoformat(day)).days<=3)

def _pythagorean(team):
    scored, allowed = float(team.get('runs_for_total',0)), float(team.get('runs_allowed_total',0))
    if not scored and not allowed: return .5
    exponent=1.83; return scored**exponent/max(1e-9,scored**exponent+allowed**exponent)

def _season_strength(value):
    games=float(value.get('games',0));wins=float(value.get('wins',0));scored=float(value.get('runs_for_total',0));allowed=float(value.get('runs_allowed_total',0))
    win=(wins+10)/(games+20);exponent=1.83;pyth=(scored+90)**exponent/((scored+90)**exponent+(allowed+90)**exponent);margin=(scored-allowed)/(games+20)
    return win,pyth,margin

def matchup_features(state, home_id, away_id, game_date, context=None):
    home,away=_team(state,home_id),_team(state,away_id); context=context or {}
    hc,ac=context.get('home',{}),context.get('away',{}); weather=context.get('weather',{})
    hs=home['wins']/home['games'] if home['games'] else .5; aws=away['wins']/away['games'] if away['games'] else .5
    home_split=home['home_wins']/home['home_games'] if home['home_games'] else .5
    away_split=away['away_wins']/away['away_games'] if away['away_games'] else .5
    hp,ap=_pitcher(state,hc.get('starter_id')),_pitcher(state,ac.get('starter_id'))
    home_bullpen=float(hc.get('bullpen_recent_pitches',_bullpen(home,game_date))); away_bullpen=float(ac.get('bullpen_recent_pitches',_bullpen(away,game_date)))
    home_prior,away_prior=_season_strength(home.get('previous_season',{})),_season_strength(away.get('previous_season',{}))
    home_current,away_current=_season_strength(home),_season_strength(away);progress=min(1.0,min(home['games'],away['games'])/80.0)
    return [
        (home['elo']+35)-away['elo'], _rate(home['results'],5)-_rate(away['results'],5),
        _rate(home['results'],10)-_rate(away['results'],10), _rate(home['results'],20)-_rate(away['results'],20),
        _avg(home['margins'],10)-_avg(away['margins'],10), _avg(home['margins'],20)-_avg(away['margins'],20),
        _avg(home['runs_for'],20)-_avg(away['runs_for'],20), _avg(away['runs_allowed'],20)-_avg(home['runs_allowed'],20),
        hs-aws, _pythagorean(home)-_pythagorean(away), home_split-away_split,
        _rest(home['last_date'],game_date)-_rest(away['last_date'],game_date), hp['elo']-ap['elo'],
        _rest(hp['last_date'],game_date,5)-_rest(ap['last_date'],game_date,5),
        float(ac.get('starter_era',4.5))-float(hc.get('starter_era',4.5)),
        float(ac.get('starter_whip',1.35))-float(hc.get('starter_whip',1.35)),
        float(hc.get('lineup_ops',.710))-float(ac.get('lineup_ops',.710)), away_bullpen-home_bullpen,
        float(weather.get('temperature',65)), float(weather.get('wind_speed',0)), float(context.get('context_available',0)),
        home_prior[0]-away_prior[0],home_prior[1]-away_prior[1],home_prior[2]-away_prior[2],
        home_current[0]-away_current[0],home_current[1]-away_current[1],home_current[2]-away_current[2],progress,
        (1-progress)*(home_prior[1]-away_prior[1]),progress*(home_current[1]-away_current[1])
    ]

def apply_result(state, game, context=None):
    home,away=_team(state,game['home_id']),_team(state,game['away_id'])
    home_score,away_score=int(game['home_score']),int(game['away_score']); home_win=int(home_score>away_score)
    expected=1/(1+10**((away['elo']-(home['elo']+35))/400)); change=20*(home_win-expected)
    home['elo']+=change; away['elo']-=change; margin=home_score-away_score
    for side,team,won,team_margin,scored,allowed in (
        ('home',home,home_win,margin,home_score,away_score),('away',away,1-home_win,-margin,away_score,home_score)):
        team['games']+=1;team['wins']+=won;team['runs_for_total']+=scored;team['runs_allowed_total']+=allowed
        team[f'{side}_games']+=1;team[f'{side}_wins']+=won
        team['results'].append(won);team['margins'].append(team_margin);team['runs_for'].append(scored);team['runs_allowed'].append(allowed);team['last_date']=game['date']
        if context:team['bullpen'].append((game['date'],context.get(side,{}).get('bullpen_pitches',0)))
    if context:
        hp,ap=_pitcher(state,context.get('home',{}).get('starter_id')),_pitcher(state,context.get('away',{}).get('starter_id'))
        pexpected=1/(1+10**((ap['elo']-hp['elo'])/400)); pchange=8*(home_win-pexpected)
        hp['elo']+=pchange;ap['elo']-=pchange
        for pitcher in (hp,ap):pitcher['starts']+=1;pitcher['last_date']=game['date']

def reset_season_records(state):
    for team in state['teams'].values():
        team['previous_season']={key:team.get(key,0) for key in ('games','wins','runs_for_total','runs_allowed_total')}
        for key in ('games','wins','runs_for_total','runs_allowed_total','home_games','home_wins','away_games','away_wins'):team[key]=0

def serializable_state(state):
    output=deepcopy(state);output['teams']=dict(output['teams'])
    for team in output['teams'].values():
        for key in ('results','margins','runs_for','runs_allowed','bullpen'):team[key]=list(team.get(key,[]))
    return output
