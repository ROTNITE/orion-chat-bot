import time
import pytest
from orion.db import Database
from orion.services import Service, DomainError, clean, duration, utc_day

@pytest.fixture
def env():
    db=Database()
    db.chat(-100, 'Testing')
    for uid in (10001,10002,10003,10004):
        db.user(uid, f'Person {uid}')
        db.member(-100,uid, f'Person {uid}')
    yield db,Service(db)
    db.close()

@pytest.mark.parametrize('s,sec', [('30m',1800),('2h',7200),('1д',86400),('1w',604800),('5мин',300)])
def test_duration(s,sec): assert duration(s)==sec

@pytest.mark.parametrize('s', ['11','-2h','1year','invalid','1секунда','999999999d'])
def test_bad_duration(s):
    with pytest.raises(DomainError):duration(s)

def test_normalization(): assert clean('ＡＢＣ')=='abc'

def test_record_stats(env):
    db,s=env
    s.record_message(-100,10001,'Person 10001',now=1750000000)
    s.record_message(-100,10001,'Person 10001',now=1750000001)
    assert db.one('SELECT messages FROM members WHERE chat_id=-100 AND user_id=10001')['messages']==2
    assert db.one('SELECT count FROM stats WHERE chat_id=-100 AND user_id=10001')['count']==2

def test_rank_hierarchy(env):
    db,s=env
    s.set_rank(-100,10001,10002,3,4)
    assert s.rank(-100,10002)==3
    with pytest.raises(DomainError):s.set_rank(-100,10002,10001,4,3)
    with pytest.raises(DomainError):s.set_rank(-100,10002,10002,1,3)
    with pytest.raises(DomainError):s.set_rank(-100,10001,10003,4,4)

def test_warnings_expire_and_clear(env):
    db,s=env
    n,limit=s.add_warning(-100,10001,10002,'spam',ttl=10,now=100)
    assert (n,limit)==(1,3)  # count evaluated against the supplied clock
    assert len(s.warnings(-100,10002,now=105))==1
    assert len(s.warnings(-100,10002,now=111))==0
    s.add_warning(-100,10001,10002,'now',ttl=3600)
    assert len(s.warnings(-100,10002))==1
    assert s.clear_warning(-100,10001,10002)==1
    assert not s.warnings(-100,10002)

def test_daily_global_limit(env):
    db,s=env
    assert s.daily(10001,now=1735689600)[0]==25
    with pytest.raises(DomainError):s.daily(10001,now=1735690000)
    assert s.daily(10001,now=1735776000)[0]==50

def test_transfer_atomic(env):
    db,s=env
    s.daily(10001)
    s.transfer(10001,10002,20)
    assert s.balance(10001)[0]==5 and s.balance(10002)[0]==20
    with pytest.raises(DomainError):s.transfer(10001,10002,10)
    assert s.balance(10001)[0]==5 and s.balance(10002)[0]==20
    with pytest.raises(DomainError):s.transfer(10001,10001,1)
    assert db.one('SELECT COUNT(*) n FROM transfers')['n']==1

def test_reputation_once_daily_and_self_protection(env):
    db,s=env
    assert s.vote(10001,10002,1,now=1735689600)==1
    with pytest.raises(DomainError):s.vote(10001,10002,-1,now=1735690000)
    assert s.vote(10001,10002,-1,now=1735776000)==0
    with pytest.raises(DomainError):s.vote(10001,10001,1)

def test_marriage_expiration_restrictions_and_divorce(env):
    db,s=env
    s.propose(10001,10002)
    s.accept_proposal(10001,10002)
    assert s.spouse(10001)==10002 and s.spouse(10002)==10001
    with pytest.raises(DomainError):s.propose(10001,10003)
    with pytest.raises(DomainError):s.accept_proposal(10001,10002)
    s.divorce(10002)
    assert s.spouse(10001) is None
    with pytest.raises(DomainError):s.divorce(10002)

def test_clans_atomic_funds_and_membership(env):
    db,s=env
    with pytest.raises(DomainError):s.create_clan(-100,10001,'test')
    db.run('UPDATE wallet SET coins=100 WHERE user_id=10001')
    cid=s.create_clan(-100,10001,'Alpha')
    assert s.balance(10001)[0]==0
    assert s.join_clan(10002,cid,-100)=='Alpha'
    with pytest.raises(DomainError):s.join_clan(10002,cid,-100)
    with pytest.raises(DomainError):s.leave_clan(10001)
    s.leave_clan(10002)
    s.disband_clan(10001)
    assert not db.one('SELECT 1 FROM clans WHERE id=?',(cid,))

def test_duel_escrow_refund(env):
    db,s=env
    db.run('UPDATE wallet SET coins=100 WHERE user_id IN (10001,10002)')
    d=s.duel_create(-100,10001,10002,30)
    assert s.balance(10001)[0]==70
    with pytest.raises(DomainError):s.duel_reply(d,-100,10003,True)
    assert s.duel_reply(d,-100,10002,False) is None
    assert s.balance(10001)[0]==100
    with pytest.raises(DomainError):s.duel_reply(d,-100,10002,False)

def test_duel_winner_and_total_funds(env):
    db,s=env
    db.run('UPDATE wallet SET coins=100 WHERE user_id IN (10001,10002)')
    d=s.duel_create(-100,10001,10002,25)
    winner=s.duel_reply(d,-100,10002,True)
    assert winner in (10001,10002)
    assert s.balance(10001)[0]+s.balance(10002)[0]==200

def test_rollback(env):
    db,_=env
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.run('UPDATE wallet SET coins=42 WHERE user_id=10001')
            raise RuntimeError('abort')
    assert db.one('SELECT coins FROM wallet WHERE user_id=10001')['coins']==0

def test_raffle_without_entries(env):
    db,s=env
    r=db.run('INSERT INTO giveaways(chat_id,creator,prize,deadline) VALUES(?,?,?,?)',(-100,10001,'test',int(time.time())-1))
    result=s.raffle_draw(r.lastrowid)
    assert result[1] is None
    assert s.raffle_draw(r.lastrowid) is None

def test_isolated_chats_and_users(env):
    db,s=env
    db.chat(-200,'Other chat')
    s.record_message(-100,10001,now=1750000000)
    assert not db.one('SELECT 1 FROM members WHERE chat_id=-200 AND user_id=10001')
    s.record_message(-200,10001,now=1750000000)
    assert db.one('SELECT messages FROM members WHERE chat_id=-100 AND user_id=10001')['messages']==1
    assert db.one('SELECT messages FROM members WHERE chat_id=-200 AND user_id=10001')['messages']==1

def test_exchange_virtual_with_spread(env):
    db,s=env
    db.run('UPDATE wallet SET coins=300 WHERE user_id=10001')
    assert s.exchange(10001,'buy',2)==(100,2)
    assert s.exchange(10001,'sell',1)==(195,1)
    with pytest.raises(DomainError):s.exchange(10001,'buy',3)
    assert s.balance(10001)==(195,1)

def test_awards(env):
    db,s=env
    s.award(-100,10001,10002,'Помощник')
    assert db.one('SELECT name FROM awards WHERE chat_id=-100 AND target_id=10002')['name']=='Помощник'
    with pytest.raises(DomainError):s.award(-100,10001,10001,'test')

def test_federation_invites_single_use_and_leaving(env):
    db,s=env
    f=s.federation_create(-100,10001,'Alpha network')
    code=s.federation_code(-100,10001)
    assert s.federation_join(-200,code)==f
    with pytest.raises(DomainError):s.federation_join(-300,code)
    with pytest.raises(DomainError):s.federation_create(-100,10001,'duplicate')
    with pytest.raises(DomainError):s.federation_code(-100,10002)
    s.federation_leave(-200)
    assert s.federation(-100)['id']==f
    s.federation_leave(-100)
    assert s.federation(-100) is None

def test_username_clearing_and_indirect_updates(env):
    db,s=env
    db.user(10001,'Name','first_name')
    s.record_message(-100,10001,'Name')  # Should not erase known username.
    assert db.one('SELECT username FROM users WHERE id=10001')['username']=='first_name'
    db.user(10001,'Name','')  # User explicitly no longer has a username.
    assert db.one('SELECT username FROM users WHERE id=10001')['username']==''


def test_federation_owner_leave_dissolves_network(env):
    db,s=env
    s.federation_create(-100,10001,'Alpha')
    code=s.federation_code(-100,10001)
    s.federation_join(-200,code)
    s.federation_leave(-100,10001)
    assert s.federation(-200) is None
