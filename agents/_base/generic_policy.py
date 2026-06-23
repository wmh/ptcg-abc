"""GenericPolicy — a competent-enough BasePolicy for ANY deck, so a bare decklist becomes a
usable cabt opponent without writing a bespoke pilot. Derives its config (attackers, energy
types, first/second) from card data, implements the abstract hooks with sensible card-driven
defaults, and inherits the generic energy discipline. Not meant to be a top pilot — just a fair,
non-crashing opponent that plays the deck's gameplan (set up the line, attack for damage/lethal).

Use `make_generic_agent(deck_ids)` to get an `agent(obs_dict)` callable for a 60-card deck.
"""
from __future__ import annotations

from policy_base import (
    BasePolicy, make_agent, new_diag, card_table, attack_table, get_card,
    prize_count, AreaType, CardType, EnergyType, OptionType, Pokemon,
)


def _top_damage(card):
    best = 0
    for aid in (getattr(card, 'attacks', None) or []):
        a = attack_table.get(aid)
        best = max(best, getattr(a, 'damage', 0) or 0)
    return best


class GenericPolicy(BasePolicy):
    # set per-deck by the factory:
    ENERGY_TYPES: set = set()
    ATTACKER_IDS: set = set()
    GO_FIRST: bool = True

    def go_first(self):
        return self.GO_FIRST

    def score_ability(self, o):
        # MEASURED (vs top Chandelure pilots): GenericPolicy under-used abilities (engine pilots use
        # them 310x; we used ~0 because the flat 9000 sat below draw supporters). Abilities are
        # usually the deck's ENGINE (free draw/search/accel/damage) and should out-rank playing a
        # supporter for the same effect. Shared fix -> lifts every generic-piloted opponent.
        card = get_card(self.obs, o.area, o.index, self.my_index)
        d = card_table.get(card.id) if card is not None else None
        txt = ' '.join((s.text or '') for s in (d.skills or [])).lower() if d else ''
        if any(k in txt for k in ('draw', 'search', 'look at', 'into your hand')):
            return 17000        # draw/search engine -> above supporters (14000)
        if any(k in txt for k in ('damage counter', 'damage to', 'knock out')):
            return 12000        # offensive ability (e.g. Chandelure spread)
        if any(k in txt for k in ('energy', 'attach', 'switch', 'move')):
            return 11000        # accel / repositioning
        return 9500

    def score_play_poke(self, card):
        d = card_table.get(card.id)
        n = self.field[card.id]
        if d is None:
            return 0
        # Bench Basics that start/advance the attacker line; don't flood duplicates.
        base = 15000
        if d.megaEx or d.ex:
            base = 13000        # big attackers are usually evolved into; bench the pre-evos first
        if getattr(d, 'evolvesFrom', None):
            base = 16000        # a basic that itself is a pre-evolution to develop
        return base - 350 * n

    def score_play_trainer(self, card):
        d = card_table.get(card.id)
        if d is None:
            return 0
        ct = d.cardType
        txt = ' '.join((s.text or '') for s in (d.skills or [])).lower()
        if ct == CardType.SUPPORTER:
            if self.state.supporterPlayed:
                return 50
            # SEARCH supporters (find a needed piece) stay high; pure DRAW/refill is HAND-AWARE —
            # top pilots don't burn a draw supporter on an already-full hand (we over-played
            # Lillie's 375x). Scale draw by how empty the hand is.
            if any(k in txt for k in ('search', 'look at')):
                return 14000
            if 'draw' in txt:
                h = self.me.handCount
                return 14000 if h <= 3 else (8000 if h <= 5 else 2500)
            return 9000
        if ct == CardType.ITEM:
            # energy-search items are useful only while we still need energy in hand
            if 'energy' in txt and any(k in txt for k in ('search', 'put into your hand')):
                have_energy = any(self.is_energy(c.id) for c in self.me.hand)
                return 9000 if not have_energy else 1500
            if any(k in txt for k in ('search', 'draw', 'put', 'attach')):
                return 10000
            return 6000
        if ct == CardType.STADIUM:
            return 8000 if self.stadium_id != card.id else 100
        if ct == CardType.TOOL:
            return 7000
        return 5000

    def score_evolve(self, o):
        card = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        if card is None:
            return 0
        d = card_table.get(card.id)
        # Evolving is almost always correct; prefer the biggest payoff.
        return 20000 + (1500 if (d and (d.megaEx or d.ex)) else 0) + (500 if (d and d.stage2) else 0)

    def _dmg(self, aid, target):
        a = attack_table.get(aid)
        base = getattr(a, 'damage', 0) or 0
        d = card_table.get(target.id) if target is not None else None
        if d is not None and base and getattr(a, 'energies', None):
            # weakness x2 if the attack's first energy type matches the target weakness type
            if d.weakness is not None and d.weakness in (a.energies or []):
                base *= 2
        return base

    def score_attack(self, o):
        active = self.me.active[0] if self.me.active else None
        opp = self.opponent.active[0] if self.opponent.active else None
        if active is None or opp is None:
            return 800
        aid = o.attackId
        dmg = self._dmg(aid, opp)
        if dmg > 0 and opp.hp <= dmg and prize_count(opp) >= len(self.me.prize):
            return 95000                       # lethal that wins now
        if dmg <= 0:
            return 600                         # status/utility attack -> last resort over END
        score = 1000 + min(dmg, 320)
        if opp.hp <= dmg:
            score += 2500 + prize_count(opp) * 250
        return score


def make_generic_agent(deck_ids):
    """Build an agent(obs_dict) for a 60-card deck using GenericPolicy, with config derived from
    the deck: attackers = ex/megaEx or Stage-2 Pokémon; energy types = energy cards present;
    go-first if the deck is setup-heavy (has any Stage-2)."""
    deck_ids = list(deck_ids)
    pokes = [cid for cid in set(deck_ids) if card_table.get(cid) and getattr(card_table[cid], 'hp', None)]
    attackers = {cid for cid in pokes
                 if card_table[cid].megaEx or card_table[cid].ex or card_table[cid].stage2}
    if not attackers:                          # fallback: highest-HP bodies
        attackers = set(sorted(pokes, key=lambda c: -(card_table[c].hp or 0))[:2])
    energies = {cid for cid in set(deck_ids)
                if card_table.get(cid) and card_table[cid].cardType in
                (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY)}
    go_first = any(card_table[c].stage2 for c in pokes)

    class _Cfg(GenericPolicy):
        ENERGY_TYPES = energies
        ATTACKER_IDS = attackers
        GO_FIRST = go_first

    return make_agent(_Cfg, deck_ids, new_diag())
