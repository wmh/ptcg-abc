"""Competition deck lists using official card IDs.

Reference:  docs/official/EN_Card_Data.csv
JP meta:    pokemon-tcg-jp-scraper — Mega Lucario ex ranks #1 with 34 wins
Sample:     docs/3rd-party/A Sample Rule-Based Agent Mega Lucario ex Deck/main.py

Deck: Mega Lucario ex (60 cards)
Key mechanics:
  - Mega Lucario ex: Aura Jab {F}→160 (+Premium Power Pro), attaches 3 F from discard
  - Mega Brave {F}{F}→300 on alternate turns
  - Hariyama: Heave-Ho Catcher ability — free Boss's Orders on evolve
  - Solrock: Cosmic Beam {F}→100 (with Premium Power Pro + Lunatone on bench)
  - Premium Power Pro: +30 to all Fighting attacks
  - Fighting Gong: search F energy or F Pokémon
  - Poké Pad: search any non-Rule Box Pokémon
  - Carmine: draw Supporter usable on turn 1
  - Gravity Mountain: Stage 2 Pokémon -30 HP (makes Hariyama hits land easier)
"""
from __future__ import annotations
from deck.card_db import get_card, Card


# ─── Card ID constants (competition pool) ────────────────────────────────────

# Pokémon
MAKUHITA         = 673   # HP 80, Basic {F}
HARIYAMA         = 674   # Stage 1, Ability: Heave-Ho Catcher (Boss on evolve), Wild Press {F}{F}{F}→210
LUNATONE         = 675   # Ability: discard {F} → draw 3 (draw engine)
SOLROCK          = 676   # Cosmic Beam {F}→70 (only with Lunatone on bench, bypasses W/R)
RIOLU            = 677   # HP 80, Basic {F}
MEGA_LUCARIO_EX  = 678   # Stage 1 Mega ex, Aura Jab {F}→130+energy, Mega Brave {F}{F}→270

# Trainers — Items
DUSK_BALL        = 1102  # Look at bottom 7 of deck, take 1 Pokémon
SWITCH           = 1123  # Switch Active ↔ Bench
PREMIUM_POWER_PRO = 1141 # This turn, your {F} Pokémon attacks do +30
FIGHTING_GONG    = 1142  # Search deck for 1 Basic {F} energy or 1 Basic {F} Pokémon
POKE_PAD         = 1152  # Search deck for 1 non-Rule Box Pokémon
HERO_CAPE        = 1159  # Tool: Pokémon this is attached to gets +100 HP

# Trainers — Supporters
BOSS_ORDERS      = 1182  # Switch opponent's benched Pokémon → active
CARMINE          = 1192  # (Can use on turn 1) Discard hand, draw 5
LILLIE_DETERM    = 1227  # Shuffle hand into deck, draw 6 (8 if you have all 6 prizes)

# Trainers — Stadiums
GRAVITY_MOUNTAIN = 1252  # Each Stage 2 Pokémon in play gets -30 HP

# Energy
BASIC_FIGHTING   = 6     # Basic {F} Energy


# ─── Deck list (60 cards) ────────────────────────────────────────────────────

# fmt: off
LUCARIO_DECK_SPEC: list[tuple[int, int]] = [
    # Pokémon (18)
    (MAKUHITA,          2),   # Evolves into Hariyama (Heave-Ho Catcher)
    (HARIYAMA,          2),   # Ability Boss + 210dmg attacker
    (LUNATONE,          2),   # Draw engine
    (SOLROCK,           3),   # Cheap bridge attacker (100 with PPP)
    (RIOLU,             3),   # Evolves into Mega Lucario ex
    (MEGA_LUCARIO_EX,   4),   # Main attacker (Mega ex = 3 prizes when KO'd)
    # Trainers — Items (19)
    (DUSK_BALL,         4),   # Bottom-7 Pokémon search
    (SWITCH,            2),   # Mobility
    (PREMIUM_POWER_PRO, 4),   # +30 to all Fighting attacks
    (FIGHTING_GONG,     4),   # Search F energy or F Basic
    (POKE_PAD,          4),   # Search non-Rule Box Pokémon
    (HERO_CAPE,         1),   # +100 HP to Lucario / Hariyama
    # Trainers — Supporters (10)
    (BOSS_ORDERS,       2),   # Bring up high-value benched target
    (CARMINE,           4),   # Turn-1 draw: discard hand, draw 5
    (LILLIE_DETERM,     4),   # Main draw: shuffle + draw 6 (8 at game start)
    # Trainers — Stadiums (4)
    (GRAVITY_MOUNTAIN,  2),   # Stage 2 Pokémon -30 HP (softens opponent)
    # Energy (13)
    (BASIC_FIGHTING,   13),   # {F} Energy (Aura Jab pulls 3 back from discard)
]
# fmt: on

_TOTAL = sum(cnt for _, cnt in LUCARIO_DECK_SPEC)
assert _TOTAL == 60, f"Deck has {_TOTAL} cards, expected 60"


def build_lucario_deck() -> list[Card]:
    deck: list[Card] = []
    for card_id, count in LUCARIO_DECK_SPEC:
        card = get_card(card_id)
        deck.extend([card] * count)
    return deck
