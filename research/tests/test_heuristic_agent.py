"""Test heuristic agent decision making."""
import pytest
from env.game_state import Observation, ActivePokemon
from env.actions import Action, ActionType, attack, end_turn, attach_energy
from agent.heuristic_agent import HeuristicAgent
from deck.card_db import get_card, Card


def _make_active(card: Card, damage: int = 0, energies: int = 0) -> ActivePokemon:
    energy_card = get_card(6)  # Basic {F} Energy
    return ActivePokemon(
        card=card,
        damage_counters=damage,
        attached_energy=[energy_card] * energies,
    )


def _make_obs(my_active=None, opp_active=None, legal=None, first_turn=False,
              my_hand=None) -> Observation:
    return Observation(
        my_hand=my_hand or [],
        my_active=my_active,
        my_bench=[],
        my_prizes_remaining=3,
        my_discard=[],
        my_deck_size=40,
        my_supporter_played=False,
        my_attached_energy_this_turn=False,
        opp_active=opp_active,
        opp_bench=[],
        opp_prizes_remaining=3,
        opp_discard=[],
        opp_hand_size=4,
        opp_deck_size=40,
        turn_number=5,
        is_my_turn=True,
        first_turn=first_turn,
        legal_actions=legal or [end_turn()],
    )


def test_agent_returns_action():
    agent = HeuristicAgent()
    obs = _make_obs(legal=[end_turn()])
    result = agent.act(obs)
    assert isinstance(result, Action)


def test_agent_prefers_ko_attack():
    """Agent should prefer an attack that KOs the opponent."""
    agent = HeuristicAgent()
    lucario = get_card(678)   # Mega Lucario ex
    riolu   = get_card(677)   # Riolu HP=80

    my  = _make_active(lucario, energies=2)
    opp = _make_active(riolu, damage=60)   # 20 HP left → Mega Brave (270) KOs

    ko_attack   = attack(1)   # Mega Brave: 270 dmg
    weak_attack = attack(0)   # Aura Jab: 130 dmg

    obs = _make_obs(my_active=my, opp_active=opp, legal=[weak_attack, ko_attack])
    chosen = agent.act(obs)
    assert chosen.action_type == ActionType.ATTACK


def test_agent_ends_turn_when_no_options():
    agent = HeuristicAgent()
    obs = _make_obs(legal=[end_turn()])
    assert agent.act(obs).action_type == ActionType.END_TURN


def test_agent_attaches_energy():
    agent = HeuristicAgent()
    att = attach_energy(0, -1)  # hand index 0 → active
    obs = _make_obs(legal=[att, end_turn()])
    result = agent.act(obs)
    assert result.action_type == ActionType.ATTACH_ENERGY
