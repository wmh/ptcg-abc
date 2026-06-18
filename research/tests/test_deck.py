"""Test deck construction using official card data."""
import pytest
from collections import Counter
from deck.decklists import build_lucario_deck
from deck.card_db import Card, load_all_cards


def test_deck_has_60_cards():
    deck = build_lucario_deck()
    assert len(deck) == 60


def test_deck_max_4_copies_non_basic_energy():
    """Basic energy cards are unlimited; all other cards max 4 copies."""
    deck = build_lucario_deck()
    counts = Counter(c.card_id for c in deck)
    for card_id, count in counts.items():
        card = next(c for c in deck if c.card_id == card_id)
        if card.is_basic_energy:
            continue
        assert count <= 4, f"{card.name} ({card_id}) has {count} copies (max 4)"


def test_deck_has_basic_pokemon():
    deck = build_lucario_deck()
    basics = [c for c in deck if c.stage == "Basic Pokémon"]
    assert len(basics) >= 4, "Need enough Basic Pokémon to start"


def test_deck_has_energy():
    deck = build_lucario_deck()
    energy = [c for c in deck if c.is_energy]
    assert 8 <= len(energy) <= 20


def test_deck_contains_mega_lucario():
    deck = build_lucario_deck()
    lucarios = [c for c in deck if c.name == "Mega Lucario ex"]
    assert len(lucarios) == 4


def test_deck_contains_riolu():
    deck = build_lucario_deck()
    riolus = [c for c in deck if c.name == "Riolu"]
    assert len(riolus) == 3, "Sample deck runs 3 Riolu"


def test_deck_contains_hariyama():
    """Hariyama's Heave-Ho Catcher ability acts as Boss's Orders on evolve."""
    deck = build_lucario_deck()
    assert any(c.name == "Hariyama" for c in deck)
    assert any(c.name == "Makuhita" for c in deck)


def test_all_card_ids_valid():
    """Every card in the deck must exist in the official card pool."""
    all_cards = load_all_cards()
    deck = build_lucario_deck()
    for card in deck:
        assert card.card_id in all_cards, f"Card ID {card.card_id} not in official pool"


def test_card_db_loads_attacks():
    all_cards = load_all_cards()
    lucario = all_cards[678]
    assert lucario.name == "Mega Lucario ex"
    assert any(a.name == "Aura Jab" for a in lucario.attacks)
    aura_jab = next(a for a in lucario.attacks if a.name == "Aura Jab")
    assert aura_jab.damage == 130


def test_card_db_loads_abilities():
    all_cards = load_all_cards()
    dusknoir = all_cards[133]
    assert any("Cursed Blast" in a.name for a in dusknoir.abilities)
