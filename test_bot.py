import json
import os
import tempfile
import zlib

os.environ["STATE_FILE"] = os.path.join(tempfile.mkdtemp(), "s.json")
import bot  # noqa: E402

CALLS = []


def fake_call(method, _timeout=30, **p):
    CALLS.append((method, p))
    return True


bot.call = fake_call
bot.BOT_USERNAME = "gamesbot"
A = {"id": 1001, "first_name": "Анна"}
B = {"id": 1002, "first_name": "Борис"}
C = {"id": 1003, "first_name": "Кира"}
qn = 0


def wq(user, data, chat=None, msg=1, inline=None):
    global qn
    qn += 1
    q = {"id": str(qn), "from": user, "data": data}
    if inline:
        q["inline_message_id"] = inline
    else:
        q["chat"], q["message_id"] = chat, msg
    CALLS.clear()
    bot.on_widget_query(q)
    answer = next(p for m, p in CALLS if m == "answerWidgetQuery")
    edit = next((p for m, p in CALLS if m == "editMessageWidgetData"), None)
    return json.loads(answer["data"]), edit


PRIV = {"id": 1001, "type": "private"}
GRP = {"id": -100, "type": "supergroup"}

# ---- sizes
for gid, g in bot.GAMES.items():
    assert len(g["html"].encode()) <= 32768
    assert len(zlib.compress(g["html"].encode(), 9)) <= 4096, gid

# ---- xo vs bot in private chat
st, edit = wq(A, "xo:m:4", PRIV, 10)
assert st["b"][4] == "x" and st["b"].count("o") == 1 and st["r"] == 1 and "e" not in st, st
assert edit["chat_id"] == 1001 and edit["message_id"] == 10
assert json.loads(edit["chat_data"])["b"] == st["b"]
for _ in range(9):  # keep playing until the game ends
    if st["w"]:
        break
    free = st["b"].index("-")
    st, _e = wq(A, f"xo:m:{free}", PRIV, 10)
assert st["w"] in ("x", "o", "d"), st
st2, _ = wq(A, "xo:n", PRIV, 10)
assert st2["b"] == "-" * 9 and st2["w"] == "" and st2["r"] > st["r"]

# ---- xo PvP in group
st, _ = wq(A, "xo:m:0", GRP, 20)
assert st["p"][0] == A["id"] and st["n"][0] == "Анна"
st, _ = wq(A, "xo:m:1", GRP, 20)
assert st["e"] == "Сейчас не ваш ход"
st, _ = wq(B, "xo:m:4", GRP, 20)
assert st["p"] == [1001, 1002] and st["b"][4] == "o"
st, _ = wq(C, "xo:m:5", GRP, 20)
assert st["e"] == "В игре уже два игрока"
st, _ = wq(A, "xo:m:4", GRP, 20)
assert st["e"] == "Клетка занята"
for who, cell in [(A, 1), (B, 3), (A, 2)]:  # A: 0,1,2 -> win
    st, _ = wq(who, f"xo:m:{cell}", GRP, 20)
assert st["w"] == "x", st
st, _ = wq(B, "xo:m:6", GRP, 20)
assert "окончена" in st["e"]

# ---- xo via inline message (no chat info, even if tapped in a private chat)
st, edit = wq(A, "xo:m:0", None, inline="IM1")
assert edit == {"inline_message_id": "IM1", "chat_data": edit["chat_data"]}
assert st["p"] == [1001, 0]
st, _ = wq(B, "xo:m:1", None, inline="IM1")
assert st["p"] == [1001, 1002] and st["b"][:2] == "xo"  # PvP, no bot even if tapped in a private chat

# ---- rps: hidden picks never reach chat_data
st, edit = wq(A, "rps:m:0", GRP, 30)
assert st["d"] == [1, 0] and "_k" not in st and "_k" not in edit["chat_data"]
assert st["l"] == []
st, _ = wq(A, "rps:m:1", GRP, 30)
assert st["e"].startswith("Ты уже выбрал")
st, _ = wq(B, "rps:m:2", GRP, 30)  # rock beats scissors
assert st["l"] == [0, 2] and st["s"] == [1, 0] and st["d"] == [0, 0]
for _ in range(2):
    wq(A, "rps:m:0", GRP, 30)
    st, _ = wq(B, "rps:m:2", GRP, 30)
assert st["w"] == 0 and st["s"][0] == 3
st, _ = wq(A, "rps:m:0", GRP, 30)
assert "окончен" in st["e"]
st, _ = wq(B, "rps:n", GRP, 30)
assert st["s"] == [0, 0] and st["w"] == -1
# rps vs bot
st, _ = wq(A, "rps:m:1", PRIV, 31)
assert st["l"] and st["n"][1] == "Бот"

# ---- bad input
st, _ = bot_resp = (None, None)
CALLS.clear()
bot.on_widget_query({"id": "x", "from": A, "chat": PRIV, "message_id": 1, "data": "zzz"})
assert json.loads(CALLS[-1][1]["data"])["e"] == "Некорректный запрос"

# ---- inline results
CALLS.clear()
bot.on_inline({"id": "iq", "query": ""})
res = CALLS[-1][1]["results"]
assert [r["id"] for r in res] == ["xo", "rps", "snake", "2048"]
assert all(r["input_message_content"]["html"] and r["input_message_content"]["caption"] for r in res)
assert res[0]["input_message_content"]["allow_queries"] is True
assert res[2]["input_message_content"]["allow_queries"] is False
CALLS.clear()
bot.on_inline({"id": "iq", "query": "змей"})
assert [r["id"] for r in CALLS[-1][1]["results"]] == ["snake"]

# ---- commands & menu
CALLS.clear()
bot.on_message({"chat": GRP, "text": "/games@gamesbot"})
assert CALLS[-1][0] == "sendMessage" and len(CALLS[-1][1]["reply_markup"]["inline_keyboard"]) == 4
CALLS.clear()
bot.on_message({"chat": GRP, "text": "/games@otherbot"})
assert not CALLS
bot.on_message({"chat": GRP, "text": "/2048"})
assert CALLS[-1][0] == "sendWidget" and CALLS[-1][1]["chat_id"] == -100
CALLS.clear()
bot.on_callback({"id": "cb", "data": "g:snake", "message": {"chat": GRP}})
assert [m for m, _ in CALLS] == ["sendWidget", "answerCallbackQuery"]

# ---- state survives a restart
import importlib  # noqa: E402
assert json.loads(open(os.environ["STATE_FILE"]).read())
print("ALL OK")
