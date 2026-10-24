"""Independent research journal. Reads game data; writes only its own SQLite file.

No ingestion hooks, notifications, source-data updates, or speculative causal claims.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from games.models import GameRound, AlertEvaluation, AlertOccurrence
from . import case_study_analysis as analysis

HISTORY_LIMIT = 150
RESULT_FIELDS = ('pk', 'game_no', 'game_type', 'winning_number', 'reward_numbers',
                 'winner_event_ts', 'pre_event_ts', 'created_at', 'updated_at',
                 'has_winner', 'has_pre', 'status')


def journal_path():
    return Path(getattr(settings, 'CASE_STUDY_DB_PATH', os.environ.get(
        'CASE_STUDY_DB_PATH', str(settings.PROJECT_ROOT / '.local' / 'case-study.sqlite3'))))


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


@contextmanager
def journal(write=False):
    path = journal_path()
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=5)
        db.execute('PRAGMA journal_mode=WAL')
    else:
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        yield db
        if write:
            db.commit()
    finally:
        db.close()


def initialize():
    with journal(True) as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS forecasts (
                id INTEGER PRIMARY KEY, stream TEXT NOT NULL, round_id TEXT NOT NULL,
                created_at TEXT NOT NULL, payload TEXT NOT NULL,
                UNIQUE(stream, round_id));
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY, stream TEXT NOT NULL, round_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL, revision INTEGER NOT NULL,
                observed_at TEXT NOT NULL, logged_at TEXT NOT NULL,
                number INTEGER, mode TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS case_round ON cases(stream, round_id, id);
            CREATE INDEX IF NOT EXISTS case_time ON cases(stream, observed_at);
            CREATE TABLE IF NOT EXISTS scores (
                case_id INTEGER NOT NULL, strategy TEXT NOT NULL, label TEXT NOT NULL,
                top_k INTEGER NOT NULL, hit INTEGER NOT NULL, baseline_hit INTEGER NOT NULL,
                expected REAL NOT NULL, PRIMARY KEY(case_id,strategy,top_k));
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, stream TEXT NOT NULL, round_id TEXT NOT NULL,
                case_id INTEGER, kind TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL);
        ''')


def metadata(db, key, default=None):
    row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    return json.loads(row['value']) if row else default


def set_metadata(db, key, value):
    db.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, encoded(value)))


def production_id(value):
    # Exclude TEST_/GAME_ and other synthetic or unorderable legacy identifiers.
    if not re.fullmatch(r'\d{12,20}', value or ''):
        return False
    try:
        datetime.strptime(value[:8], '%Y%m%d')
    except ValueError:
        return False
    return True


def stream_for(game):
    return game.game_type or 'lucky28'


def source_query(stream):
    query = GameRound.objects.only(*RESULT_FIELDS)
    return query.filter(Q(game_type='lucky28') | Q(game_type='') | Q(game_type__isnull=True)) if stream == 'lucky28' else query.filter(game_type=stream)


def completed(query):
    return query.filter(has_winner=True, winning_number__range=(0, 27), winner_event_ts__isnull=False).filter(Q(status__isnull=True) | Q(status__in=(3, 4)))


def result_record(game):
    return dict(round_id=game.game_no, number=game.winning_number, digits=game.reward_numbers,
                observed_at=game.winner_event_ts.isoformat() if game.winner_event_ts else None,
                received_at=game.updated_at.isoformat())


def prior_history(stream, cutoff, exclude):
    rows = completed(source_query(stream)).filter(winner_event_ts__lt=cutoff).exclude(game_no=exclude).order_by('-winner_event_ts', '-pk')[:HISTORY_LIMIT + 50]
    return list(reversed([result_record(g) for g in rows if production_id(g.game_no)][:HISTORY_LIMIT]))


def prior_alerts(game, cutoff):
    evaluation = AlertEvaluation.objects.filter(game_no=game.game_no, captured_at__lte=cutoff).only('pk', 'captured_at', 'observed_at').first()
    if not evaluation:
        return []
    return [dict(rule=row.rule_key, title=row.snapshot.get('title', row.rule_key),
                 detail=row.snapshot.get('detail', ''), captured_at=evaluation.captured_at.isoformat())
            for row in AlertOccurrence.objects.filter(evaluation=evaluation).only('rule_key', 'snapshot')[:50]]


def make_forecast(game, now):
    stream = stream_for(game)
    history = prior_history(stream, now, game.game_no)
    if history and int(history[-1]['round_id']) >= int(game.game_no):
        return False  # A delayed pre-packet from an older round is not upcoming.
    payload = analysis.forecast(history)
    payload.update(round_id=game.game_no, stream=stream, created_at=now.isoformat(),
                   cutoff_at=history[-1]['observed_at'] if history else None,
                   history=history, pre_observed_at=game.pre_event_ts.isoformat(),
                   prior_alerts=prior_alerts(game, now),
                   timing_note='Saved before local result observation; provider draw/close time is unavailable.',
                   selection_source='Case-study strategies; dashboard manual selections are not captured.')
    # Recheck after computation; a result that arrived during reads is never prospective.
    if GameRound.objects.filter(pk=game.pk, has_winner=True).exists():
        return False
    payload['created_at'] = timezone.now().isoformat()
    with journal(True) as db:
        cursor = db.execute('INSERT OR IGNORE INTO forecasts(stream,round_id,created_at,payload) VALUES (?,?,?,?)',
                            (stream, game.game_no, payload['created_at'], encoded(payload)))
        if cursor.rowcount:
            db.execute('INSERT INTO events(stream,round_id,kind,created_at,payload) VALUES (?,?,?,?,?)',
                       (stream, game.game_no, 'forecast_locked', payload['created_at'], encoded(payload)))
            return True
    return False


def record_case(game, now):
    stream = stream_for(game)
    result = result_record(game)
    history = prior_history(stream, game.winner_event_ts, game.game_no)
    with journal() as db:
        row = db.execute('SELECT payload FROM forecasts WHERE stream=? AND round_id=?', (stream, game.game_no)).fetchone()
        previous = db.execute('SELECT id,fingerprint,revision FROM cases WHERE stream=? AND round_id=? ORDER BY id DESC LIMIT 1', (stream, game.game_no)).fetchone()
    frozen = json.loads(row['payload']) if row else None
    if frozen and parse_datetime(frozen['created_at']) < game.winner_event_ts:
        mode = 'prospective'
        reason = 'Forecast saved before the local observer saw the result. Provider generation time is unavailable.'
        evidence_history = frozen['history']
    else:
        mode = 'late' if frozen else 'retrospective'
        reason = ('Forecast was recorded at or after result observation; excluded from prospective scores.' if frozen else
                  'No forecast recorded before this result. Replayed from earlier saved history; excluded from prospective scores.')
        evidence_history = history
    replay = analysis.forecast(evidence_history) if not frozen else frozen
    explanation = analysis.explain(result, evidence_history, replay,
        evidence_mode='recorded_before_result' if mode == 'prospective' else 'retrospective')
    fingerprint = digest({'result': {k:v for k,v in result.items() if k != 'received_at'},
                          'history': [{k:v for k,v in r.items() if k != 'received_at'} for r in evidence_history], 'forecast': frozen,
                          'analysis_version': replay.get('version')})
    if previous and previous['fingerprint'] == fingerprint:
        return False
    payload = dict(round_id=game.game_no, stream=stream, result=result, forecast=replay,
                   explanation=explanation, mode=mode, eligibility_reason=reason,
                   revision=previous['revision'] + 1 if previous else 1, logged_at=now.isoformat(),
                   fingerprint=fingerprint, history=evidence_history,
                   prior_alerts=frozen.get('prior_alerts', []) if frozen else prior_alerts(game, game.winner_event_ts),
                   timing_note='Observed time is browser receipt time. Received time is the source row last-update time.',
                   selection_source='Case-study strategies; existing dashboard selections are unchanged and not scored here.')
    with journal(True) as db:
        cursor = db.execute('INSERT INTO cases(stream,round_id,fingerprint,revision,observed_at,logged_at,number,mode,payload) VALUES (?,?,?,?,?,?,?,?,?)',
                            (stream, game.game_no, fingerprint, payload['revision'], game.winner_event_ts.isoformat(), now.isoformat(), game.winning_number, mode, encoded(payload)))
        db.execute('INSERT INTO events(stream,round_id,case_id,kind,created_at,payload) VALUES (?,?,?,?,?,?)',
                   (stream, game.game_no, cursor.lastrowid, 'result_revision' if previous else 'result_review', now.isoformat(), encoded(payload)))
        strategies = replay.get('strategies', [])
        if mode != 'late' and strategies:
            baseline = strategies[0]
            for strategy in strategies:
                for k in (1, 3, 5):
                    numbers = strategy['ranked_numbers'][:k]
                    db.execute('INSERT INTO scores VALUES (?,?,?,?,?,?,?)',
                               (cursor.lastrowid, strategy['id'], strategy['name'], k,
                                int(game.winning_number in numbers),
                                int(game.winning_number in baseline['ranked_numbers'][:k]),
                                sum(baseline['probabilities'][n] for n in numbers)))
    return True


def synchronize(now=None):
    """One polling pass. The command holds an exclusive worker lock."""
    now = now or timezone.now()
    initialize()
    with journal() as db:
        cursor = metadata(db, 'cursor')
    streams = sorted({value or 'lucky28' for value in GameRound.objects.values_list('game_type', flat=True).distinct()})
    forecasts = reviews = 0
    for stream in streams:
        pending = source_query(stream).filter(has_pre=True, has_winner=False,
                    pre_event_ts__gte=now-timedelta(seconds=120), pre_event_ts__lte=now).order_by('-pre_event_ts').first()
        if pending and production_id(pending.game_no):
            with journal() as db:
                exists = db.execute('SELECT 1 FROM forecasts WHERE stream=? AND round_id=?', (stream, pending.game_no)).fetchone()
            if not exists:
                forecasts += int(make_forecast(pending, now))
        if cursor:
            changes = list(completed(source_query(stream)).filter(updated_at__gte=parse_datetime(cursor)-timedelta(seconds=2)).order_by('updated_at', 'pk'))
        else:
            changes = list(completed(source_query(stream)).order_by('-winner_event_ts', '-pk')[:150])
        # A late import/correction can change later retrospective explanations.
        # Reconcile the visible history once, without altering frozen live inputs.
        if cursor and any(g.winner_event_ts < now-timedelta(seconds=120) for g in changes):
            by_id = {g.pk:g for g in changes}
            by_id.update({g.pk:g for g in completed(source_query(stream)).order_by('-winner_event_ts', '-pk')[:150]})
            changes = list(by_id.values())
        for game in changes:
            if production_id(game.game_no):
                reviews += int(record_case(game, now))
    with journal(True) as db:
        set_metadata(db, 'cursor', now.isoformat())
        set_metadata(db, 'worker', dict(last_tick=timezone.now().isoformat(), error='', pid=os.getpid()))
    return dict(forecasts=forecasts, reviews=reviews)


def worker_error(message):
    with journal(True) as db:
        set_metadata(db, 'worker', dict(last_tick=None, error=str(message)[:240], pid=os.getpid()))


def latest_cases(db, stream, limit=None):
    sql = '''SELECT c.* FROM cases c JOIN
        (SELECT MAX(id) id FROM cases WHERE stream=? GROUP BY round_id) latest
        ON c.id=latest.id ORDER BY c.observed_at DESC,c.id DESC'''
    return db.execute(sql + (' LIMIT ?' if limit else ''), (stream, limit) if limit else (stream,)).fetchall()


def case_detail(case_id):
    if not journal_path().exists():
        return None
    with journal() as db:
        row = db.execute('SELECT * FROM cases WHERE id=?', (case_id,)).fetchone()
        if not row:
            return None
        payload = json.loads(row['payload'])
        payload['id'] = row['id']
        payload['events'] = [dict(kind=e['kind'], created_at=e['created_at'], case_id=e['case_id']) for e in
            db.execute('SELECT * FROM events WHERE stream=? AND round_id=? ORDER BY id', (row['stream'], row['round_id']))]
        return payload


def performance(db, stream):
    """Score all logged outcomes, keeping retrospective replay separate."""
    result = []
    rows = db.execute('''SELECT s.strategy,s.label,c.mode,s.top_k,COUNT(*) samples,
        SUM(s.hit) hits,SUM(s.baseline_hit) baseline_hits,SUM(s.expected) expected_hits
        FROM scores s JOIN cases c ON c.id=s.case_id
        JOIN (SELECT MAX(id) id FROM cases WHERE stream=? GROUP BY round_id) latest ON latest.id=c.id
        GROUP BY s.strategy,s.label,c.mode,s.top_k ORDER BY c.mode,s.strategy,s.top_k''', (stream,))
    for row in rows:
        values = dict(row)
        count = values['samples']
        result.append(dict(**values,
                           hit_rate=round(values['hits']/count*100, 2),
                           baseline_rate=round(values['baseline_hits']/count*100, 2),
                           lift_pp=round((values['hits']-values['baseline_hits'])/count*100, 2),
                           verdict='Exploratory results; no demonstrated predictive advantage.'))
    return result


def dashboard(stream='lucky28'):
    output = dict(checked_at=timezone.now().isoformat(), stream=stream, streams=[stream],
                  worker=dict(last_tick=None, error='', running=False), pending=[], performance=[], cases=[], totals={})
    if not journal_path().exists():
        return output
    with journal() as db:
        worker = metadata(db, 'worker', output['worker'])
        tick = parse_datetime(worker.get('last_tick') or '')
        worker['running'] = bool(tick and (timezone.now()-tick).total_seconds() < 10 and not worker.get('error'))
        output['worker'] = worker
        output['streams'] = sorted({stream} | {r[0] for r in db.execute('SELECT DISTINCT stream FROM cases UNION SELECT DISTINCT stream FROM forecasts')})
        output['pending'] = [json.loads(r['payload']) for r in db.execute('''SELECT f.payload FROM forecasts f WHERE f.stream=?
            AND f.created_at>=? AND NOT EXISTS(SELECT 1 FROM cases c WHERE c.stream=f.stream AND c.round_id=f.round_id)
            ORDER BY f.created_at DESC LIMIT 1''', (stream, (timezone.now()-timedelta(seconds=180)).isoformat()))]
        rows = latest_cases(db, stream, 150)
        output['performance'] = performance(db, stream)
        output['totals'] = {r['mode']:r['count'] for r in db.execute('''SELECT mode,COUNT(*) count FROM cases c
            JOIN (SELECT MAX(id) id FROM cases WHERE stream=? GROUP BY round_id) latest ON latest.id=c.id GROUP BY mode''', (stream,))}
        for row in rows:
            payload = json.loads(row['payload'])
            output['cases'].append(dict(id=row['id'], round_id=row['round_id'], number=row['number'],
                observed_at=row['observed_at'], logged_at=row['logged_at'], mode=row['mode'], revision=row['revision'],
                classification=payload['explanation'].get('classification'),
                calculation_status=payload['explanation'].get('calculation', {}).get('status', 'unavailable')))
    return output


def export_records(stream='lucky28'):
    """Append-only event export includes every original forecast and every revision."""
    if not journal_path().exists():
        return
    with journal() as db:
        for row in db.execute('SELECT * FROM events WHERE stream=? ORDER BY id', (stream,)):
            yield dict(id=row['id'], stream=row['stream'], round_id=row['round_id'], kind=row['kind'],
                       case_id=row['case_id'], created_at=row['created_at'], payload=json.loads(row['payload']))
