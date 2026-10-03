import os
import sqlite3
from pathlib import Path
from flask import current_app, g


def connection():
    if 'db' not in g:
        if current_app.config['DB_ENGINE'] == 'firebird':
            from firebird.driver import connect
            g.db = connect(os.environ['FIREBIRD_DATABASE'], user=os.environ['FIREBIRD_USER'], password=os.environ['FIREBIRD_PASSWORD'], charset='UTF8')
        else:
            Path(current_app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
            g.db = sqlite3.connect(current_app.config['DATABASE'], timeout=15)
    return g.db


def query(sql, args=(), one=False):
    cur = connection().cursor()
    try:
        cur.execute(sql, args)
        columns = [d[0].lower() for d in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return (rows[0] if rows else None) if one else rows
    finally:
        cur.close()


def execute(sql, args=()):
    db = connection()
    cur = db.cursor()
    try:
        cur.execute(sql, args)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()


def init_db():
    engine = current_app.config['DB_ENGINE']
    source = Path(__file__).parent.parent / 'database' / f'{engine}.sql'
    db = connection()
    try:
        for statement in source.read_text(encoding='utf-8').split(';'):
            if statement.strip():
                cur = db.cursor()
                try:
                    cur.execute(statement)
                finally:
                    cur.close()
        db.commit()
    except Exception:
        db.rollback()
        raise


def close_db(error=None):
    db = g.pop('db', None)
    if db:
        db.close()
