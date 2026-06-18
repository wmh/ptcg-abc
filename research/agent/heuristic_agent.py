"""Rule-based heuristic agent tuned for the Mega Lucario ex deck.

Priority order each turn:
1. Attack if it KOs opponent's active Pokémon
2. Use Dusknoir Cursed Blast ability to soften a target
3. Attack for maximum damage (prefer Mega Brave when enough energy)
4. Evolve (Riolu→Lucario, Duskull→Dusclops→Dusknoir)
5. Attach energy to active or most-energy-hungry bench Pokémon
6. Play Supporter (Boss's Orders > Iris > Judge > Brock > Dawn)
7. Play Item (Buddy-Buddy Poffin > Ultra Ball > Night Stretcher > Switch)
8. End turn
"""
from __future__ import annotations
from env.game_state import Observation, ActivePokemon
from env.actions import Action, ActionType, attack, end_turn, attach_energy, evolve
from agent.base_agent import BaseAgent


class HeuristicAgent(BaseAgent):
    def act(self, observation: Observation) -> Action:
        legal = observation.legal_actions
        if not legal:
            return end_turn()
        if len(legal) == 1:
            return legal[0]

        for priority_fn in [
            self._try_ko_attack,
            self._try_best_attack,
            self._try_evolve,
            self._try_attach_energy,
            self._try_play_supporter,
            self._try_play_item,
        ]:
            action = priority_fn(observation, legal)
            if action is not None:
                return action

        return end_turn()

    # ─── Priority actions ─────────────────────────────────────────────────

    def _try_ko_attack(self, obs: Observation, legal: list[Action]) -> Action | None:
        if obs.first_turn or obs.opp_active is None or obs.my_active is None:
            return None
        for a in legal:
            if a.action_type == ActionType.ATTACK:
                if self._calc_damage(obs, a.attack_idx) >= obs.opp_active.remaining_hp:
                    return a
        return None

    def _try_best_attack(self, obs: Observation, legal: list[Action]) -> Action | None:
        if obs.first_turn or obs.my_active is None:
            return None
        best_action, best_dmg = None, -1
        for a in legal:
            if a.action_type == ActionType.ATTACK:
                dmg = self._calc_damage(obs, a.attack_idx)
                if dmg > best_dmg:
                    best_dmg, best_action = dmg, a
        return best_action

    def _try_evolve(self, obs: Observation, legal: list[Action]) -> Action | None:
        # Prioritise: Lucario ex > Dusknoir > Dusclops
        priority = ["Mega Lucario ex", "Dusknoir", "Dusclops"]
        for target_name in priority:
            for a in legal:
                if a.action_type == ActionType.EVOLVE_POKEMON:
                    card = obs.my_hand[a.source_idx]
                    if card.name == target_name:
                        return a
        for a in legal:
            if a.action_type == ActionType.EVOLVE_POKEMON:
                return a
        return None

    def _try_attach_energy(self, obs: Observation, legal: list[Action]) -> Action | None:
        if obs.my_attached_energy_this_turn:
            return None
        # Prefer attaching to active (target_idx == -1)
        for a in legal:
            if a.action_type == ActionType.ATTACH_ENERGY and a.target_idx == -1:
                return a
        for a in legal:
            if a.action_type == ActionType.ATTACH_ENERGY:
                return a
        return None

    def _try_play_supporter(self, obs: Observation, legal: list[Action]) -> Action | None:
        if obs.my_supporter_played:
            return None
        priority = [
            ("Boss's Orders", lambda: bool(obs.opp_bench)),
            ("Iris's Fighting Spirit", lambda: True),
            ("Judge", lambda: obs.opp_prizes_remaining <= obs.my_prizes_remaining),
            ("Brock's Scouting", lambda: True),
            ("Dawn", lambda: True),
        ]
        for name, condition in priority:
            if not condition():
                continue
            for a in legal:
                if a.action_type == ActionType.PLAY_SUPPORTER:
                    if obs.my_hand[a.source_idx].name == name:
                        return a
        # Any supporter
        for a in legal:
            if a.action_type == ActionType.PLAY_SUPPORTER:
                return a
        return None

    def _try_play_item(self, obs: Observation, legal: list[Action]) -> Action | None:
        priority = [
            "Buddy-Buddy Poffin",
            "Ultra Ball",
            "Master Ball",
            "Night Stretcher",
            "Switch",
            "Pokégear 3.0",
            "Rare Candy",
        ]
        for name in priority:
            for a in legal:
                if a.action_type == ActionType.PLAY_ITEM:
                    if obs.my_hand[a.source_idx].name == name:
                        return a
        return None

    # ─── Helpers ─────────────────────────────────────────────────────────

    def _calc_damage(self, obs: Observation, attack_idx: int) -> int:
        if obs.my_active is None or obs.opp_active is None:
            return 0
        if attack_idx >= len(obs.my_active.card.attacks):
            return 0
        atk = obs.my_active.card.attacks[attack_idx]
        base = atk.damage

        # Weakness ×2
        my_type  = obs.my_active.card.poke_type
        opp_weak = obs.opp_active.card.weakness
        if my_type is not None and opp_weak is not None and my_type == opp_weak:
            base *= 2

        # Maximum Belt: +50 vs ex
        has_max_belt = any(
            getattr(t, 'name', '') == "Maximum Belt"
            for t in [obs.my_active.attached_tool] if t is not None
        )
        if has_max_belt and obs.opp_active.card.is_ex:
            base += 50

        # Variable damage (×): rough estimate using energy count
        if atk.modifier == "×" and base > 0:
            energy_total = len(obs.my_active.attached_energy)
            base = base * max(energy_total, 1)

        return base
