"""Card database built from official EN_Card_Data.csv.

Card IDs are the competition's internal IDs (1–1267).
All stats are sourced directly from the official data file.
"""
from __future__ import annotations
import csv
import os
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import lru_cache
from typing import Optional


# ─── Data types ──────────────────────────────────────────────────────────────

class EnergyType(Enum):
    G = "G"   # Grass
    R = "R"   # Fire
    W = "W"   # Water
    L = "L"   # Lightning
    P = "P"   # Psychic
    F = "F"   # Fighting
    D = "D"   # Darkness
    M = "M"   # Metal
    C = "C"   # Colorless / Dragon (competition uses C for colorless ●)
    DRAGON = "竜"  # Dragon type (appears in data as kanji)

    @classmethod
    def from_symbol(cls, s: str) -> "EnergyType":
        s = s.strip("{}")
        mapping = {
            "G": cls.G, "R": cls.R, "W": cls.W, "L": cls.L,
            "P": cls.P, "F": cls.F, "D": cls.D, "M": cls.M,
            "C": cls.C, "竜": cls.DRAGON,
        }
        return mapping.get(s, cls.C)


@dataclass(frozen=True)
class Attack:
    name: str
    cost: tuple[EnergyType, ...]   # empty tuple = free
    damage: int                     # 0 if non-damaging
    modifier: str                   # "+", "×", "-", or ""
    effect: str


@dataclass(frozen=True)
class Ability:
    name: str
    effect: str


@dataclass
class Card:
    card_id: int
    name: str
    expansion: str
    coll_no: str
    category: str   # "Pokemon", "Trainer", "Energy"
    stage: str      # "Basic", "Stage 1", "Stage 2", "Item", "Supporter", etc.
    rule: str       # "Pokémon ex", "Mega Pokémon ex", "n/a", etc.
    hp: int
    poke_type: Optional[EnergyType]
    weakness: Optional[EnergyType]
    resistance: Optional[EnergyType]
    retreat: int
    previous_stage: Optional[str]
    abilities: list[Ability] = field(default_factory=list)
    attacks: list[Attack] = field(default_factory=list)
    effect_text: str = ""  # for trainers / energies

    @property
    def is_pokemon(self) -> bool:
        return "Pokémon" in self.stage or "pokemon" in self.category.lower()

    @property
    def is_trainer(self) -> bool:
        return self.category in ("Item", "Supporter", "Stadium", "Tool")

    @property
    def is_energy(self) -> bool:
        return "Energy" in self.stage

    @property
    def is_basic_energy(self) -> bool:
        return self.stage == "Basic Energy"

    @property
    def is_ex(self) -> bool:
        return "ex" in self.rule.lower()

    def __repr__(self) -> str:
        return f"Card({self.card_id}, {self.name!r})"

    def __hash__(self) -> int:
        return hash(self.card_id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Card):
            return NotImplemented
        return self.card_id == other.card_id


# ─── CSV loader ──────────────────────────────────────────────────────────────

_DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "docs", "official", "EN_Card_Data.csv"
)

import re as _re

def _parse_cost(cost_str: str) -> tuple[EnergyType, ...]:
    if not cost_str or cost_str in ("n/a", "No cost", ""):
        return ()
    energies: list[EnergyType] = []
    for token in _re.findall(r'\{[A-Z竜]\}|●', cost_str):
        if token == "●":
            energies.append(EnergyType.C)
        else:
            energies.append(EnergyType.from_symbol(token))
    return tuple(energies)


def _parse_damage(dmg_str: str) -> tuple[int, str]:
    if not dmg_str or dmg_str in ("n/a", ""):
        return 0, ""
    modifier = ""
    for mod in ("+", "×", "-"):
        if mod in dmg_str:
            modifier = mod
            dmg_str = dmg_str.replace(mod, "")
            break
    try:
        return int(dmg_str.strip()), modifier
    except ValueError:
        return 0, modifier


def _parse_type(type_str: str) -> Optional[EnergyType]:
    if not type_str or type_str in ("n/a", ""):
        return None
    # Extract first {X} symbol
    m = _re.search(r'\{([A-Z])\}|竜', type_str)
    if not m:
        return None
    s = m.group(1) if m.group(1) else "竜"
    return EnergyType.from_symbol(s)


def _classify_category(stage: str, rule: str, card_name: str) -> str:
    if "Energy" in stage:
        return "Energy"
    if any(t in stage for t in ("Item", "Supporter", "Stadium", "Tool")):
        return stage.split()[0]
    return "Pokemon"


@lru_cache(maxsize=1)
def load_all_cards() -> dict[int, Card]:
    """Load all cards from EN_Card_Data.csv. Result is cached."""
    raw: dict[int, dict] = {}

    with open(_DATA_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = int(row["Card ID"])
            stage = row["Stage (Pokémon)/Type (Energy and Trainer)"].strip()
            rule  = row["Rule"].strip()
            name  = row["Card Name"].strip()

            if cid not in raw:
                raw[cid] = {
                    "card_id":      cid,
                    "name":         name,
                    "expansion":    row["Expansion"].strip(),
                    "coll_no":      row["Collection No."].strip(),
                    "stage":        stage,
                    "rule":         rule,
                    "category":     _classify_category(stage, rule, name),
                    "hp":           int(row["HP"]) if row["HP"] and row["HP"] != "n/a" else 0,
                    "poke_type":    _parse_type(row["Type"]),
                    "weakness":     _parse_type(row["Weakness"]),
                    "resistance":   _parse_type(row["Resistance (Type)"]),
                    "retreat":      int(row["Retreat"]) if row["Retreat"] and row["Retreat"] not in ("n/a","") else 0,
                    "previous_stage": row["Previous stage"].strip() or None,
                    "abilities":    [],
                    "attacks":      [],
                    "effect_text":  "",
                }

            move = row["Move Name"].strip()
            eff  = row["Effect Explanation"].strip()
            cost_str = row["Cost"].strip()
            dmg_raw  = row["Damage"].strip()

            if move.startswith("["):
                # Ability or Tera rule
                ability_name = move.strip("[]")
                raw[cid]["abilities"].append({"name": ability_name, "effect": eff})
            elif move and move not in ("n/a", ""):
                dmg, mod = _parse_damage(dmg_raw)
                raw[cid]["attacks"].append({
                    "name":     move,
                    "cost":     _parse_cost(cost_str),
                    "damage":   dmg,
                    "modifier": mod,
                    "effect":   eff,
                })
            elif eff and not raw[cid]["effect_text"]:
                raw[cid]["effect_text"] = eff

    result: dict[int, Card] = {}
    for cid, d in raw.items():
        result[cid] = Card(
            card_id=d["card_id"],
            name=d["name"],
            expansion=d["expansion"],
            coll_no=d["coll_no"],
            category=d["category"],
            stage=d["stage"],
            rule=d["rule"],
            hp=d["hp"],
            poke_type=d["poke_type"],
            weakness=d["weakness"],
            resistance=d["resistance"],
            retreat=d["retreat"],
            previous_stage=d["previous_stage"] if d["previous_stage"] not in ("n/a","") else None,
            abilities=[Ability(**a) for a in d["abilities"]],
            attacks=[Attack(**a) for a in d["attacks"]],
            effect_text=d["effect_text"],
        )
    return result


# Convenience accessors
def get_card(card_id: int) -> Card:
    return load_all_cards()[card_id]


def find_card(name: str) -> Optional[Card]:
    """Find first card by exact name (case-insensitive)."""
    name_lower = name.lower()
    for card in load_all_cards().values():
        if card.name.lower() == name_lower:
            return card
    return None


def find_cards(name: str) -> list[Card]:
    """Find all cards matching name (case-insensitive)."""
    name_lower = name.lower()
    return [c for c in load_all_cards().values() if c.name.lower() == name_lower]
