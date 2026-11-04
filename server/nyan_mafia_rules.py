"""Pure, testable rules for NYAN MAFIA.

The public API never sends these secret assignments to another player.  This
module only handles choosing roles and deciding a winner; SQL transactions and
Telegram authentication live in nyan_mafia.py.
"""

from __future__ import annotations

import secrets
from collections import Counter


TEAM = {
    "civilian": "town", "commissioner": "town", "doctor": "town",
    "bodyguard": "town", "journalist": "town", "lover": "town",
    "immortal": "town", "kamikaze": "town", "lawyer": "town",
    "mafia": "mafia", "don": "mafia", "maniac": "solo",
}

ROLE_TITLE = {
    "civilian": "мирный житель", "commissioner": "комиссар", "doctor": "доктор",
    "bodyguard": "телохранитель", "journalist": "журналист", "lover": "любовница",
    "immortal": "бессмертный", "kamikaze": "камикадзе", "lawyer": "адвокат",
    "mafia": "мафия", "don": "дон мафии", "maniac": "маньяк",
}

ROLE_HINT = {
    "civilian": "днём общайся, вычисляй мафию и голосуй за подозреваемых.",
    "mafia": "ночью выбирай жертву вместе с сообщниками в закрытом чате.",
    "don": "ты возглавляешь мафию: ночью выбирай жертву вместе с командой.",
    "commissioner": "ночью проверь одного игрока — узнаешь, на стороне ли он мафии.",
    "doctor": "каждую ночь спаси одного игрока от нападения.",
    "bodyguard": "выбери, кого защищать ночью. при нападении погибнешь вместо него.",
    "journalist": "ночью сравни двух игроков и узнай, принадлежат ли они одной команде.",
    "lover": "ночью выбери игрока — он не сможет выполнить своё действие.",
    "immortal": "первое смертельное нападение ты переживёшь.",
    "kamikaze": "ночью назначь цель. если тебя убьют, она погибнет вместе с тобой.",
    "lawyer": "ночью защити одного игрока от ближайшего дневного изгнания.",
    "maniac": "ты играешь один. ночью выбирай жертву и оставайся последним.",
}

NIGHT_ACTION = {
    "mafia": "kill", "don": "kill", "maniac": "kill",
    "commissioner": "inspect", "doctor": "heal", "bodyguard": "guard",
    "journalist": "compare", "lover": "block", "lawyer": "defend",
    "kamikaze": "revenge",
}


def role_deck(player_count: int) -> list[str]:
    """Return a balanced deck of exactly player_count roles, 4..20 players."""
    if not 4 <= player_count <= 20:
        raise ValueError("нужно от 4 до 20 участников")

    deck = ["mafia"]
    if player_count >= 8:
        deck.append("mafia")
    if player_count >= 10:
        deck[0] = "don"
    if player_count >= 16:
        deck.append("mafia")

    for threshold, role in (
        (6, "doctor"), (7, "commissioner"), (9, "bodyguard"),
        (11, "maniac"), (12, "journalist"), (13, "lover"),
        (14, "immortal"), (15, "lawyer"), (16, "kamikaze"),
    ):
        if player_count >= threshold:
            deck.append(role)

    deck.extend(["civilian"] * (player_count - len(deck)))
    return deck


def shuffle_deck(player_count: int) -> list[str]:
    deck = role_deck(player_count)
    secrets.SystemRandom().shuffle(deck)
    return deck


def winner_for_roles(alive_roles: list[str]) -> str | None:
    """Mafia wins at parity only after the lone maniac is gone."""
    if not alive_roles:
        return "draw"
    counts = Counter(TEAM[role] for role in alive_roles)
    mafia = counts["mafia"]
    solo = counts["solo"]
    town = counts["town"]
    if solo and not mafia and town <= 1:
        return "maniac"
    if not mafia and not solo:
        return "civilians"
    if mafia and not solo and mafia >= town:
        return "mafia"
    return None
