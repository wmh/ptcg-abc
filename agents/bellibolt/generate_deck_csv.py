"""Generate deck.csv for Kaggle submission.

Format: 60 lines, one card ID per line (competition internal ID).

Deck: Iono's Bellibolt ex (60 cards) — the top-meta deck (2026-06-17 data).
Used by leaderboard #1 (onechan1) and #2 (Kyo_s_s). Beats Crustle 91%.

Key mechanics:
  - Iono's Bellibolt ex (269): Stage1 from Tadbulb, HP280, ex.
      Ability "Electric Streamer": attach Basic {L} from hand to any Iono's Pokémon
      as often as you like each turn (the energy engine — bypasses 1/turn limit).
      Thunderous Bolt {L}{L}{L}{C}→230 (can't attack next turn → rotate attackers).
  - Iono's Kilowattrel (271): Stage1 from Wattrel, HP120, NON-ex (Crustle answer).
      Mach Bolt {L}{C}{C}→70. Ability "Flashing Draw": discard a {L} from it → draw to 6.
  - Iono's Voltorb (265): Voltaic Chain {C}{C}→20 + 20 per {L} on all your Iono's Pokémon.
  - Iono's Tadbulb (268): evolves to Bellibolt ex. Iono's Wattrel (270): evolves to Kilowattrel.
  - Levincia (1254): stadium — each turn put up to 2 Basic {L} from discard to hand.
  - Canari (1233): discard 1 → search up to 4 {L} Pokémon to hand.
"""
import os

# (card_id, count)
BELLIBOLT_DECK_SPEC = [
    # Pokémon (15)
    (265, 3),   # Iono's Voltorb  — Voltaic Chain (scaling)
    (268, 3),   # Iono's Tadbulb  — evolves to Bellibolt ex
    (269, 3),   # Iono's Bellibolt ex — main attacker + Electric Streamer engine
    (270, 3),   # Iono's Wattrel  — evolves to Kilowattrel
    (271, 3),   # Iono's Kilowattrel — non-ex attacker + Flashing Draw
    # Trainers (23)
    (1227, 4),  # Lillie's Determination — shuffle hand, draw 6/8
    (1233, 4),  # Canari — search 4 {L} Pokémon (discard 1)
    (1086, 3),  # Buddy-Buddy Poffin — search 2 basics (<=70 HP) to bench
    (1121, 3),  # Ultra Ball — search any Pokémon (discard 2)
    (1254, 3),  # Levincia — stadium, recover 2 {L} energy/turn
    (1097, 2),  # Night Stretcher — recover 1 Pokémon or basic energy
    (1152, 2),  # Poké Pad — search non-Rule-Box Pokémon
    (1110, 1),  # Max Rod — recover up to 5 Pokémon/basic energy
    (1118, 1),  # Energy Retrieval — recover 2 basic energy
    # Energy (22)
    (4, 22),    # Basic {L} Energy
]


def build_deck_ids():
    ids = []
    for cid, cnt in BELLIBOLT_DECK_SPEC:
        ids.extend([cid] * cnt)
    return ids


if __name__ == "__main__":
    deck = build_deck_ids()
    assert len(deck) == 60, f"Deck has {len(deck)} cards, expected 60"
    out = os.path.join(os.path.dirname(__file__), "deck.csv")
    with open(out, "w") as f:
        for cid in deck:
            f.write(f"{cid}\n")
    print(f"Written {len(deck)} card IDs to {out}")
    from collections import Counter
    for cid, cnt in sorted(Counter(deck).items()):
        print(f"  {cnt}x {cid}")
