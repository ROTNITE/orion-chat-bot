"""Telegram transport and Russian chat commands. aiogram 3.31; single polling worker.

All game assets/currencies are locally generated, free and non-redeemable.
"""
import asyncio
from collections import defaultdict, deque
from datetime import datetime, timezone
import logging
import re
import time
from dataclasses import dataclass

from aiogram import Bot, Dispatcher, Router, F
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (Message, ChatMemberUpdated, BotCommand, ChatPermissions)

from .config import Config
from .network import create_bot
from .db import Database
from .services import Service, DomainError, duration, clean

log = logging.getLogger(__name__)
GROUP = ('group','supergroup')
DURATION = re.compile(r'^\d{1,5}(?:s|sec|m|min|h|d|w|с|сек|м|мин|ч|час|д|день|н|нед)$',re.I)
LINK = re.compile(r'(?:https?://|t\.me/|telegram\.me/|www\.)',re.I)
SIMPLE_NAME = re.compile(r'^[\w\-]{1,32}$',re.U)

HELP = """ОРИОН — бот управления сообществами

Общие: /help /id /profile /bio /title /stats /top /chat /rules /rank_list /warnings
Модерация: /warn /unwarn /mute /unmute /ban /unban /kick /purge /audit /setrank
Настройки: /settings /setwelcome /setrules /setlog /setwarnlimit /antispam /antilinks /anticaps /flood /antiraid /filter_add /filter_del /filters /access /command_add /command_del /commands /note_add /note_del /note
Экономика: /wallet /daily /give /exchange /rich /rep /reputation
Социальные: /marry /accept /divorce /spouse /clan_create /clan_join /clan_leave /clan_disband /clans /award /awards
Игры: /duel /duel_accept /duel_decline /dice /coin
Утилиты: /report /bookmark /bookmarks /remind /reminders /raffle /raffle_join /raffles /poll /timer /timers /fed_info /mydata /forgetme /health

Для наказаний ответьте командой на сообщение участника или укажите ID; @username работает только для ранее замеченных участников. Примеры: /warn (ответом), /mute 2h (ответом), /ban 1234567 1d спам, /give 1234567 20. Русские алиасы: !бан, !варн, !мут, !кик, !профиль, !баланс, !топ, !админы, !ириска (бонус). Полная таблица — в docs/COMMANDS.md.
"""


@dataclass
class Ctx:
    msg: Message
    bot: Bot
    svc: Service
    name: str
    args: list[str]
    rank: int
    raw: str
    @property
    def db(self): return self.svc.db
    @property
    def uid(self): return self.msg.from_user.id
    @property
    def cid(self): return self.msg.chat.id
    @property
    def group(self): return self.msg.chat.type in GROUP
    async def say(self, text):
        return await self.msg.answer(str(text)[:3900], parse_mode=None)


class Orion:
    def __init__(self, config: Config, db: Database):
        self.config=config
        self.svc=Service(db)
        self.router=Router(name='orion')
        self.router.message.register(self.on_join, F.new_chat_members)
        self.router.message.register(self.on_message)
        self.router.chat_member.register(self.on_chat_member)
        self.bot_id=0
        self.bot_username=''
        self.flood=defaultdict(deque)
        self.repeats={}
        self.joins=defaultdict(deque)
        self.raid_until={}
        self.cooldown={}
        self.handlers={}
        self.hard_floors={}
        self.group_only=set()
        self._register()

    def add(self, names, handler, rank=0, group=False):
        for name in names.split():
            self.handlers[name]=handler
            self.hard_floors[name]=rank
            if group: self.group_only.add(name)

    def _register(self):
        a=self.add
        a('help start помощь команды',self.help)
        a('id ид',self.id)
        a('health',self.health)
        a('profile профиль анкета',self.profile)
        a('bio',self.bio)
        a('title',self.title)
        a('mydata',self.mydata)
        a('forgetme',self.forgetme)
        a('chat чат',self.chat_info,group=True)
        a('stats статистика',self.stats,group=True)
        a('top топ',self.top,group=True)
        a('rules правила',self.rules,group=True)
        a('rank_list админы модеры',self.rank_list,group=True)
        a('warnings варны',self.warnings,group=True)
        a('settings настройки',self.settings,rank=2,group=True)
        a('setrank ранг модер',self.setrank,rank=4,group=True)
        a('warn варн пред',self.warn,rank=1,group=True)
        a('unwarn снятьварн',self.unwarn,rank=1,group=True)
        a('mute мут',self.mute,rank=2,group=True)
        a('unmute размут',self.unmute,rank=2,group=True)
        a('ban бан',self.ban,rank=3,group=True)
        a('unban разбан',self.unban,rank=3,group=True)
        a('kick кик',self.kick,rank=2,group=True)
        a('purge очистить',self.purge,rank=3,group=True)
        a('audit журнал',self.audit,rank=3,group=True)
        a('setwelcome приветствие',self.setwelcome,rank=3,group=True)
        a('setrules',self.setrules,rank=3,group=True)
        a('setlog',self.setlog,rank=4,group=True)
        a('setwarnlimit',self.setwarnlimit,rank=3,group=True)
        a('antispam',self.toggle,rank=3,group=True)
        a('antilinks',self.toggle,rank=3,group=True)
        a('anticaps',self.toggle,rank=3,group=True)
        a('flood',self.flood_cmd,rank=3,group=True)
        a('antiraid',self.antiraid,rank=4,group=True)
        a('filter_add',self.filter_add,rank=3,group=True)
        a('filter_del',self.filter_del,rank=3,group=True)
        a('filters',self.filters,rank=2,group=True)
        a('access дк',self.access,rank=4,group=True)
        a('command_add',self.command_add,rank=3,group=True)
        a('command_del',self.command_del,rank=3,group=True)
        a('commands',self.commands,group=True)
        a('note_add',self.note_add,rank=2,group=True)
        a('note_del',self.note_del,rank=2,group=True)
        a('note',self.note,group=True)
        a('wallet баланс кошелек',self.wallet)
        a('daily ириска бонус',self.daily)
        a('give передать',self.give)
        a('rich богачи',self.rich)
        a('exchange обмен',self.exchange)
        a('rep реп',self.rep)
        a('reputation репутация',self.reputation)
        a('marry брак',self.marry,group=True)
        a('accept принятьбрак',self.accept,group=True)
        a('divorce развод',self.divorce)
        a('spouse супруг',self.spouse)
        a('clan_create',self.clan_create,group=True)
        a('clan_join',self.clan_join,group=True)
        a('clan_leave',self.clan_leave)
        a('clan_disband',self.clan_disband)
        a('clans',self.clans,group=True)
        a('award наградить',self.award,rank=2,group=True)
        a('awards награды',self.awards,group=True)
        a('duel дуэль',self.duel,group=True)
        a('duel_accept',self.duel_accept,group=True)
        a('duel_decline',self.duel_decline,group=True)
        a('dice куб',self.dice)
        a('coin монета',self.coin)
        a('report репорт',self.report,group=True)
        a('bookmark закладка',self.bookmark,group=True)
        a('bookmarks закладки',self.bookmarks)
        a('remind напомни',self.remind)
        a('reminders напоминания',self.reminders)
        a('raffle розыгрыш',self.raffle,rank=2,group=True)
        a('timer',self.timer,rank=3,group=True)
        a('timers',self.timers,rank=2,group=True)
        a('timer_off',self.timer_off,rank=3,group=True)
        a('fed_create',self.fed_create,rank=5,group=True)
        a('fed_code',self.fed_code,rank=5,group=True)
        a('fed_join',self.fed_join,rank=5,group=True)
        a('fed_leave',self.fed_leave,rank=5,group=True)
        a('fed_info',self.fed_info,rank=2,group=True)
        a('fed_ban',self.fed_ban,rank=4,group=True)
        a('fed_unban',self.fed_unban,rank=4,group=True)
        a('raffle_join участвовать',self.raffle_join,group=True)
        a('raffles розыгрыши',self.raffles,group=True)
        a('poll опрос',self.poll,rank=2,group=True)

    def parse(self,text):
        if not text:return None
        t=text.strip()
        if t.lower().startswith('орион '): t=t[6:].strip()
        elif t.startswith(('/','!','.')): t=t[1:].strip()
        else:return None
        head,_,tail=t.partition(' ')
        if '@' in head:
            word,mention=head.split('@',1)
            if self.bot_username and mention.lower()!=self.bot_username.lower(): return None
            head=word
        name=head.casefold()
        if not name or name not in self.handlers:return None
        return name,tail.strip()

    async def actual_rank(self, bot, cid, uid):
        obj=await bot.get_chat_member(cid,uid)
        if obj.status=='creator':return 5
        if obj.status=='administrator':return 4
        if obj.status in ('left','kicked'):
            # Local rank must not survive membership loss to enable remote control.
            return 0
        return self.svc.rank(cid,uid)

    async def on_chat_member(self, event: ChatMemberUpdated):
        # Avoid retaining stale delegated authority when the user leaves the group.
        if event.new_chat_member.status in ('left','kicked'):
            uid=event.new_chat_member.user.id
            self.svc.db.run('UPDATE members SET rank=0 WHERE chat_id=? AND user_id=?',(event.chat.id,uid))

    async def on_join(self,msg: Message,bot: Bot):
        if not msg.new_chat_members or msg.chat.type not in GROUP:return
        d=self.svc.db
        d.chat(msg.chat.id,msg.chat.title or '')
        now=time.monotonic()
        q=self.joins[msg.chat.id]
        for member in msg.new_chat_members:
            if member.is_bot:continue
            d.user(member.id,member.full_name,member.username or '')
            d.member(msg.chat.id,member.id,member.full_name)
            q.append(now)
        while q and now-q[0]>60:q.popleft()
        setting=d.one('SELECT * FROM chats WHERE id=?',(msg.chat.id,))
        # Raid protection is opt-in; do not automatically ban legitimate new users by default.
        if setting['raid_limit'] and len(q)>=setting['raid_limit']:
            self.raid_until[msg.chat.id]=now+120
            await self.log_action(bot,msg.chat.id,'Антирейд: обнаружен всплеск входов, защита новых входов на 2 мин.')
        if now<self.raid_until.get(msg.chat.id,0):
            for m in msg.new_chat_members:
                if m.is_bot:continue
                try:
                    await bot.ban_chat_member(msg.chat.id,m.id,until_date=int(time.time())+3600)
                except TelegramAPIError:log.warning('Antiraid ban failed for chat=%s',msg.chat.id)
            return
        for member in msg.new_chat_members[:5]:
            if member.id==self.bot_id:
                await msg.answer('Орион подключён. Выдайте права администратора на удаление сообщений, муты и блокировки. /help')
            else:
                welcome=setting['welcome'].replace('{name}',member.full_name).replace('{id}',str(member.id))
                if welcome: await msg.answer(welcome[:3000],parse_mode=None)

    async def on_message(self,msg:Message,bot:Bot):
        if not msg.from_user or msg.from_user.is_bot or msg.sender_chat:
            return
        db=self.svc.db
        db.user(msg.from_user.id,msg.from_user.full_name,msg.from_user.username or '')
        group=msg.chat.type in GROUP
        if group:
            db.chat(msg.chat.id,msg.chat.title or '')
            self.svc.record_message(msg.chat.id,msg.from_user.id,msg.from_user.full_name)
        command=self.parse(msg.text or msg.caption or '')
        if group and await self.automod(msg,bot, bool(command)):
            return
        if not command:
            if group and msg.text:
                await self.custom_reply(msg)
            return
        name,raw=command
        try:rank=await self.actual_rank(bot,msg.chat.id,msg.from_user.id) if group else 0
        except TelegramAPIError:
            log.exception('Rank lookup failed in chat=%s',msg.chat.id)
            await msg.answer('Не удалось определить права участника. Проверьте права бота.')
            return
        ctx=Ctx(msg,bot,self.svc,name,raw.split(),rank,raw)
        if name in self.group_only and not group:
            await ctx.say('Эта команда работает только в группе.');return
        if group:
            override=db.one('SELECT min_rank FROM command_access WHERE chat_id=? AND command=?',
                            (msg.chat.id,name))
            minimum=self.hard_floors[name]
            if override:
                if override['min_rank']==-1:
                    await ctx.say('Команда отключена администрацией.');return
                minimum=max(minimum,override['min_rank'])
            if rank<minimum:
                await ctx.say(f'Недостаточно прав: требуется ранг {minimum}, у вас {rank}.');return
        elif self.hard_floors[name]>0:
            await ctx.say('Команда доступна только администраторам в группе.');return
        # Simple per-user cooldown for economy/free-form responses; moderation commands not throttled.
        if name in {'daily','give','rep','marry','accept','duel','duel_accept','dice','coin','report'}:
            key=(msg.from_user.id,name)
            now=time.monotonic()
            if now-self.cooldown.get(key,0)<2.0:
                await ctx.say('Не чаще одного раза в 2 секунды.');return
            self.cooldown[key]=now
        try:
            await self.handlers[name](ctx)
        except DomainError as exc:
            await ctx.say(f'Ошибка: {exc}')
        except (ValueError,IndexError) as exc:
            await ctx.say(f'Неверные аргументы. Смотрите /help. {str(exc)[:180]}')
        except TelegramAPIError as exc:
            log.warning('Telegram API error in %s chat=%s: %s',name,msg.chat.id,exc)
            await ctx.say('Telegram не выполнил действие. Проверьте права бота и статус участника.')
        except Exception:
            log.exception('Unhandled command %s chat=%s',name,msg.chat.id)
            await ctx.say('Внутренняя ошибка. Подробнее в серверном логе.')

    async def automod(self,msg,bot, is_command=False):
        db=self.svc.db
        config=db.one('SELECT * FROM chats WHERE id=?',(msg.chat.id,))
        if not config or not config['antispam']:return False
        # Do not delete the Telegram owner's or any administrator's messages.
        # For performance, check status only on a possible rule violation.
        user=msg.from_user.id
        raw=msg.text or msg.caption or ''
        now=time.monotonic()
        key=(msg.chat.id,user)
        dq=self.flood[key]
        dq.append(now)
        while dq and now-dq[0]>10:dq.popleft()
        if len(self.flood)>20000:
            # Bound in-memory storage on a long-lived bot.
            self.flood={k:v for k,v in self.flood.items() if v and now-v[-1]<60}
        norm=clean(raw)
        prev=self.repeats.get(key)
        count=(prev[1]+1 if prev and prev[0]==norm and now-prev[2]<60 else 1)
        self.repeats[key]=(norm,count,now)
        if len(self.repeats)>20000:
            self.repeats={k:v for k,v in self.repeats.items() if now-v[2]<60}
        reason=None
        if is_command:return False
        if config['flood_limit'] and len(dq)>config['flood_limit']: reason='флуд'
        if raw and count>=4 and len(norm)>8:reason='повтор сообщений'
        if config['links'] and LINK.search(raw):reason='ссылки запрещены'
        letters=[x for x in raw if x.isalpha()]
        if config['caps'] and len(letters)>=12 and sum(x.isupper() for x in letters)/len(letters)>.8:
            reason='CAPS'
        filters=db.all('SELECT phrase FROM filters WHERE chat_id=?',(msg.chat.id,))
        if any(clean(row['phrase']) in norm for row in filters):reason='запрещённая фраза'
        if not reason:return False
        try:member=await bot.get_chat_member(msg.chat.id,user)
        except TelegramAPIError:
            log.warning('Automod rank lookup failed chat=%s',msg.chat.id)
            return False
        if member.status in ('creator','administrator') or self.svc.rank(msg.chat.id,user)>0:
            return False
        try:
            await msg.delete()
        except TelegramAPIError:log.warning('Could not delete violating message chat=%s',msg.chat.id)
        n,limit=self.svc.add_warning(msg.chat.id,self.bot_id,user,reason)
        if n>=limit:
            try:
                await bot.ban_chat_member(msg.chat.id,user,until_date=int(time.time())+3600)
                await self.log_action(bot,msg.chat.id,f'Автобан {user} на 1 час: {reason}; предупреждений {n}.')
            except TelegramAPIError:log.warning('Autoban failed for %s',user)
        return True

    async def custom_reply(self,msg):
        # Exact prefix match only; prevent shadowing admin commands.
        t=clean(msg.text)
        r=self.svc.db.one('SELECT response FROM custom_commands WHERE chat_id=? AND trigger=?',(msg.chat.id,t))
        if r:await msg.answer(r['response'],parse_mode=None)

    async def log_action(self,bot,cid,text):
        r=self.svc.db.one('SELECT log_chat_id FROM chats WHERE id=?',(cid,))
        if r and r['log_chat_id']:
            try:await bot.send_message(r['log_chat_id'],f'[Чат {cid}] {text}'[:3900])
            except TelegramAPIError:log.warning('Cannot deliver moderation log for chat=%s',cid)

    async def target(self,c:Ctx,require_member=True):
        # ID or a previously observed username. A reply takes priority when no explicit target.
        args=c.args.copy()
        target=None
        if args and (re.fullmatch(r'\d{4,20}',args[0]) or args[0].startswith('@')):
            token=args.pop(0)
            if token.startswith('@'):
                if not c.group:raise DomainError('Поиск по @username доступен в группе.')
                r=c.db.one('SELECT u.id FROM users u JOIN members m ON m.user_id=u.id '
                           'WHERE u.username=? AND m.chat_id=? ORDER BY m.last_seen DESC LIMIT 1',
                           (token[1:].lower(),c.cid))
                if not r:raise DomainError('Неизвестный @username. Ответьте командой на сообщение участника.')
                target=r['id']
            else:target=int(token)
        elif c.msg.reply_to_message and c.msg.reply_to_message.from_user:
            target=c.msg.reply_to_message.from_user.id
        if target is None:raise DomainError('Ответьте на сообщение участника или укажите его числовой ID.')
        if target<=0:raise DomainError('Некорректный ID.')
        if require_member and c.group:
            m=await c.bot.get_chat_member(c.cid,target)
            if m.status in ('left','kicked'):
                raise DomainError('Пользователь не находится в этом чате.')
        return target,args

    @staticmethod
    def safe_ban_duration(secs):
        # Telegram interprets periods shorter than 30 s or >366 d as forever.
        # Add a margin for clock rounding and network latency.
        if secs and not (60 <= secs <= 365*86400):
            raise DomainError('Срок временного наказания: от 1 минуты до 365 дней.')
        return secs

    async def protected(self,c,uid):
        if uid in (c.uid,self.bot_id) or uid<=0:
            raise DomainError('Нельзя применять команду к себе или боту.')
        m=await c.bot.get_chat_member(c.cid,uid)
        if m.status in ('creator','administrator'):
            raise DomainError('Telegram запрещает управлять администраторами через бота.')
        if self.svc.rank(c.cid,uid)>=c.rank:
            raise DomainError('Нельзя применять наказание к равному или старшему модератору.')

    async def help(self,c):await c.say(HELP)
    async def health(self,c):
        if self.config.owner_id and c.uid!=self.config.owner_id:
            raise DomainError('Доступно только владельцу сервера.')
        await c.say('OK: polling, SQLite и диспетчер работают.')
    async def id(self,c):
        if c.msg.reply_to_message and c.msg.reply_to_message.from_user:
            await c.say(f'ID участника: {c.msg.reply_to_message.from_user.id}')
        else:await c.say(f'Ваш ID: {c.uid}\nID чата: {c.cid}')
    async def profile(self,c):
        uid,args=await self.target(c,False) if c.args or c.msg.reply_to_message else (c.uid,[])
        r=c.db.one('SELECT name,username,bio,title FROM users WHERE id=?',(uid,))
        if not r:raise DomainError('Профиль пока неизвестен боту.')
        chat_line=f'Сообщений здесь: {c.db.one("SELECT messages FROM members WHERE chat_id=? AND user_id=?",(c.cid,uid))[0]}' if c.group and c.db.one('SELECT messages FROM members WHERE chat_id=? AND user_id=?',(c.cid,uid)) else ''
        await c.say(f'Профиль {r["name"]}\nID: {uid}\n@{r["username"] or "нет"}\nСтатус: {r["title"] or "—"}\nО себе: {r["bio"] or "—"}\nРепутация: {self.svc.reputation(uid)}\n{chat_line}')
    async def bio(self,c):
        if not 1<=len(c.raw)<=200:raise DomainError('Пример: /bio Люблю музыку (1–200 символов).')
        c.db.run('UPDATE users SET bio=? WHERE id=?',(c.raw,c.uid));await c.say('Описание обновлено.')
    async def title(self,c):
        if not 1<=len(c.raw)<=50:raise DomainError('Пример: /title Исследователь (1–50 символов).')
        c.db.run('UPDATE users SET title=? WHERE id=?',(c.raw,c.uid));await c.say('Звание обновлено.')
    async def mydata(self,c):
        r=c.db.one('SELECT * FROM users WHERE id=?',(c.uid,))
        money=self.svc.balance(c.uid)
        await c.say(f'Ваши данные (без чужих сообщений): ID {c.uid}; имя {r["name"]}; @{r["username"]}; био: {r["bio"]}; звание: {r["title"]}; монеты: {money[0]}, золото: {money[1]}. Для удаления профиля обращайтесь к оператору экземпляра бота; модерационные журналы сохраняются по политике сообщества.')
    async def forgetme(self,c):
        if c.raw != 'CONFIRM':
            raise DomainError('/forgetme CONFIRM удалит профиль, статистику, кошелёк и социальные данные без восстановления. Журналы модерации и жалобы остаются в сообществах; это НЕ полное удаление идентификатора. Уточните политику у владельца экземпляра.')
        with c.db.transaction():
            uid=c.uid
            c.db.run('UPDATE users SET name="Удалённый профиль",username="",bio="",title="" WHERE id=?',(uid,))
            c.db.run('DELETE FROM stats WHERE user_id=?',(uid,))
            c.db.run('UPDATE members SET name="Удалённый профиль",messages=0 WHERE user_id=?',(uid,))
            c.db.run('DELETE FROM wallet WHERE user_id=?',(uid,))
            c.db.run('DELETE FROM reputation WHERE target_id=?',(uid,))
            c.db.run('DELETE FROM rep_votes WHERE from_id=? OR to_id=?',(uid,uid))
            c.db.run('DELETE FROM proposals WHERE from_id=? OR to_id=?',(uid,uid))
            c.db.run('DELETE FROM marriages WHERE user1=? OR user2=?',(uid,uid))
            c.db.run('DELETE FROM bookmarks WHERE user_id=?',(uid,))
            c.db.run('DELETE FROM reminders WHERE user_id=?',(uid,))
            c.db.run('DELETE FROM giveaway_entries WHERE user_id=?',(uid,))
            # Historical moderation, ownership and transfer/audit references retained.
        await c.say('Профиль и персональная статистика обезличены. История модерации и операций в сообществах сохранена.')

    async def chat_info(self,c):
        r=c.db.one('SELECT * FROM chats WHERE id=?',(c.cid,))
        n=c.db.one('SELECT COUNT(*) n FROM members WHERE chat_id=?',(c.cid,))['n']
        await c.say(f'{r["title"]}\nЧат ID {c.cid}\nЗамеченных участников: {n}\nВаш ранг: {c.rank}\nЛимит предупреждений: {r["warn_limit"]}')
    async def stats(self,c):
        uid,_=await self.target(c,False) if c.args or c.msg.reply_to_message else (c.uid,[])
        r=c.db.one('SELECT messages FROM members WHERE chat_id=? AND user_id=?',(c.cid,uid))
        await c.say(f'Активность {uid}: сообщений {r["messages"] if r else 0}.')
    async def top(self,c):
        period='today' if c.args and c.args[0].lower() in ('today','сегодня') else 'all'
        sql=('SELECT m.user_id,u.name,s.count value FROM stats s JOIN users u ON u.id=s.user_id JOIN members m ON m.chat_id=s.chat_id AND m.user_id=s.user_id WHERE s.chat_id=? AND s.day=date("now") ORDER BY s.count DESC LIMIT 10' if period=='today' else
             'SELECT m.user_id,u.name,m.messages value FROM members m JOIN users u ON u.id=m.user_id WHERE m.chat_id=? ORDER BY m.messages DESC LIMIT 10')
        rows=c.db.all(sql,(c.cid,))
        await c.say('Топ активности:\n'+'\n'.join(f'{i}. {r["name"]} ({r["user_id"]}) — {r["value"]}' for i,r in enumerate(rows,1)) if rows else 'Пока нет статистики.')
    async def rules(self,c):
        r=c.db.one('SELECT rules FROM chats WHERE id=?',(c.cid,))
        await c.say(r['rules'] or 'Правила пока не установлены.')
    async def rank_list(self,c):
        rows=c.db.all('SELECT m.user_id,m.name,m.rank FROM members m WHERE m.chat_id=? AND m.rank>0 ORDER BY rank DESC LIMIT 40',(c.cid,))
        await c.say('Локальные модераторы:\n'+'\n'.join(f'Ранг {r["rank"]}: {r["name"]} ({r["user_id"]})' for r in rows) if rows else 'Локальные ранги ещё не назначены; Telegram-администраторы получают ранг 4 автоматически.')
    async def warnings(self,c):
        uid,_=await self.target(c,False) if c.args or c.msg.reply_to_message else (c.uid,[])
        rows=self.svc.warnings(c.cid,uid)
        await c.say(f'Предупреждений {uid}: {len(rows)}\n'+'\n'.join(f'#{r["id"]}: {r["reason"] or "без причины"}' for r in rows[:15]))
    async def settings(self,c):
        r=c.db.one('SELECT * FROM chats WHERE id=?',(c.cid,))
        await c.say(f'Модерация: антиспам={r["antispam"]}, запрет ссылок={r["links"]}, CAPS={r["caps"]}, флуд>{r["flood_limit"]}/10с, входы для антирейда={r["raid_limit"]}/60с (0=выкл), лимит предупреждений={r["warn_limit"]}, лог-чат={r["log_chat_id"] or "не назначен"}.')
    async def setrank(self,c):
        uid,args=await self.target(c)
        if not args or not args[0].isdigit():raise DomainError('/setrank ID 0..4 или /setrank 2 ответом на сообщение.')
        val=int(args[0]); await self.protected(c,uid)
        self.svc.set_rank(c.cid,c.uid,uid,val,c.rank)
        await c.say(f'Локальный ранг пользователя {uid}: {val}.')
    async def warn(self,c):
        uid,args=await self.target(c)
        await self.protected(c,uid)
        ttl=7*86400
        if args and DURATION.fullmatch(args[0]):ttl=duration(args.pop(0))
        if ttl<30:raise DomainError('Минимальный срок предупреждения — 30 секунд.')
        reason=' '.join(args)[:500] or 'Не указана'
        n,limit=self.svc.add_warning(c.cid,c.uid,uid,reason,ttl)
        await self.log_action(c.bot,c.cid,f'WARN {uid} от {c.uid}: {reason}, {n}/{limit}')
        if n>=limit:
            await c.bot.ban_chat_member(c.cid,uid,until_date=int(time.time())+3600)
            c.db.event(c.cid,c.uid,'autoban_warns',uid,reason)
            await c.say(f'Предупреждения {uid}: {n}/{limit}. Автобан на 1 час.')
        else: await c.say(f'Предупреждение {uid}: {n}/{limit}. Причина: {reason}')
    async def unwarn(self,c):
        uid,args=await self.target(c,False)
        await self.protected(c,uid)
        n=self.svc.clear_warning(c.cid,c.uid,uid,'all' in args or 'все' in args)
        await c.say(f'Снято предупреждений: {n}.')
    async def mute(self,c):
        uid,args=await self.target(c)
        await self.protected(c,uid)
        secs=duration(args.pop(0)) if args and DURATION.fullmatch(args[0]) else 3600
        self.safe_ban_duration(secs)
        await c.bot.restrict_chat_member(c.cid,uid,ChatPermissions(can_send_messages=False),until_date=int(time.time())+secs)
        c.db.event(c.cid,c.uid,'mute',uid,' '.join(args))
        await self.log_action(c.bot,c.cid,f'MUTE {uid} на {secs}с от {c.uid}')
        await c.say(f'{uid}: мут на {secs} секунд.')
    async def unmute(self,c):
        uid,_=await self.target(c,False)
        await self.protected(c,uid)
        # Restore common default permissions; custom granular chat permissions may need admin adjustment.
        await c.bot.restrict_chat_member(c.cid,uid,ChatPermissions(can_send_messages=True,can_send_audios=True,can_send_documents=True,can_send_photos=True,can_send_videos=True,can_send_video_notes=True,can_send_voice_notes=True,can_send_polls=True,can_send_other_messages=True,can_add_web_page_previews=True,can_invite_users=True))
        c.db.event(c.cid,c.uid,'unmute',uid)
        await c.say(f'Снято ограничение с {uid}.')
    async def ban(self,c):
        uid,args=await self.target(c,False)
        await self.protected(c,uid)
        secs=duration(args.pop(0)) if args and DURATION.fullmatch(args[0]) else 0
        self.safe_ban_duration(secs)
        await c.bot.ban_chat_member(c.cid,uid,until_date=int(time.time())+secs if secs else None,revoke_messages=False)
        reason=' '.join(args)[:500]
        c.db.run('INSERT INTO bans(chat_id,user_id,mod_id,reason,created_at,until_at) VALUES(?,?,?,?,?,?) '
                 'ON CONFLICT(chat_id,user_id) DO UPDATE SET mod_id=excluded.mod_id,reason=excluded.reason,created_at=excluded.created_at,until_at=excluded.until_at',
                 (c.cid,uid,c.uid,reason,int(time.time()),int(time.time())+secs if secs else 0))
        c.db.event(c.cid,c.uid,'ban',uid,reason)
        await self.log_action(c.bot,c.cid,f'BAN {uid} от {c.uid}: {reason}')
        await c.say(f'{uid} заблокирован'+(f' на {secs} секунд.' if secs else ' бессрочно.')+(f' Причина: {reason}' if reason else ''))
    async def unban(self,c):
        uid,_=await self.target(c,False)
        await c.bot.unban_chat_member(c.cid,uid,only_if_banned=True)
        c.db.run('DELETE FROM bans WHERE chat_id=? AND user_id=?',(c.cid,uid))
        c.db.event(c.cid,c.uid,'unban',uid)
        await c.say(f'Блокировка {uid} снята. Telegram не добавляет его в чат автоматически.')
    async def kick(self,c):
        uid,_=await self.target(c)
        await self.protected(c,uid)
        await c.bot.ban_chat_member(c.cid,uid)
        await c.bot.unban_chat_member(c.cid,uid)
        c.db.event(c.cid,c.uid,'kick',uid)
        await c.say(f'{uid} исключён, может вернуться по приглашению.')
    async def purge(self,c):
        if not c.msg.reply_to_message:raise DomainError('Ответьте на первое удаляемое сообщение: /purge (до 100).')
        a=c.msg.reply_to_message.message_id;b=c.msg.message_id
        if b-a>98:raise DomainError('Не более 100 сообщений за один вызов.')
        try:
            await c.bot.delete_messages(c.cid,list(range(a,b+1)))
        except TelegramAPIError:
            # Best effort for ineligible messages (>48h old, service messages etc).
            deleted=0
            for mid in range(a,b+1):
                try:await c.bot.delete_message(c.cid,mid);deleted+=1
                except TelegramAPIError:continue
            await self.log_action(c.bot,c.cid,f'PURGE {deleted} сообщений от {c.uid}')
            return
        await self.log_action(c.bot,c.cid,f'PURGE до {b-a+1} сообщений от {c.uid}')
    async def audit(self,c):
        rows=c.db.all('SELECT * FROM audit WHERE chat_id=? ORDER BY id DESC LIMIT 15',(c.cid,))
        await c.say('Последние действия:\n'+'\n'.join(f'{datetime.fromtimestamp(r["at"],timezone.utc).strftime("%m-%d %H:%M")} {r["actor_id"]}: {r["action"]} => {r["target_id"] or "-"} {r["detail"][:70]}' for r in rows) if rows else 'Журнал пуст.')
    # Chat configuration and controlled custom content.
    async def setwelcome(self,c):
        if len(c.raw)>1500:raise DomainError('Приветствие: максимум 1500 символов.')
        c.db.run('UPDATE chats SET welcome=? WHERE id=?',(c.raw,c.cid))
        await c.say('Приветствие сохранено. {name} и {id} заменяются при входе.')
    async def setrules(self,c):
        if not 1<=len(c.raw)<=3000:raise DomainError('/setrules текст правил (до 3000).')
        c.db.run('UPDATE chats SET rules=? WHERE id=?',(c.raw,c.cid))
        await c.say('Правила сохранены.')
    async def setlog(self,c):
        if not c.args or not re.fullmatch(r'-?\d{5,20}|0',c.args[0]):
            raise DomainError('/setlog ID_чата; /setlog 0 отключает. Добавьте бота в лог-чат.')
        cid=int(c.args[0])
        if cid:
            member=await c.bot.get_chat_member(cid,self.bot_id)
            if member.status not in ('creator','administrator','member'):
                raise DomainError('Добавьте бота в лог-чат.')
        c.db.run('UPDATE chats SET log_chat_id=? WHERE id=?',(cid or None,c.cid))
        await c.say(f'Логи: {cid or "отключены"}.')
    async def setwarnlimit(self,c):
        n=int(c.args[0])
        if not 1<=n<=20:raise DomainError('Лимит должен быть 1–20.')
        c.db.run('UPDATE chats SET warn_limit=? WHERE id=?',(n,c.cid));await c.say(f'Лимит предупреждений: {n}.')
    async def toggle(self,c):
        if not c.args or c.args[0].lower() not in ('on','off','вкл','выкл'):
            raise DomainError(f'/{c.name} on|off')
        column={'antispam':'antispam','antilinks':'links','anticaps':'caps'}[c.name]
        value=int(c.args[0].lower() in ('on','вкл'))
        c.db.run(f'UPDATE chats SET {column}=? WHERE id=?',(value,c.cid))
        await c.say(f'{c.name}: {"включено" if value else "выключено"}.')
    async def flood_cmd(self,c):
        n=int(c.args[0])
        if not 0<=n<=30:raise DomainError('/flood 0..30 сообщений за 10 секунд (0=выкл).')
        c.db.run('UPDATE chats SET flood_limit=? WHERE id=?',(n,c.cid))
        await c.say(f'Порог флуда: {n}/10с.')
    async def antiraid(self,c):
        n=int(c.args[0])
        if not 0<=n<=100 or n==1:raise DomainError('/antiraid 0 (выкл) или 2..100 новых участников за минуту.')
        c.db.run('UPDATE chats SET raid_limit=? WHERE id=?',(n,c.cid))
        await c.say(f'Антирейд: {n}/мин (0 — отключён). При превышении новые входы блокируются на 1 час в течение 2 минут.')
    async def filter_add(self,c):
        phrase=clean(c.raw)
        if not 2<=len(phrase)<=80:raise DomainError('/filter_add фраза (2–80 символов).')
        c.db.run('INSERT OR IGNORE INTO filters VALUES (?,?)',(c.cid,phrase))
        await c.say('Фраза добавлена в фильтр.')
    async def filter_del(self,c):
        n=c.db.run('DELETE FROM filters WHERE chat_id=? AND phrase=?',(c.cid,clean(c.raw))).rowcount
        await c.say('Удалено.' if n else 'Фраза не найдена.')
    async def filters(self,c):
        r=c.db.all('SELECT phrase FROM filters WHERE chat_id=? ORDER BY phrase LIMIT 50',(c.cid,))
        await c.say('Фильтры: '+(', '.join(x['phrase'] for x in r) if r else 'пусто'))
    async def access(self,c):
        if len(c.args)!=2 or c.args[0].lower() not in self.handlers:
            raise DomainError('/access имя_команды ранг(0..5 или -1 для отключения).')
        name=c.args[0].lower()
        val=int(c.args[1])
        if val not in (-1,0,1,2,3,4,5):raise DomainError('Ранг: -1, 0..5.')
        if name in ('access','setrank','health'):
            raise DomainError('Для этой команды ограничения неизменяемы.')
        c.db.run('INSERT INTO command_access(chat_id,command,min_rank) VALUES (?,?,?) ON CONFLICT(chat_id,command) DO UPDATE SET min_rank=excluded.min_rank',(c.cid,name,val))
        await c.say(f'Доступ /{name}: {val}. Минимальный защищённый ранг {self.hard_floors[name]} нельзя понизить.')
    async def command_add(self,c):
        t,sep,response=c.raw.partition(' | ')
        t=clean(t)
        if not sep or not SIMPLE_NAME.fullmatch(t) or len(response)>1800 or not response:
            raise DomainError('/command_add привет | Ответ на привет (через пробел | пробел).')
        if t in self.handlers:raise DomainError('Нельзя подменить встроенную команду.')
        c.db.run('INSERT INTO custom_commands VALUES (?,?,?) ON CONFLICT(chat_id,trigger) DO UPDATE SET response=excluded.response',(c.cid,t,response))
        await c.say(f'Пользовательская команда сохранена: {t} (точное совпадение текста).')
    async def command_del(self,c):
        n=c.db.run('DELETE FROM custom_commands WHERE chat_id=? AND trigger=?',(c.cid,clean(c.raw))).rowcount
        await c.say('Удалена.' if n else 'Команда не найдена.')
    async def commands(self,c):
        rows=c.db.all('SELECT trigger,response FROM custom_commands WHERE chat_id=? ORDER BY trigger LIMIT 40',(c.cid,))
        await c.say('Команды чата:\n'+'\n'.join(f'{r["trigger"]}: {r["response"][:80]}' for r in rows) if rows else 'Пользовательских команд нет.')
    async def note_add(self,c):
        name,sep,body=c.raw.partition(' | ')
        name=clean(name)
        if not sep or not SIMPLE_NAME.fullmatch(name) or not 1<=len(body)<=2500:
            raise DomainError('/note_add имя | текст заметки')
        c.db.run('INSERT INTO notes VALUES (?,?,?) ON CONFLICT(chat_id,name) DO UPDATE SET content=excluded.content',(c.cid,name,body))
        await c.say(f'Заметка {name} сохранена.')
    async def note_del(self,c):
        n=c.db.run('DELETE FROM notes WHERE chat_id=? AND name=?',(c.cid,clean(c.raw))).rowcount
        await c.say('Удалена.' if n else 'Заметка не найдена.')
    async def note(self,c):
        if not c.raw:
            r=c.db.all('SELECT name FROM notes WHERE chat_id=? LIMIT 50',(c.cid,))
            await c.say('Заметки: '+(', '.join(x['name'] for x in r) if r else 'пусто'))
            return
        r=c.db.one('SELECT content FROM notes WHERE chat_id=? AND name=?',(c.cid,clean(c.raw)))
        await c.say(r['content'] if r else 'Заметка не найдена.')

    # Global profile, reputation and virtual economy.
    async def wallet(self,c):
        uid,_=await self.target(c,False) if c.args or c.msg.reply_to_message else (c.uid,[])
        money=self.svc.balance(uid)
        await c.say(f'Кошелёк {uid}: {money[0]} монет, {money[1]} золота (не имеют денежной стоимости).')
    async def daily(self,c):
        money=self.svc.daily(c.uid)
        await c.say(f'+25 монет. Баланс: {money[0]}. Следующий бонус завтра по UTC.')
    async def give(self,c):
        uid,args=await self.target(c,False)
        if not args:raise DomainError('/give ID 25 или /give 25 ответом на сообщение.')
        remaining=self.svc.transfer(c.uid,uid,int(args[0]))
        await c.say(f'Монеты переведены пользователю {uid}. Остаток: {remaining[0]}.')
    async def rich(self,c):
        rows=c.db.all('SELECT user_id,coins FROM wallet ORDER BY coins DESC LIMIT 10')
        await c.say('Рейтинг кошельков:\n'+'\n'.join(f'{i}. {r["user_id"]}: {r["coins"]}' for i,r in enumerate(rows,1)))
    async def exchange(self,c):
        if len(c.args) != 2:raise DomainError('/exchange buy 2 или /exchange sell 1; не имеет отношения к реальным деньгам.')
        coins,gold=self.svc.exchange(c.uid,c.args[0].lower(),int(c.args[1]))
        await c.say(f'Обмен завершён. Баланс: {coins} монет, {gold} золота. Курс: 100 / 95.')

    async def rep(self,c):
        uid,args=await self.target(c,False)
        delta=-1 if args and args[0] in ('-','-1','минус') else 1
        score=self.svc.vote(c.uid,uid,delta)
        await c.say(f'Репутация {uid}: {score:+}.')
    async def reputation(self,c):
        uid,_=await self.target(c,False) if c.args or c.msg.reply_to_message else (c.uid,[])
        await c.say(f'Репутация {uid}: {self.svc.reputation(uid):+}.')

    # Relationships and clans.
    async def marry(self,c):
        uid,_=await self.target(c)
        self.svc.propose(c.uid,uid)
        await c.say(f'Пользователь {c.uid} предложил брак пользователю {uid}. Получатель: ответьте /accept {c.uid} в течение 24 часов.')
    async def accept(self,c):
        uid,_=await self.target(c,False)
        self.svc.accept_proposal(uid,c.uid)
        await c.say(f'Брак между {uid} и {c.uid} заключён.')
    async def divorce(self,c):
        self.svc.divorce(c.uid);await c.say('Брак расторгнут.')
    async def spouse(self,c):
        uid,_=await self.target(c,False) if c.args or c.msg.reply_to_message else (c.uid,[])
        spouse=self.svc.spouse(uid)
        await c.say(f'Партнёр {uid}: {spouse}' if spouse else 'Брак не заключён.')
    async def clan_create(self,c):
        clanid=self.svc.create_clan(c.cid,c.uid,c.raw)
        await c.say(f'Клан создан, ID {clanid}. Цена: 100 виртуальных монет.')
    async def clan_join(self,c):
        name=self.svc.join_clan(c.uid,int(c.args[0]),c.cid)
        await c.say(f'Вы вступили в клан {name}.')
    async def clan_leave(self,c):
        self.svc.leave_clan(c.uid);await c.say('Вы вышли из клана.')
    async def clan_disband(self,c):
        self.svc.disband_clan(c.uid);await c.say('Ваш клан расформирован.')
    async def clans(self,c):
        rows=c.db.all('SELECT c.id,c.name,COUNT(cm.user_id) members FROM clans c LEFT JOIN clan_members cm ON c.id=cm.clan_id WHERE c.chat_id=? GROUP BY c.id ORDER BY members DESC LIMIT 30',(c.cid,))
        await c.say('Кланы:\n'+'\n'.join(f'{r["id"]}. {r["name"]}: {r["members"]} уч.' for r in rows) if rows else 'Кланов нет.')

    # Games and user-submitted content.
    async def award(self,c):
        uid,args=await self.target(c)
        await self.protected(c,uid)
        name=' '.join(args).strip()
        self.svc.award(c.cid,c.uid,uid,name)
        c.db.event(c.cid,c.uid,'award',uid,name)
        await c.say(f'Награда «{name}» вручена участнику {uid}.')
    async def awards(self,c):
        uid,_=await self.target(c,False) if c.args or c.msg.reply_to_message else (c.uid,[])
        rows=c.db.all('SELECT name,giver_id FROM awards WHERE chat_id=? AND target_id=? ORDER BY id DESC LIMIT 20',(c.cid,uid))
        await c.say(f'Награды {uid}:\n'+'\n'.join(f'{r["name"]} (от {r["giver_id"]})' for r in rows) if rows else 'Наград пока нет.')

    async def duel(self,c):
        uid,args=await self.target(c)
        if not args:raise DomainError('/duel ID ставка (1..1000) или /duel ставка ответом на сообщение.')
        duelid=self.svc.duel_create(c.cid,c.uid,uid,int(args[0]))
        await c.say(f'Дуэль #{duelid}: {c.uid} вызывает {uid}, ставка {args[0]} монет. {uid} должен написать /duel_accept {duelid} или /duel_decline {duelid} в течение часа.')
    async def duel_accept(self,c):
        result=self.svc.duel_reply(int(c.args[0]),c.cid,c.uid,True)
        await c.say(f'Дуэль закончена. Победитель: {result}.' if result else 'Дуэль истекла, монеты возвращены.')
    async def duel_decline(self,c):
        self.svc.duel_reply(int(c.args[0]),c.cid,c.uid,False)
        await c.say('Дуэль отклонена, ставка возвращена.')
    async def dice(self,c):
        await c.bot.send_dice(c.cid,emoji='🎲')
    async def coin(self,c):
        import secrets
        await c.say('Орёл' if secrets.randbelow(2) else 'Решка')
    async def report(self,c):
        if not c.msg.reply_to_message:raise DomainError('Ответьте /report на сообщение с нарушением.')
        culprit=c.msg.reply_to_message.from_user
        c.db.event(c.cid,c.uid,'report',culprit.id if culprit else None,f'Сообщение {c.msg.reply_to_message.message_id}')
        await self.log_action(c.bot,c.cid,f'Жалоба {c.uid} на сообщение {c.msg.reply_to_message.message_id}, пользователь {culprit.id if culprit else "скрыт"}.')
        await c.say('Жалоба записана. При настроенном /setlog она направлена модераторам.')
    async def bookmark(self,c):
        if not c.msg.reply_to_message:raise DomainError('Ответьте на сообщение: /bookmark имя.')
        if not c.args or not SIMPLE_NAME.fullmatch(c.args[0]):raise DomainError('Имя закладки: до 32 букв или цифр.')
        c.db.run('INSERT INTO bookmarks VALUES (?,?,?,?) ON CONFLICT(user_id,name) DO UPDATE SET chat_id=excluded.chat_id,message_id=excluded.message_id',
                 (c.uid,c.cid,c.msg.reply_to_message.message_id,c.args[0].lower()))
        await c.say('Закладка сохранена.')
    async def bookmarks(self,c):
        rows=c.db.all('SELECT * FROM bookmarks WHERE user_id=? LIMIT 30',(c.uid,))
        await c.say('Закладки (ссылки только для публичных / супергрупп с ID -100...):\n'+'\n'.join(f'{r["name"]}: чат {r["chat_id"]}, сообщение {r["message_id"]}' for r in rows) if rows else 'Закладок нет.')
    async def remind(self,c):
        if len(c.args)<2:raise DomainError('/remind 15m Текст напоминания; максимум 30 дней.')
        secs=duration(c.args[0])
        if not 30<=secs<=30*86400:raise DomainError('Срок: от 30 секунд до 30 дней.')
        body=c.raw[len(c.args[0]):].strip()[:500]
        if not body:raise DomainError('Введите текст напоминания.')
        n=c.db.one('SELECT COUNT(*) n FROM reminders WHERE user_id=? AND sent=0',(c.uid,))['n']
        if n>=20:raise DomainError('Не более 20 активных напоминаний на пользователя.')
        cur=c.db.run('INSERT INTO reminders(chat_id,user_id,text,due_at) VALUES(?,?,?,?)',
                     (c.cid,c.uid,body,int(time.time())+secs))
        await c.say(f'Напоминание #{cur.lastrowid} создано. Получатель: текущий чат.')
    async def reminders(self,c):
        rows=c.db.all('SELECT id,text,due_at FROM reminders WHERE user_id=? AND sent=0 ORDER BY due_at LIMIT 20',(c.uid,))
        await c.say('Ваши напоминания (UTC):\n'+'\n'.join(f'#{r["id"]} {datetime.fromtimestamp(r["due_at"],timezone.utc):%m-%d %H:%M}: {r["text"][:90]}' for r in rows) if rows else 'Активных напоминаний нет.')
    async def raffle(self,c):
        if len(c.args)<2:raise DomainError('/raffle 1h Приз (от 5 минут до 7 дней).')
        secs=duration(c.args[0])
        if not 300<=secs<=7*86400:raise DomainError('Розыгрыш: от 5 минут до 7 дней.')
        prize=c.raw[len(c.args[0]):].strip()[:300]
        if not prize:raise DomainError('Укажите приз.')
        cur=c.db.run('INSERT INTO giveaways(chat_id,creator,prize,deadline) VALUES(?,?,?,?)',
                     (c.cid,c.uid,prize,int(time.time())+secs))
        await c.say(f'Розыгрыш #{cur.lastrowid}: {prize}. Для участия: /raffle_join {cur.lastrowid}. Победитель определяется случайно после окончания.')
    async def raffle_join(self,c):
        r=c.db.one('SELECT * FROM giveaways WHERE id=? AND chat_id=? AND finished=0',
                   (int(c.args[0]),c.cid))
        if not r or r['deadline']<=int(time.time()):raise DomainError('Активный розыгрыш не найден.')
        c.db.run('INSERT OR IGNORE INTO giveaway_entries(giveaway_id,user_id) VALUES(?,?)',(r['id'],c.uid))
        await c.say('Вы участвуете в розыгрыше.')
    async def raffles(self,c):
        rows=c.db.all('SELECT id,prize,deadline FROM giveaways WHERE chat_id=? AND finished=0 AND deadline>? ORDER BY deadline LIMIT 10',(c.cid,int(time.time())))
        await c.say('Розыгрыши:\n'+'\n'.join(f'#{r["id"]}: {r["prize"]} (до {datetime.fromtimestamp(r["deadline"],timezone.utc):%m-%d %H:%M} UTC)' for r in rows) if rows else 'Активных розыгрышей нет.')
    async def timer(self,c):
        if len(c.args)<2:raise DomainError('/timer 2h Сообщение (публикация каждые 2 часа).')
        seconds=duration(c.args[0])
        if not 300<=seconds<=30*86400:raise DomainError('Период таймера: от 5 минут до 30 дней.')
        body=c.raw[len(c.args[0]):].strip()[:1000]
        count=c.db.one('SELECT COUNT(*) n FROM chat_timers WHERE chat_id=? AND active=1',(c.cid,))['n']
        if count>=20:raise DomainError('Не более 20 активных таймеров в чате.')
        if not body:raise DomainError('Введите текст.')
        row=c.db.run('INSERT INTO chat_timers(chat_id,owner_id,content,every_seconds,next_at) VALUES(?,?,?,?,?)',
                     (c.cid,c.uid,body,seconds,int(time.time())+seconds))
        await c.say(f'Таймер #{row.lastrowid} создан. Сообщения будут публиковаться каждые {seconds} секунд.')
    async def timers(self,c):
        rows=c.db.all('SELECT id,content,every_seconds FROM chat_timers WHERE chat_id=? AND active=1 LIMIT 20',(c.cid,))
        await c.say('Таймеры:\n'+'\n'.join(f'#{r["id"]} / {r["every_seconds"]} с: {r["content"][:65]}' for r in rows) if rows else 'Активных таймеров нет.')
    async def timer_off(self,c):
        n=c.db.run('UPDATE chat_timers SET active=0 WHERE chat_id=? AND id=?',(c.cid,int(c.args[0]))).rowcount
        await c.say('Таймер остановлен.' if n else 'Не найден.')

    async def fed_create(self,c):
        fid=self.svc.federation_create(c.cid,c.uid,c.raw)
        await c.say(f'Создана сеть #{fid}. Код приглашения: /fed_code (действителен 10 минут).')
    async def fed_code(self,c):
        code=self.svc.federation_code(c.cid,c.uid)
        # Owner must decide how to share the code. Avoid leaking it in group chat.
        try:
            await c.bot.send_message(c.uid,f'Одноразовый код сети: {code}\nВ другом чате его владелец вводит /fed_join {code}\nДействует 10 минут.')
            await c.say('Код отправлен вам в личные сообщения.')
        except TelegramAPIError:
            raise DomainError('Сначала откройте личный чат с ботом и нажмите /start, затем повторите.')
    async def fed_join(self,c):
        if not c.args:raise DomainError('/fed_join КОД — используйте в другом чате от имени его владельца.')
        fid=self.svc.federation_join(c.cid,c.args[0])
        try:await c.msg.delete()  # Remove invitation code from group history if possible.
        except TelegramAPIError:pass
        await c.say(f'Чат присоединён к сети #{fid}. Владелец сети может применять общие баны.')
    async def fed_leave(self,c):
        self.svc.federation_leave(c.cid,c.uid)
        await c.say('Чат вышел из сети. Если вы владелец всей сети, она расформирована для всех чатов. Ранее выданные баны остаются в силе.')
    async def fed_info(self,c):
        f=self.svc.federation(c.cid)
        if not f:raise DomainError('Чат не подключён к сети.')
        chats=c.db.all('SELECT chat_id FROM federation_chats WHERE federation_id=?',(f['id'],))
        await c.say(f'Сеть {f["name"]} #{f["id"]}, владелец: {f["owner_id"]}. Чаты: '+', '.join(str(x['chat_id']) for x in chats))
    async def fed_ban(self,c):
        f=self.svc.federation(c.cid)
        if not f or f['owner_id']!=c.uid:raise DomainError('Общие блокировки может делать только владелец сети.')
        uid,args=await self.target(c,False)
        if uid==self.bot_id or uid==c.uid:raise DomainError('Неверная цель.')
        secs=duration(args.pop(0)) if args and DURATION.fullmatch(args[0]) else 0
        self.safe_ban_duration(secs)
        chats=c.db.all('SELECT chat_id FROM federation_chats WHERE federation_id=?',(f['id'],))
        ok=skip=0
        for item in chats:
            dest=item['chat_id']
            try:
                member=await c.bot.get_chat_member(dest,uid)
                if member.status in ('creator','administrator'):
                    skip+=1;continue
                await c.bot.ban_chat_member(dest,uid,until_date=int(time.time())+secs if secs else None)
                c.db.event(dest,c.uid,'fed_ban',uid,' '.join(args)[:200]);ok+=1
            except TelegramAPIError:skip+=1
        await c.say(f'Общий бан {uid}: успешно в {ok} чатах, пропущено {skip}. Причина: {" ".join(args) or "не указана"}.')
    async def fed_unban(self,c):
        f=self.svc.federation(c.cid)
        if not f or f['owner_id']!=c.uid:raise DomainError('Общие блокировки может снимать только владелец сети.')
        uid,_=await self.target(c,False)
        rows=c.db.all('SELECT chat_id FROM federation_chats WHERE federation_id=?',(f['id'],))
        ok=skip=0
        for row in rows:
            try:
                await c.bot.unban_chat_member(row['chat_id'],uid,only_if_banned=True)
                c.db.event(row['chat_id'],c.uid,'fed_unban',uid);ok+=1
            except TelegramAPIError:skip+=1
        await c.say(f'Разблокировано в {ok} чатах; пропущено {skip}.')

    async def poll(self,c):
        # Separate alternatives with |; limit to Telegram's 2..12 choices.
        items=[x.strip() for x in c.raw.split('|')]
        if not 3<=len(items)<=13 or any(not x or len(x)>100 for x in items[1:]) or len(items[0])>300:
            raise DomainError('/poll Ваш вопрос | вариант 1 | вариант 2 [| ... до 12]')
        await c.bot.send_poll(c.cid,question=items[0],options=items[1:],is_anonymous=True)

    async def scheduler(self,bot:Bot,stop:asyncio.Event):
        """Single-worker, at-least-once attempts; delivery errors remain retryable."""
        while not stop.is_set():
            try:
                due=self.svc.due_reminders()
                for r in due:
                    try:
                        await bot.send_message(r['chat_id'],f'Напоминание для {r["user_id"]}: {r["text"]}')
                        self.svc.db.run('UPDATE reminders SET sent=1 WHERE id=? AND sent=0',(r['id'],))
                    except TelegramAPIError:
                        log.warning('Reminder delivery failed: %s',r['id'])
                giveaways=self.svc.db.all('SELECT id FROM giveaways WHERE finished=0 AND deadline<=? LIMIT 30',(int(time.time()),))
                for g in giveaways:
                    result=self.svc.raffle_draw(g['id'])
                    if result:
                        giveaway,winner=result
                        try:await bot.send_message(giveaway['chat_id'],f'Розыгрыш #{g["id"]} «{giveaway["prize"]}»: '+(f'победил участник {winner}!' if winner else 'никто не участвовал.'))
                        except TelegramAPIError:log.warning('Raffle notification failed: %s',g['id'])
                timers=self.svc.db.all('SELECT * FROM chat_timers WHERE active=1 AND next_at<=? LIMIT 30',(int(time.time()),))
                for t in timers:
                    # Advance before sending; this prevents a burst of duplicates after downtime.
                    self.svc.db.run('UPDATE chat_timers SET next_at=? WHERE id=? AND active=1',
                                    (int(time.time())+t['every_seconds'],t['id']))
                    try:await bot.send_message(t['chat_id'],t['content'])
                    except TelegramAPIError:log.warning('Timer delivery failed: %s',t['id'])
                # Refund abandoned challenge escrow after an hour.                # Refund abandoned challenge escrow after an hour.
                expired=self.svc.db.all('SELECT id,stake,challenger FROM duels WHERE status="pending" AND created_at<? LIMIT 100',(int(time.time())-3600,))
                for d in expired:
                    with self.svc.db.transaction():
                        changed=self.svc.db.run('UPDATE duels SET status="expired" WHERE id=? AND status="pending"',(d['id'],)).rowcount
                        if changed:self.svc.db.run('UPDATE wallet SET coins=coins+? WHERE user_id=?',(d['stake'],d['challenger']))
            except Exception:log.exception('Scheduler failed')
            try:await asyncio.wait_for(stop.wait(),timeout=10)
            except asyncio.TimeoutError:pass


async def serve(config:Config):
    db=Database(config.db_path)
    bot=create_bot(config)
    orion=Orion(config,db)
    dp=Dispatcher()
    dp.include_router(orion.router)
    stop=asyncio.Event()
    try:
        me=await bot.get_me()
        orion.bot_id=me.id
        orion.bot_username=me.username or ''
        await bot.set_my_commands([BotCommand(command=k,description=v) for k,v in [
            ('help','Справочник'),('profile','Профиль'),('id','Мой ID'),('stats','Статистика в чате'),
            ('settings','Настройки чата'),('warn','Предупреждение'),('mute','Мут'),('ban','Бан'),
            ('wallet','Виртуальный кошелёк'),('daily','Ежедневный бонус'),('rep','Репутация'),
            ('clans','Кланы'),('remind','Напоминание'),('rules','Правила'),('report','Пожаловаться')]])
        task=asyncio.create_task(orion.scheduler(bot,stop))
        log.info('Started @%s (id=%s). Bot token is not logged.',me.username,me.id)
        try:await dp.start_polling(bot,allowed_updates=['message','chat_member'])
        finally:
            stop.set()
            await task
    finally:
        await bot.session.close()
        db.close()
