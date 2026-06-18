"""Pokemon TCG action definitions."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class ActionType(Enum):
    # Playing cards from hand
    PLAY_BASIC_POKEMON_ACTIVE = auto()  # Put basic pokemon as active
    PLAY_BASIC_POKEMON_BENCH = auto()   # Put basic pokemon on bench
    EVOLVE_POKEMON = auto()             # Evolve a pokemon
    PLAY_ITEM = auto()                  # Play item card
    PLAY_SUPPORTER = auto()             # Play supporter card
    PLAY_STADIUM = auto()               # Play stadium card
    ATTACH_ENERGY = auto()              # Attach energy from hand
    ATTACH_TOOL = auto()                # Attach tool to pokemon

    # In-battle actions
    ATTACK = auto()                     # Use a pokemon attack
    RETREAT = auto()                    # Retreat active pokemon
    USE_ABILITY = auto()                # Use pokemon ability

    # Turn management
    END_TURN = auto()

    # Forced choices (responses to effects)
    CHOOSE_POKEMON = auto()             # Choose a pokemon (e.g., for retreat target)
    CHOOSE_CARD = auto()                # Choose a card (e.g., from discard)
    CHOOSE_PRIZE = auto()               # Choose a prize card to take


@dataclass
class Action:
    action_type: ActionType
    # Indices into relevant lists (hand, bench, etc.)
    source_idx: Optional[int] = None   # e.g., hand index for the card being played
    target_idx: Optional[int] = None   # e.g., bench index for evolution target
    attack_idx: Optional[int] = None   # which attack to use
    retreat_target_idx: Optional[int] = None  # bench index to retreat to

    def __str__(self) -> str:
        parts = [self.action_type.name]
        if self.source_idx is not None:
            parts.append(f"src={self.source_idx}")
        if self.target_idx is not None:
            parts.append(f"tgt={self.target_idx}")
        if self.attack_idx is not None:
            parts.append(f"atk={self.attack_idx}")
        return f"Action({', '.join(parts)})"


def end_turn() -> Action:
    return Action(ActionType.END_TURN)


def play_basic_to_bench(hand_idx: int) -> Action:
    return Action(ActionType.PLAY_BASIC_POKEMON_BENCH, source_idx=hand_idx)


def play_basic_as_active(hand_idx: int) -> Action:
    return Action(ActionType.PLAY_BASIC_POKEMON_ACTIVE, source_idx=hand_idx)


def attach_energy(hand_idx: int, target_idx: int) -> Action:
    """Attach energy from hand to active (target_idx=-1) or bench pokemon (target_idx=0..4)."""
    return Action(ActionType.ATTACH_ENERGY, source_idx=hand_idx, target_idx=target_idx)


def attack(attack_idx: int) -> Action:
    return Action(ActionType.ATTACK, attack_idx=attack_idx)


def retreat(bench_idx: int) -> Action:
    return Action(ActionType.RETREAT, retreat_target_idx=bench_idx)


def play_supporter(hand_idx: int) -> Action:
    return Action(ActionType.PLAY_SUPPORTER, source_idx=hand_idx)


def play_item(hand_idx: int) -> Action:
    return Action(ActionType.PLAY_ITEM, source_idx=hand_idx)


def evolve(hand_idx: int, target_idx: int) -> Action:
    """Evolve pokemon in play. target_idx: -1=active, 0..4=bench."""
    return Action(ActionType.EVOLVE_POKEMON, source_idx=hand_idx, target_idx=target_idx)
