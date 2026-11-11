#!/usr/bin/env python3
"""Telegram bot with 4 games running inside Bot API 10.4 widgets.

Games:
  xo     - tic-tac-toe (2 players, or vs the bot in a private chat)   [bot-driven]
  rps    - rock-paper-scissors, first to 3 (hidden picks)              [bot-driven]
  snake  - snake                                                       [runs in the widget]
  2048   - 2048                                                        [runs in the widget]

Env:
  BOT_TOKEN  token from @BotFather
  TG_TEST=1  use the Telegram test server (needed for groups / inline mode today)
"""
import copy
import json
import logging
import os
import random
import sys
from collections import OrderedDict
from pathlib import Path

import requests

HERE = Path(__file__).parent
TOKEN = os.environ.get("BOT_TOKEN", "9245792127:AAFEVBCz9JX8CeX64RteHKkLTC4mdKoJ6VA")
TEST = os.environ.get("TG_TEST", "") == "1"
API = f"https://api.telegram.org/bot{TOKEN}/" + ("test/" if TEST else "")
STATE_FILE = Path(os.environ.get("STATE_FILE", HERE / "state.json"))
MAX_STATES = 5000

log = logging.getLogger("games")
SESSION = requests.Session()
BOT_USERNAME = ""


# --------------------------------------------------------------------------- API
class TgError(Exception):
    def __init__(self, code, desc, params=None):
        super().__init__(f"{code}: {desc}")
        self.code, self.desc, self.params = code, desc or "", params or {}


def call(method, _timeout=30, **params):
    params = {k: v for k, v in params.items() if v is not None}
    r = SESSION.post(API + method, json=params, timeout=_timeout)
    try:
        j = r.json()
    except ValueError:
        raise TgError(r.status_code, r.text[:200])
    if not j.get("ok"):
        raise TgError(j.get("error_code"), j.get("description"), j.get("parameters"))
    return j["result"]


# ------------------------------------------------------------------------- state
class Store:
    """Authoritative state of every game message (the widget only draws it)."""

    def __init__(self, path):
        self.path, self.d = path, OrderedDict()
        try:
            self.d.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def get(self, key):
        return self.d.get(key)

    def set(self, key, val):
        self.d[key] = val
        self.d.move_to_end(key)
        while len(self.d) > MAX_STATES:
            self.d.popitem(last=False)
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            log.exception("cannot save state")


STORE = Store(STATE_FILE)


def pub(s):
    """The part of the state the widget sees (chat_data). Keys starting with _ stay on the bot."""
    return {k: v for k, v in s.items() if not k.startswith("_")}


def dumps(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def short(u):
    return (u.get("first_name") or "Игрок").strip()[:12] or "Игрок"


# ------------------------------------------------------------------- tic-tac-toe
LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]


def xo_new():
    return {"b": "-" * 9, "t": "x", "w": "", "p": [0, 0], "n": ["", ""], "r": 0}


def xo_result(b):
    for a, c, d in LINES:
        if b[a] != "-" and b[a] == b[c] == b[d]:
            return b[a]
    return "d" if "-" not in b else ""


def xo_bot_move(b, me="o", foe="x"):
    free = [i for i, c in enumerate(b) if c == "-"]

    def finishing(side):
        for a, c, d in LINES:
            cells = [b[a], b[c], b[d]]
            if cells.count(side) == 2 and cells.count("-") == 1:
                return (a, c, d)[cells.index("-")]
        return None

    for side in (me, foe):  # win, otherwise block
        m = finishing(side)
        if m is not None:
            return m
    for pref in ([4], [0, 2, 6, 8], [1, 3, 5, 7]):
        opts = [i for i in pref if i in free]
        if opts:
            return random.choice(opts)
    return random.choice(free)


def xo_act(s, user, cmd, vs_bot):
    uid = user["id"]
    if cmd == "n":
        if not s["w"]:
            return "Партия ещё идёт"
        s.update(b="-" * 9, t="x", w="")
        return None
    if not cmd.startswith("m:"):
        return "Неизвестная команда"
    try:
        i = int(cmd[2:])
        assert 0 <= i <= 8
    except (ValueError, AssertionError):
        return "Неверная клетка"
    if s["w"]:
        return "Партия окончена — нажмите «Новая игра»"
    if s["b"][i] != "-":
        return "Клетка занята"
    side = s["t"]
    k = 0 if side == "x" else 1
    if vs_bot:
        s["p"], s["n"] = [uid, -1], [short(user), "Бот"]
    else:
        if 0 not in s["p"] and uid not in s["p"]:
            return "В игре уже два игрока"
        if uid in s["p"]:
            if s["p"][k] != uid:
                return "Сейчас не ваш ход"
        elif s["p"][k]:
            return "Сейчас не ваш ход"
        else:
            s["p"][k], s["n"][k] = uid, short(user)
    b = list(s["b"])
    b[i] = side
    s["b"] = "".join(b)
    s["w"] = xo_result(s["b"])
    s["t"] = "o" if side == "x" else "x"
    if vs_bot and not s["w"]:
        b[xo_bot_move(b)] = "o"
        s["b"] = "".join(b)
        s["w"] = xo_result(s["b"])
        s["t"] = "x"
    return None


# ----------------------------------------------------------------- rock-paper-scissors
def rps_new():
    return {"s": [0, 0], "p": [0, 0], "n": ["", ""], "d": [0, 0], "l": [], "w": -1, "r": 0,
            "_k": [None, None]}


def rps_act(s, user, cmd, vs_bot):
    uid = user["id"]
    if cmd == "n":
        if s["w"] < 0:
            return "Матч ещё идёт"
        s.update(s=[0, 0], d=[0, 0], l=[], w=-1, _k=[None, None])
        return None
    if not cmd.startswith("m:"):
        return "Неизвестная команда"
    try:
        pick = int(cmd[2:])
        assert 0 <= pick <= 2
    except (ValueError, AssertionError):
        return "Неверный выбор"
    if s["w"] >= 0:
        return "Матч окончен — нажмите «Новый матч»"
    if vs_bot:
        s["p"], s["n"] = [uid, -1], [short(user), "Бот"]
        slot = 0
    elif uid in s["p"]:
        slot = s["p"].index(uid)
    elif 0 in s["p"]:
        slot = s["p"].index(0)
        s["p"][slot], s["n"][slot] = uid, short(user)
    else:
        return "В матче уже два игрока"
    if s["_k"][slot] is not None:
        return "Ты уже выбрал, ждём соперника"
    s["_k"][slot] = pick
    s["d"][slot] = 1
    if vs_bot:
        s["_k"][1], s["d"][1] = random.randrange(3), 1
    if None in s["_k"]:
        return None
    a, b = s["_k"]
    s["l"] = [a, b]
    if a != b:
        win = 0 if (a - b) % 3 == 1 else 1
        s["s"][win] += 1
        if s["s"][win] >= 3:
            s["w"] = win
    s["_k"], s["d"] = [None, None], [0, 0]
    return None


# ------------------------------------------------------------------------ registry
def load_html(name):
    text = (HERE / "widgets" / name).read_text(encoding="utf-8")
    return "\n".join(l.strip() for l in text.splitlines() if l.strip())


GAMES = {
    "xo": dict(title="Крестики-нолики", emoji="❌", file="xo.html", queries=True, new=xo_new,
               act=xo_act, desc="Вдвоём в чате или против бота", kw=["крестики", "нолики", "tictactoe"]),
    "rps": dict(title="Камень-ножницы-бумага", emoji="✂️", file="rps.html", queries=True,
                new=rps_new, act=rps_act, desc="Дуэль до 3 побед", kw=["камень", "ножницы", "бумага"]),
    "snake": dict(title="Змейка", emoji="🐍", file="snake.html", queries=False,
                  desc="Классика, рекорд хранится на устройстве", kw=["snake", "змейка"]),
    "2048": dict(title="2048", emoji="🔢", file="g2048.html", queries=False,
                 desc="Складывай плитки", kw=["2048", "плитки"]),
}
for _id, _g in GAMES.items():
    _g["html"] = load_html(_g["file"])


def widget_content(gid):
    g = GAMES[gid]
    return {"html": g["html"], "caption": f"{g['emoji']} {g['title']}", "allow_queries": g["queries"]}


# ----------------------------------------------------------------------- handlers
def send_game(chat_id, gid, thread_id=None):
    return call("sendWidget", chat_id=chat_id, message_thread_id=thread_id, **widget_content(gid))


def send_menu(chat_id, thread_id=None):
    rows = [[{"text": f"{g['emoji']} {g['title']}", "callback_data": f"g:{gid}"}] for gid, g in GAMES.items()]
    text = "Выбери игру 👇"
    if BOT_USERNAME:
        text += f"\n\nВ любом чате можно написать @{BOT_USERNAME} и выбрать игру."
    call("sendMessage", chat_id=chat_id, text=text, message_thread_id=thread_id,
         reply_markup={"inline_keyboard": rows})


def on_message(m):
    text = (m.get("text") or "").strip()
    if not text.startswith("/"):
        return
    head = text.split()[0][1:]
    cmd, _, target = head.partition("@")
    if target and BOT_USERNAME and target.lower() != BOT_USERNAME.lower():
        return
    chat_id, thread = m["chat"]["id"], m.get("message_thread_id")
    cmd = cmd.lower()
    if cmd in ("start", "games", "menu"):
        send_menu(chat_id, thread)
    elif cmd in GAMES:
        send_game(chat_id, cmd, thread)


def on_callback(cq):
    data = cq.get("data") or ""
    msg = cq.get("message")
    if not data.startswith("g:") or data[2:] not in GAMES or not msg:
        return call("answerCallbackQuery", callback_query_id=cq["id"])
    try:
        send_game(msg["chat"]["id"], data[2:], msg.get("message_thread_id"))
        call("answerCallbackQuery", callback_query_id=cq["id"])
    except TgError as e:
        call("answerCallbackQuery", callback_query_id=cq["id"], text=e.desc[:180], show_alert=True)


def on_inline(iq):
    q = (iq.get("query") or "").strip().lower()
    ids = [gid for gid, g in GAMES.items()
           if not q or q in g["title"].lower() or q in gid or any(q in k for k in g["kw"])]
    results = [{
        "type": "article", "id": gid,
        "title": f"{GAMES[gid]['emoji']} {GAMES[gid]['title']}",
        "description": GAMES[gid]["desc"],
        "input_message_content": widget_content(gid),
    } for gid in (ids or GAMES)]
    call("answerInlineQuery", inline_query_id=iq["id"], results=results, cache_time=300, is_personal=False)


def answer_query(qid, payload):
    data = dumps(payload)
    if len(data.encode()) > 1000:
        data = dumps({"e": "Слишком большое состояние"})
    try:
        call("answerWidgetQuery", widget_query_id=qid, data=data)
    except TgError:
        log.exception("answerWidgetQuery failed")


def on_widget_query(q):
    qid, user, data = q["id"], q["from"], q.get("data") or ""
    try:
        gid, cmd = data.split(":", 1)
        game = GAMES[gid]
        act = game["act"]
    except (ValueError, KeyError):
        return answer_query(qid, {"e": "Некорректный запрос"})

    if "inline_message_id" in q:  # widget was sent via @bot in some chat
        key, vs_bot = "i:" + q["inline_message_id"], False
        target = {"inline_message_id": q["inline_message_id"]}
    else:
        chat = q["chat"]
        key, vs_bot = f"c:{chat['id']}:{q['message_id']}", chat["type"] == "private"
        target = {"chat_id": chat["id"], "message_id": q["message_id"]}

    s = copy.deepcopy(STORE.get(key))
    if not s or s.get("_g") != gid:
        s = game["new"]()
        s["_g"] = gid
    before = dumps(pub(s))
    err = act(s, user, cmd, vs_bot)
    if dumps(pub(s)) != before:
        s["r"] += 1
        try:
            call("editMessageWidgetData", chat_data=dumps(pub(s)), **target)
        except TgError as e:
            low = e.desc.lower()
            if "not modified" in low:
                pass
            elif e.code == 429:
                log.warning("flood wait on edit: %s", e)  # state is still committed, next edit syncs everyone
            else:
                log.error("edit failed: %s", e)
                return answer_query(qid, {**pub(STORE.get(key) or game["new"]()), "e": "Не удалось обновить, попробуй ещё раз"})
    STORE.set(key, s)
    out = pub(s)
    if err:
        out["e"] = err
    answer_query(qid, out)


def dispatch(u):
    if "message" in u:
        on_message(u["message"])
    elif "callback_query" in u:
        on_callback(u["callback_query"])
    elif "inline_query" in u:
        on_inline(u["inline_query"])
    elif "widget_query" in u:
        on_widget_query(u["widget_query"])


ALLOWED = ["message", "callback_query", "inline_query", "widget_query", "shared_widget_query"]


def main():
    global BOT_USERNAME
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not TOKEN:
        sys.exit("Set BOT_TOKEN")
    me = call("getMe")
    BOT_USERNAME = me["username"]
    log.info("@%s started (%s server)", BOT_USERNAME, "TEST" if TEST else "production")
    if not me.get("supports_inline_queries"):
        log.warning("Inline mode is off: enable it with /setinline in @BotFather")
    call("deleteWebhook")
    call("setMyCommands", commands=[{"command": "games", "description": "Выбрать игру"}] +
         [{"command": gid, "description": g["title"]} for gid, g in GAMES.items()])
    offset = None
    while True:
        try:
            updates = call("getUpdates", _timeout=70, offset=offset, timeout=50, allowed_updates=ALLOWED)
        except (requests.RequestException, TgError) as e:
            log.warning("getUpdates: %s", e)
            import time
            time.sleep(3)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                dispatch(u)
            except Exception:
                log.exception("update %s failed", u.get("update_id"))


if __name__ == "__main__":
    main()
