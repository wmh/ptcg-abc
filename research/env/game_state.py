"""Pokemon TCG game state representation."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class EnergyType(Enum):
    FIRE = "fire"
    WATER = "water"
    GRASS = "grass"
    LIGHTNING = "lightning"
    PSYCHIC = "psychic"
    FIGHTING = "fighting"
    DARKNESS = "darkness"
    METAL = "metal"
    DRAGON = "dragon"
    FAIRY = "fairy"
    COLORLESS = "colorless"


class CardType(Enum):
    POKEMON = auto()
    TRAINER = auto()
    ENERGY = auto()


class PokemonStage(Enum):
    BASIC = auto()
    STAGE1 = auto()
    STAGE2 = auto()
    VSTAR = auto()
    VMAX = auto()


@dataclass
class Attack:
    name: str
    cost: list[EnergyType]
    damage: int
    text: str = ""


@dataclass
class PokemonCard:
    card_id: str
    name: str
    hp: int
    stage: PokemonStage
    energy_type: EnergyType
    attacks: list[Attack]
    retreat_cost: list[EnergyType]
    weakness: Optional[EnergyType] = None
    resistance: Optional[EnergyType] = None
    evolves_from: Optional[str] = None

    def total_retreat_cost(self) -> int:
        return len(self.retreat_cost)


@dataclass
class TrainerCard:
    card_id: str
    name: str
    trainer_type: str  # "Item", "Supporter", "Stadium", "Tool"
    text: str


@dataclass
class EnergyCard:
    card_id: str
    name: str
    energy_type: EnergyType
    is_special: bool = False


Card = PokemonCard | TrainerCard | EnergyCard


@dataclass
class ActivePokemon:
    card: PokemonCard
    damage_counters: int = 0
    attached_energy: list[EnergyCard] = field(default_factory=list)
    attached_tool: Optional[TrainerCard] = None
    status: Optional[str] = None  # "poisoned", "burned", "paralyzed", "asleep", "confused"

    @property
    def remaining_hp(self) -> int:
        return max(0, self.card.hp - self.damage_counters)

    @property
    def is_knocked_out(self) -> bool:
        return self.remaining_hp == 0

    def energy_count(self, energy_type: Optional[EnergyType] = None) -> int:
        if energy_type is None:
            return len(self.attached_energy)
        return sum(1 for e in self.attached_energy if e.energy_type == energy_type)

    def can_attack(self, attack: Attack) -> bool:
        """Check if this pokemon has enough energy for the given attack."""
        required = {e: 0 for e in EnergyType}
        for e in attack.cost:
            required[e] += 1

        available = {e: 0 for e in EnergyType}
        for e in self.attached_energy:
            available[e.energy_type] += 1

        colorless_needed = required.get(EnergyType.COLORLESS, 0)
        for energy_type in EnergyType:
            if energy_type == EnergyType.COLORLESS:
                continue
            specific_needed = required.get(energy_type, 0)
            specific_have = available.get(energy_type, 0)
            if specific_have >= specific_needed:
                available[energy_type] -= specific_needed
            else:
                # Not enough specific energy
                return False

        total_remaining = sum(v for k, v in available.items() if k != EnergyType.COLORLESS)
        return total_remaining >= colorless_needed


@dataclass
class PlayerState:
    deck: list[Card] = field(default_factory=list)
    hand: list[Card] = field(default_factory=list)
    discard: list[Card] = field(default_factory=list)
    prizes: list[Card] = field(default_factory=list)
    active: Optional[ActivePokemon] = None
    bench: list[ActivePokemon] = field(default_factory=list)
    supporter_played: bool = False
    attached_energy_this_turn: bool = False

    @property
    def prize_count(self) -> int:
        return len(self.prizes)

    @property
    def bench_count(self) -> int:
        return len(self.bench)

    @property
    def can_add_to_bench(self) -> bool:
        return self.bench_count < 5

    def has_pokemon_in_play(self) -> bool:
        return self.active is not None or len(self.bench) > 0


@dataclass
class GameState:
    player: PlayerState = field(default_factory=PlayerState)
    opponent: PlayerState = field(default_factory=PlayerState)
    turn_number: int = 1
    is_my_turn: bool = True
    first_turn: bool = True  # First turn cannot attack


@dataclass
class Observation:
    """What the agent can observe (excludes hidden info like opponent's hand/deck)."""
    my_hand: list[Card]
    my_active: Optional[ActivePokemon]
    my_bench: list[ActivePokemon]
    my_prizes_remaining: int
    my_discard: list[Card]
    my_deck_size: int
    my_supporter_played: bool
    my_attached_energy_this_turn: bool

    opp_active: Optional[ActivePokemon]
    opp_bench: list[ActivePokemon]
    opp_prizes_remaining: int
    opp_discard: list[Card]
    opp_hand_size: int
    opp_deck_size: int

    turn_number: int
    is_my_turn: bool
    first_turn: bool

    legal_actions: list["Action"]
