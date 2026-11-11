# Telegram Games Bot (Bot API 10.4 widgets)

4 игры в виджетах: ❌ Крестики-нолики, ✂️ Камень-ножницы-бумага, 🐍 Змейка, 🔢 2048.

## Запуск
    pip install -r requirements.txt
    export BOT_TOKEN=...        # от @BotFather
    export TG_TEST=1            # тестовый сервер (нужен для групп и @-режима, см. ниже)
    python bot.py

В @BotFather: `/setinline` — включить inline-режим (для вызова через @бот).

## Где что работает (на 11.11.2026)
| Режим                              | Прод | Тестовый сервер |
|------------------------------------|:----:|:---------------:|
| Личный чат с ботом (/games, /xo …) | да   | да              |
| Группы (/games@бот)                | нет  | да              |
| @бот + выбор игры в любом чате     | нет  | да              |

Тестовый сервер: аккаунт Telegram в test-окружении (в десктопном клиенте — Shift+Alt+правый клик
по иконке «Add Account» → Test Server), бот создаётся там же через @BotFather.
Бот в группе должен иметь право `can_send_other_messages`.

## Архитектура
- Состояние игр (xo, rps) хранит бот (`state.json`), виджет только рисует `chatData`
  и шлёт `TelegramWidget.request("xo:m:4")`. Бот отвечает `answerWidgetQuery` и пишет
  состояние в `editMessageWidgetData`. Скрытые ходы (камень/ножницы) лежат в ключах `_*` и в виджет не уходят.
- Змейка и 2048 целиком работают внутри виджета (`allow_queries=false`), рекорды — в `localStorage`.
- Лимиты: виджет ≤ 32 КБ / 4 КБ после zlib (сейчас ~1–1.2 КБ каждый), chat_data ≤ 1024 байт.

## Тесты
    python test_bot.py

## Деплой на Render
См. render.yaml (Background Worker, тариф Starter, диск 1 ГБ для state.json).
Секрет BOT_TOKEN задаётся в панели Render. TG_TEST=1 — только если токен от бота на тестовом сервере.
