"""Pure domain logic, deliberately independent from Telegram for local tests."""
from datetime import datetime, timezone
import hashlib
import re
import secrets
import time
import unicodedata
from .db import Database


class DomainError(ValueError):
    pass


def utc_day(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).strftime('%Y-%m-%d')


def duration(raw: str) -> int:
    """2h, 30m, 1d, 2ч, 5мин, 1н => seconds. Bot API bans require >=30s."""
    m = re.fullmatch(r'(\d{1,5})\s*(s|sec|m|min|h|d|w|с|сек|м|мин|ч|час|д|день|н|нед)', raw.lower())
    if not m:
        raise DomainError('Срок: 30m / 2h / 1d / 1w (также 30мин, 2ч, 1д).')
    scale = {'s':1,'sec':1,'с':1,'сек':1,'m':60,'min':60,'м':60,'мин':60,
             'h':3600,'ч':3600,'час':3600,'d':86400,'д':86400,'день':86400,
             'w':604800,'н':604800,'нед':604800}
    return int(m[1])*scale[m[2]]


def clean(text: str) -> str:
    return unicodedata.normalize('NFKC', text).casefold().strip()


class Service:
    def __init__(self, db: Database):
        self.db = db

    def record_message(self, chat, user, name='', now=None):
        now = int(time.time() if now is None else now)
        self.db.user(user, name)
        self.db.member(chat, user, name)
        day = utc_day(now)
        with self.db.transaction():
            self.db.run('UPDATE members SET messages=messages+1,last_seen=? WHERE chat_id=? AND user_id=?',
                        (now,chat,user))
            self.db.run('INSERT INTO stats(chat_id,user_id,day,count) VALUES (?,?,?,1) '
                        'ON CONFLICT(chat_id,user_id,day) DO UPDATE SET count=count+1', (chat,user,day))

    def rank(self, chat, user):
        r = self.db.one('SELECT rank FROM members WHERE chat_id=? AND user_id=?', (chat,user))
        return int(r['rank']) if r else 0

    def set_rank(self, chat, actor, target, value, actor_rank):
        if target == actor or value < 0 or value >= actor_rank or not 0 <= value <= 4:
            raise DomainError('Нельзя назначить этот ранг: нужен ранг строго ниже вашего (до 4).')
        if self.rank(chat,target) >= actor_rank:
            raise DomainError('Нельзя менять ранг равного или старшего модератора.')
        self.db.member(chat,target)
        with self.db.transaction():
            self.db.run('UPDATE members SET rank=? WHERE chat_id=? AND user_id=?', (value,chat,target))
            self.db.event(chat,actor,'rank',target,str(value))

    def warnings(self, chat, user, now=None):
        t = int(time.time() if now is None else now)
        return self.db.all('SELECT * FROM warnings WHERE chat_id=? AND user_id=? AND (expires_at=0 OR expires_at>?) ORDER BY id DESC',
                           (chat,user,t))

    def add_warning(self, chat, actor, target, reason='', ttl=7*86400, now=None):
        t = int(time.time() if now is None else now)
        with self.db.transaction():
            self.db.run('INSERT INTO warnings(chat_id,user_id,mod_id,reason,created_at,expires_at) VALUES(?,?,?,?,?,?)',
                        (chat,target,actor,reason[:500],t,t+ttl if ttl else 0))
            self.db.event(chat,actor,'warn',target,reason)
        limit = self.db.one('SELECT warn_limit FROM chats WHERE id=?', (chat,))
        return len(self.warnings(chat,target,t)), limit['warn_limit'] if limit else 3

    def clear_warning(self, chat, actor, target, all_warnings=False):
        with self.db.transaction():
            if all_warnings:
                n = self.db.run('DELETE FROM warnings WHERE chat_id=? AND user_id=?', (chat,target)).rowcount
            else:
                n = self.db.run('DELETE FROM warnings WHERE id=(SELECT id FROM warnings WHERE chat_id=? AND user_id=? ORDER BY id DESC LIMIT 1)', (chat,target)).rowcount
            self.db.event(chat,actor,'unwarn',target,str(n))
        return n

    def daily(self, user, now=None):
        today = utc_day(now)
        self.db.user(user)
        with self.db.transaction():
            r = self.db.one('SELECT last_daily FROM wallet WHERE user_id=?', (user,))
            if r['last_daily'] == today:
                raise DomainError('Сегодня ежедневный бонус уже получен (сброс в 00:00 UTC).')
            self.db.run('UPDATE wallet SET coins=coins+25,last_daily=? WHERE user_id=?', (today,user))
        return self.balance(user)

    def balance(self, user):
        self.db.user(user)
        r = self.db.one('SELECT coins,gold FROM wallet WHERE user_id=?',(user,))
        return (r['coins'], r['gold'])

    def transfer(self, sender, receiver, amount):
        if sender == receiver or not 1 <= amount <= 100_000:
            raise DomainError('Перевод: от 1 до 100000 монет другому пользователю.')
        self.db.user(sender)
        self.db.user(receiver)
        with self.db.transaction():
            taken = self.db.run('UPDATE wallet SET coins=coins-? WHERE user_id=? AND coins>=?',
                                (amount,sender,amount)).rowcount
            if not taken:
                raise DomainError('Недостаточно монет.')
            self.db.run('UPDATE wallet SET coins=coins+? WHERE user_id=?',(amount,receiver))
            self.db.run('INSERT INTO transfers(from_id,to_id,amount,at) VALUES(?,?,?,?)',
                        (sender,receiver,amount,int(time.time())))
        return self.balance(sender)

    def vote(self, sender, target, value=1, now=None):
        if sender == target or value not in (-1,1):
            raise DomainError('Нельзя голосовать за себя.')
        if not self.db.one('SELECT id FROM users WHERE id=?',(target,)):
            raise DomainError('Пользователь должен сначала написать боту или в общий чат.')
        day=utc_day(now)
        with self.db.transaction():
            if self.db.one('SELECT 1 FROM rep_votes WHERE from_id=? AND to_id=? AND day=?', (sender,target,day)):
                raise DomainError('Оценка этому пользователю сегодня уже выставлена.')
            self.db.run('INSERT INTO rep_votes VALUES (?,?,?)',(sender,target,day))
            self.db.run('INSERT INTO reputation(target_id,score) VALUES(?,?) ON CONFLICT(target_id) DO UPDATE SET score=score+excluded.score',(target,value))
        return self.reputation(target)

    def reputation(self, user):
        r=self.db.one('SELECT score FROM reputation WHERE target_id=?',(user,))
        return r['score'] if r else 0

    def exchange(self, user, operation, amount):
        """Internal non-redeemable conversion, not a market or cash exchange."""
        if operation not in ('buy','sell') or not 1 <= amount <= 1000:
            raise DomainError('/exchange buy|sell 1..1000. Покупка 100 монет/золото; продажа 95.')
        self.db.user(user)
        cost = amount * (100 if operation == 'buy' else 95)
        with self.db.transaction():
            if operation == 'buy':
                r = self.db.run('UPDATE wallet SET coins=coins-?,gold=gold+? '
                                'WHERE user_id=? AND coins>=?', (cost,amount,user,cost))
            else:
                r = self.db.run('UPDATE wallet SET gold=gold-?,coins=coins+? '
                                'WHERE user_id=? AND gold>=?', (amount,cost,user,amount))
            if not r.rowcount: raise DomainError('Недостаточно средств для обмена.')
        return self.balance(user)

    def award(self,chat,giver,target,name):
        if not 2 <= len(name) <= 50:
            raise DomainError('Название награды: 2–50 символов.')
        if giver == target:
            raise DomainError('Нельзя наградить себя.')
        self.db.run('INSERT INTO awards(chat_id,target_id,giver_id,name,created_at) VALUES(?,?,?,?,?)',
                    (chat,target,giver,name,int(time.time())))

    def propose(self, sender, target):
        if sender == target or self.spouse(sender) or self.spouse(target):
            raise DomainError('Предложение невозможно: проверьте участников и их семейное положение.')
        with self.db.transaction():
            self.db.run('INSERT OR REPLACE INTO proposals(from_id,to_id,created_at) VALUES(?,?,?)',
                        (sender,target,int(time.time())))

    def spouse(self, user):
        r=self.db.one('SELECT user1,user2 FROM marriages WHERE user1=? OR user2=?',(user,user))
        return (r['user2'] if r['user1']==user else r['user1']) if r else None

    def accept_proposal(self, sender, target):
        """target accepts an incoming proposal from sender."""
        if sender == target:
            raise DomainError('Недопустимое предложение.')
        with self.db.transaction():
            prop=self.db.one('SELECT created_at FROM proposals WHERE from_id=? AND to_id=?',(sender,target))
            if not prop or prop['created_at']+86400<int(time.time()):
                raise DomainError('Активного предложения нет (срок 24 часа).')
            if self.spouse(sender) or self.spouse(target):
                raise DomainError('Один из участников уже состоит в браке.')
            a,b=sorted((sender,target))
            self.db.run('INSERT INTO marriages(user1,user2,at) VALUES(?,?,?)',(a,b,int(time.time())))
            self.db.run('DELETE FROM proposals WHERE from_id=? OR to_id=? OR from_id=? OR to_id=?',
                        (sender,sender,target,target))

    def divorce(self,user):
        with self.db.transaction():
            n=self.db.run('DELETE FROM marriages WHERE user1=? OR user2=?',(user,user)).rowcount
        if not n:
            raise DomainError('Вы не состоите в браке.')

    def create_clan(self,chat,owner,name):
        if not 2<=len(name)<=36 or not re.fullmatch(r'[\w\- ]+',name,re.UNICODE):
            raise DomainError('Название клана: 2–36 букв, цифр, пробелов или дефисов.')
        self.db.user(owner)
        with self.db.transaction():
            if self.db.one('SELECT 1 FROM clan_members WHERE user_id=?',(owner,)):
                raise DomainError('Сначала выйдите из текущего клана.')
            if self.balance(owner)[0]<100:
                raise DomainError('Создание клана стоит 100 монет.')
            try:
                cur=self.db.run('INSERT INTO clans(chat_id,name,owner_id,created_at) VALUES(?,?,?,?)',
                                (chat,name.strip(),owner,int(time.time())))
            except Exception as e:
                if 'UNIQUE' in str(e): raise DomainError('Название клана уже занято в этом чате.') from e
                raise
            self.db.run('UPDATE wallet SET coins=coins-100 WHERE user_id=?',(owner,))
            self.db.run('INSERT INTO clan_members VALUES(?,?,?)',(cur.lastrowid,owner,int(time.time())))
            return cur.lastrowid

    def join_clan(self, user, clan_id, chat):
        with self.db.transaction():
            clan=self.db.one('SELECT * FROM clans WHERE id=? AND chat_id=?',(clan_id,chat))
            if not clan: raise DomainError('Клан не найден в текущем чате.')
            if self.db.one('SELECT 1 FROM clan_members WHERE user_id=?',(user,)):
                raise DomainError('Вы уже состоите в клане.')
            self.db.run('INSERT INTO clan_members VALUES (?,?,?)',(clan_id,user,int(time.time())))
            return clan['name']

    def leave_clan(self, user):
        with self.db.transaction():
            r=self.db.one('SELECT c.owner_id,c.id FROM clan_members cm JOIN clans c ON c.id=cm.clan_id WHERE cm.user_id=?',(user,))
            if not r: raise DomainError('Вы не состоите в клане.')
            if r['owner_id']==user:
                raise DomainError('Владелец должен расформировать клан (/clan_disband).')
            self.db.run('DELETE FROM clan_members WHERE user_id=?',(user,))

    def disband_clan(self,user):
        with self.db.transaction():
            r=self.db.one('SELECT id FROM clans WHERE owner_id=?',(user,))
            if not r: raise DomainError('Вы не владелец клана.')
            self.db.run('DELETE FROM clan_members WHERE clan_id=?',(r['id'],))
            self.db.run('DELETE FROM clans WHERE id=?',(r['id'],))

    def duel_create(self, chat, challenger, opponent, stake):
        if challenger==opponent or not 1<=stake<=1000:
            raise DomainError('Ставка дуэли: 1–1000 виртуальных монет; нельзя вызвать себя.')
        with self.db.transaction():
            if self.balance(challenger)[0]<stake: raise DomainError('Недостаточно монет.')
            self.db.run('UPDATE wallet SET coins=coins-? WHERE user_id=?',(stake,challenger))
            r=self.db.run('INSERT INTO duels(chat_id,challenger,opponent,stake,created_at) VALUES(?,?,?,?,?)',
                          (chat,challenger,opponent,stake,int(time.time())))
            return r.lastrowid

    def duel_reply(self, duel_id, chat, responder, accept):
        with self.db.transaction():
            r=self.db.one('SELECT * FROM duels WHERE id=? AND chat_id=? AND opponent=? AND status="pending"',
                          (duel_id,chat,responder))
            if not r: raise DomainError('Вызов не найден или адресован другому участнику.')
            if not accept or int(time.time())-r['created_at']>3600:
                self.db.run('UPDATE duels SET status="cancelled" WHERE id=?',(duel_id,))
                self.db.run('UPDATE wallet SET coins=coins+? WHERE user_id=?',(r['stake'],r['challenger']))
                return None
            if self.balance(responder)[0]<r['stake']:
                raise DomainError('Недостаточно монет для принятия вызова.')
            self.db.run('UPDATE wallet SET coins=coins-? WHERE user_id=?',(r['stake'],responder))
            winner=secrets.choice([r['challenger'],responder])
            self.db.run('UPDATE wallet SET coins=coins+? WHERE user_id=?',(r['stake']*2,winner))
            self.db.run('UPDATE duels SET status="finished" WHERE id=?',(duel_id,))
            return winner

    def federation_create(self,chat,owner,name):
        if not 3<=len(name)<=60:raise DomainError('Название сети: 3–60 символов.')
        with self.db.transaction():
            if self.db.one('SELECT 1 FROM federation_chats WHERE chat_id=?',(chat,)):
                raise DomainError('Чат уже находится в сети.')
            r=self.db.run('INSERT INTO federations(owner_id,name,created_at) VALUES(?,?,?)',
                          (owner,name.strip(),int(time.time())))
            self.db.run('INSERT INTO federation_chats VALUES(?,?)',(chat,r.lastrowid))
            return r.lastrowid

    def federation(self,chat):
        return self.db.one('SELECT f.* FROM federations f JOIN federation_chats fc ON fc.federation_id=f.id WHERE fc.chat_id=?',(chat,))

    def federation_code(self,chat,owner):
        f=self.federation(chat)
        if not f or f['owner_id']!=owner:raise DomainError('Код может создавать только владелец сети.')
        code=secrets.token_urlsafe(16)
        self.db.run('INSERT INTO federation_codes VALUES (?,?,?)',
                    (hashlib.sha256(code.encode()).hexdigest(),f['id'],int(time.time())+600))
        return code

    def federation_join(self,chat,code):
        digest=hashlib.sha256(code.encode()).hexdigest()
        with self.db.transaction():
            if self.federation(chat):raise DomainError('Чат уже находится в сети.')
            row=self.db.one('SELECT federation_id FROM federation_codes WHERE code_hash=? AND expires_at>?',
                            (digest,int(time.time())))
            if not row:raise DomainError('Код недействителен или истёк.')
            self.db.run('DELETE FROM federation_codes WHERE code_hash=?',(digest,))
            self.db.run('INSERT INTO federation_chats VALUES (?,?)',(chat,row['federation_id']))
            return row['federation_id']

    def federation_leave(self,chat,owner=None):
        with self.db.transaction():
            r=self.federation(chat)
            if not r:raise DomainError('Чат не находится в сети.')
            if owner is not None and r['owner_id']==owner:
                self.db.run('DELETE FROM federation_chats WHERE federation_id=?',(r['id'],))
            else:
                self.db.run('DELETE FROM federation_chats WHERE chat_id=?',(chat,))
            n=self.db.one('SELECT COUNT(*) n FROM federation_chats WHERE federation_id=?',(r['id'],))['n']
            if not n:
                self.db.run('DELETE FROM federation_codes WHERE federation_id=?',(r['id'],))
                self.db.run('DELETE FROM federations WHERE id=?',(r['id'],))

    def due_reminders(self, now=None):
        t=int(time.time() if now is None else now)
        return self.db.all('SELECT * FROM reminders WHERE sent=0 AND due_at<=? ORDER BY due_at LIMIT 30',(t,))

    def raffle_draw(self, giveaway_id):
        with self.db.transaction():
            r=self.db.one('SELECT * FROM giveaways WHERE id=? AND finished=0',(giveaway_id,))
            if not r or r['deadline']>int(time.time()): return None
            rows=self.db.all('SELECT user_id FROM giveaway_entries WHERE giveaway_id=?',(giveaway_id,))
            winner=secrets.choice(rows)['user_id'] if rows else None
            self.db.run('UPDATE giveaways SET winner_id=?,finished=1 WHERE id=?',(winner,giveaway_id))
            return dict(r),winner
