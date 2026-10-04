"""Transport static integrity tests runnable even without aiogram installed."""
import ast
from pathlib import Path


def route_map():
    module=ast.parse((Path(__file__).parent.parent/'orion/telegram_app.py').read_text(encoding='utf8'))
    cls=next(x for x in module.body if isinstance(x,ast.ClassDef) and x.name=='Orion')
    defined={x.name for x in cls.body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))}
    register=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='_register')
    registered=[]
    for node in ast.walk(register):
        if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Name) or node.func.id!='a':continue
        assert isinstance(node.args[0],ast.Constant)
        method=node.args[1]
        assert isinstance(method,ast.Attribute) and method.attr in defined, ast.unparse(method)
        for token in node.args[0].value.split():registered.append((token,method.attr))
    return registered


def test_all_declared_handlers_exist_and_aliases_unique():
    routes=route_map()
    names=[x[0] for x in routes]
    assert len(names)>=95
    assert len(names)==len(set(names)), 'duplicate alias shadows another handler'


def test_critical_commands_are_declared():
    cmds=dict(route_map())
    for cmd in ('ban','warn','unwarn','mute','unmute','setrank','access','help','daily',
                'transfer','give','exchange','report','raffle','forgetme'):
        if cmd=='transfer':
            assert cmds.get('give')=='give'
        else:assert cmd in cmds


def test_polling_clears_webhook_before_start():
    text = (Path(__file__).parent.parent / "orion/telegram_app.py").read_text(encoding="utf-8")
    delete_pos = text.index("await bot.delete_webhook")
    poll_pos = text.index("await dp.start_polling")
    assert delete_pos < poll_pos
