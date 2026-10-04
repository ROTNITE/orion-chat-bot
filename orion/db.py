"""SQLite repository. All transactions are synchronous and never contain an await.

For one polling worker / single process only; do not deploy multiple replicas with SQLite.
"""
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path: str = ':memory:'):
        if path != ':memory:':
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, isolation_level=None, check_same_thread=True)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.execute('PRAGMA busy_timeout=5000')
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf8'))

    @contextmanager
    def transaction(self):
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            yield
        except BaseException:
            self.conn.execute('ROLLBACK')
            raise
        else:
            self.conn.execute('COMMIT')

    def one(self, sql, args=()):
        return self.conn.execute(sql, args).fetchone()

    def all(self, sql, args=()):
        return self.conn.execute(sql, args).fetchall()

    def run(self, sql, args=()):
        return self.conn.execute(sql, args)

    def user(self, uid, name='', username=None):
        # Never replace known names with blanks from indirect interactions.
        self.run('INSERT INTO users(id,name,username,created_at) VALUES (?,?,?,?) '
                 'ON CONFLICT(id) DO UPDATE SET name=CASE WHEN excluded.name!="" THEN excluded.name ELSE users.name END, '
                 'username=CASE WHEN ? THEN excluded.username ELSE users.username END',
                 (uid, name[:180], (username or '').lower()[:60], int(time.time()), username is not None))
        self.run('INSERT OR IGNORE INTO wallet(user_id) VALUES (?)', (uid,))

    def chat(self, cid, title='', owner=0):
        self.run('INSERT INTO chats(id,title,owner_id,created_at) VALUES(?,?,?,?) '
                 'ON CONFLICT(id) DO UPDATE SET title=CASE WHEN excluded.title!="" THEN excluded.title ELSE chats.title END, '
                 'owner_id=CASE WHEN excluded.owner_id!=0 THEN excluded.owner_id ELSE chats.owner_id END',
                 (cid, title[:256], owner, int(time.time())))

    def member(self, cid, uid, name=''):
        self.run('INSERT INTO members(chat_id,user_id,name) VALUES(?,?,?) '
                 'ON CONFLICT(chat_id,user_id) DO UPDATE SET name=CASE WHEN excluded.name!="" THEN excluded.name ELSE members.name END',
                 (cid, uid, name[:180]))

    def event(self, cid, actor, action, target=None, detail=''):
        self.run('INSERT INTO audit(chat_id,actor_id,action,target_id,detail,at) VALUES(?,?,?,?,?,?)',
                 (cid, actor, action, target, str(detail)[:1000], int(time.time())))

    def close(self):
        self.conn.close()
