"""RL + MCTS training loop for PTCG AI Battle Challenge.

Architecture: Transformer encoder-decoder
  - Encoder: board state → value (win probability)
  - Decoder: (board state, candidate actions) → policy logits

Training:
  1. Evaluate: MCTS agent vs random agent (50 games)
  2. Self-play: collect (state, value, policy) samples via MCTS (100 games)
  3. Train on collected samples (batch=128, AdamW lr=3e-4)
  4. Repeat

Usage (Kaggle notebook with GPU):
    python3 train/rl_trainer.py

Requirements:
    pip install torch
    # cg library must be on sys.path (see sys.path.append below)
"""
import glob
import math
import os
import random
import sys

import torch
import torch.nn
import torch.nn.functional
import torch.optim

# ─── cg library path ─────────────────────────────────────────────────────────

_cg_paths = glob.glob('/kaggle/input/**/cg-lib', recursive=True)
if _cg_paths:
    sys.path.append(_cg_paths[0])
else:
    # Local dev: set CG_LIB_PATH env var
    _local = os.environ.get("CG_LIB_PATH", "")
    if _local:
        sys.path.append(_local)

from cg.api import (
    AreaType, Card, Observation, OptionType, PlayerState, Pokemon,
    SearchState, SelectContext,
    all_attack, all_card_data,
    search_begin, search_end, search_step,
    to_observation_class,
)
from cg.game import battle_start, battle_finish, battle_select

# ─── Card metadata ────────────────────────────────────────────────────────────

all_card   = all_card_data()
card_table = {c.cardId: c for c in all_card}
card_count = max(all_card, key=lambda c: c.cardId).cardId + 1

attack_count = max(all_attack(), key=lambda a: a.attackId).attackId + 1

# ─── Deck (load from deck.csv) ────────────────────────────────────────────────

_deck_path = os.path.join(os.path.dirname(__file__), "../submit/deck.csv")
with open(_deck_path) as f:
    DECK = [int(l) for l in f if l.strip()]
assert len(DECK) == 60

# ─── Model ────────────────────────────────────────────────────────────────────

num_words_encoder = 24
encoder_size = 22000

decoder_main_feature = 8
decoder_attack_offset = 14
decoder_card_offset = decoder_attack_offset + attack_count
decoder_size = decoder_card_offset + (1 + decoder_main_feature + SelectContext.RECOVER_SPECIAL_CONDITION) * card_count


class DecoderLayer(torch.nn.Module):
    def __init__(self, d_model: int, num_heads: int, d_feedforward: int):
        super().__init__()
        self.attention = torch.nn.MultiheadAttention(d_model, num_heads)
        self.fc1 = torch.nn.Linear(d_model, d_feedforward)
        self.fc2 = torch.nn.Linear(d_feedforward, d_model)
        self.norm1 = torch.nn.LayerNorm(d_model)
        self.norm2 = torch.nn.LayerNorm(d_model)

    def forward(self, x: torch.Tensor, encoder_out: torch.Tensor) -> torch.Tensor:
        y, _ = self.attention(x, encoder_out, encoder_out, need_weights=False)
        res = self.norm1(x + y)
        y = torch.nn.functional.relu(self.fc1(res))
        y = self.fc2(y)
        return self.norm2(res + y)


class MyModel(torch.nn.Module):
    def __init__(self, d_model=128, num_heads=2, d_feedforward=256,
                 num_layers_encoder=1, num_layers_decoder=1):
        super().__init__()
        self.d_model = d_model
        self.encoder_bag = torch.nn.EmbeddingBag(encoder_size, d_model, mode="sum")
        enc_layer = torch.nn.TransformerEncoderLayer(d_model, num_heads, d_feedforward, 0)
        self.encoder = torch.nn.TransformerEncoder(enc_layer, num_layers_encoder, enable_nested_tensor=False)
        self.encoder_fc = torch.nn.Linear(d_model, 1)
        self.decoder_bag = torch.nn.EmbeddingBag(decoder_size, d_model, mode="sum")
        self.decoder = torch.nn.ModuleList(
            [DecoderLayer(d_model, num_heads, d_feedforward) for _ in range(num_layers_decoder)]
        )
        self.decoder_fc = torch.nn.Linear(d_model, 1)

    def forward(self, idx_enc, val_enc, off_enc, idx_dec, val_dec, off_dec):
        v = self.encoder_bag(idx_enc, off_enc, val_enc)
        v = v.reshape(-1, num_words_encoder, self.d_model).transpose(0, 1)
        batch_size = v.size(1)
        encoder_out = self.encoder(v)
        v = torch.tanh(self.encoder_fc(encoder_out).mean(0))

        p = self.decoder_bag(idx_dec, off_dec, val_dec)
        p = p.reshape(batch_size, -1, self.d_model).transpose(0, 1)
        for layer in self.decoder:
            p = layer(p, encoder_out)
        p = torch.tanh(self.decoder_fc(p).transpose(0, 1).view(batch_size, -1))
        return v, p


# ─── Feature encoding ─────────────────────────────────────────────────────────

class SparseVector:
    def __init__(self):
        self.index: list[int] = []
        self.value: list[float] = []
        self.offset: list[int] = []
        self.pos = 0

    def add(self, index: int, value):
        value = float(value)
        if value != 0.0:
            self.index.append(self.pos + index)
            self.value.append(value)

    def add_pos(self, pos: int):
        self.pos += pos

    def add_single(self, value):
        value = float(value)
        if value != 0.0:
            self.index.append(self.pos)
            self.value.append(value)
        self.pos += 1

    def word_start(self):
        self.offset.append(len(self.index))


def _add_card(sv: SparseVector, card):
    if card is not None:
        sv.add(card.id, 1)
    sv.add_pos(card_count)


def _add_cards(sv: SparseVector, cards, value: float):
    if cards:
        for card in cards:
            sv.add(card.id, value)
    sv.add_pos(card_count)


def _add_pokemon(sv: SparseVector, poke):
    if poke is None:
        sv.add_single(1)
        sv.add_pos(1 + 3 * card_count)
    else:
        sv.add_single(0)
        sv.add_single(poke.hp / 400)
        _add_card(sv, poke)
        _add_cards(sv, poke.tools, 1.0)
        _add_cards(sv, poke.energyCards, 0.5)


def _add_player(sv: SparseVector, ps: PlayerState):
    sv.add_single(ps.deckCount / 60)
    sv.add_single(len(ps.discard) / 60)
    sv.add_single(ps.handCount / 8)
    sv.add_single(len(ps.bench) / 5)
    sv.add(len(ps.prize), 1)
    sv.add_pos(7)
    sv.add_single(ps.poisoned)
    sv.add_single(ps.burned)
    sv.add_single(ps.asleep)
    sv.add_single(ps.paralyzed)
    sv.add_single(ps.confused)
    _add_cards(sv, ps.discard, 0.25)


def get_encoder_input(obs: Observation, your_deck: list[int]) -> SparseVector:
    your_index = obs.current.yourIndex
    state = obs.current
    sv = SparseVector()

    for i in range(2):
        ps = state.players[i ^ your_index]
        for j in range(8):
            sv.word_start()
            pos = sv.pos
            poke = ps.bench[j] if j < len(ps.bench) else None
            _add_pokemon(sv, poke)
            if j != 7:
                sv.pos = pos

    for i in range(2):
        ps = state.players[i ^ your_index]
        sv.word_start()
        _add_pokemon(sv, ps.active[0] if ps.active else None)

    for i in range(2):
        ps = state.players[i ^ your_index]
        sv.word_start()
        _add_player(sv, ps)

    sv.word_start()
    _add_cards(sv, state.players[your_index].hand, 0.25)

    sv.word_start()
    for cid in your_deck:
        sv.add(cid, 0.25)
    sv.add_pos(card_count)

    sv.word_start()
    _add_cards(sv, state.stadium, 1.0)

    sv.word_start()
    sv.add_single(1)
    sv.add_single(state.turn / 10)
    sv.add_single(state.firstPlayer == your_index)
    return sv


def _get_obs_card(obs: Observation, area, index, player_index):
    ps = obs.current.players[player_index]
    match area:
        case AreaType.DECK:    return obs.select.deck[index]
        case AreaType.HAND:    return ps.hand[index]
        case AreaType.DISCARD: return ps.discard[index]
        case AreaType.ACTIVE:  return ps.active[index]
        case AreaType.BENCH:   return ps.bench[index]
        case AreaType.PRIZE:   return ps.prize[index]
        case AreaType.STADIUM: return obs.current.stadium[index]
        case AreaType.LOOKING: return obs.current.looking[index]
        case _:                return None


def _dm(sv: SparseVector, fi: int, card):
    if card is not None:
        sv.add(decoder_card_offset + fi * card_count + card.id, 1)


def _dc(sv: SparseVector, ctx, card_id: int):
    sv.add(decoder_card_offset + (decoder_main_feature + ctx) * card_count + card_id, 1)


def get_decoder_input(obs: Observation, actions: list[list[int]]) -> SparseVector:
    sv = SparseVector()
    yi = obs.current.yourIndex
    ps = obs.current.players[yi]
    ctx = obs.select.context

    for action in actions:
        sv.word_start()
        if not action:
            sv.add(0, 1)
            continue
        for i in action:
            o = obs.select.option[i]
            match o.type:
                case OptionType.END:              sv.add(1, 1)
                case OptionType.YES:              sv.add(2, 1)
                case OptionType.NO:               sv.add(3, 1)
                case OptionType.SPECIAL_CONDITION: sv.add(4 + o.specialConditionType, 1)
                case OptionType.NUMBER:           sv.add(9 + min(o.number, 4), 1)
                case OptionType.ATTACK:           sv.add(decoder_attack_offset + o.attackId, 1)
                case OptionType.PLAY:             _dm(sv, 0, ps.hand[o.index])
                case OptionType.ATTACH:
                    _dm(sv, 1, _get_obs_card(obs, o.area, o.index, yi))
                    _dm(sv, 2, _get_obs_card(obs, o.inPlayArea, o.inPlayIndex, yi))
                case OptionType.EVOLVE:
                    _dm(sv, 3, _get_obs_card(obs, o.area, o.index, yi))
                    _dm(sv, 4, _get_obs_card(obs, o.inPlayArea, o.inPlayIndex, yi))
                case OptionType.ABILITY:          _dm(sv, 5, _get_obs_card(obs, o.area, o.index, yi))
                case OptionType.DISCARD:          _dm(sv, 6, _get_obs_card(obs, o.area, o.index, yi))
                case OptionType.RETREAT:          _dm(sv, 7, ps.active[0] if ps.active else None)
                case OptionType.CARD:
                    c = _get_obs_card(obs, o.area, o.index, o.playerIndex)
                    if c: _dc(sv, ctx, c.id)
                case OptionType.TOOL_CARD:
                    c = _get_obs_card(obs, o.area, o.index, o.playerIndex)
                    if c: _dc(sv, ctx, c.tools[o.toolIndex].id)
                case OptionType.ENERGY_CARD | OptionType.ENERGY:
                    c = _get_obs_card(obs, o.area, o.index, o.playerIndex)
                    if c: _dc(sv, ctx, c.energyCards[o.energyIndex].id)
                case OptionType.SKILL:            _dc(sv, ctx, o.cardId)
    return sv


# ─── MCTS ─────────────────────────────────────────────────────────────────────

SEARCH_COUNT = 10  # MCTS rollouts per move


class LearnSample:
    def __init__(self, value: float, policy: list[float], sv_enc: SparseVector, sv_dec: SparseVector):
        self.value = value
        self.policy = policy
        self.sv_enc = sv_enc
        self.sv_dec = sv_dec


class Child:
    def __init__(self, select: list[int], prob: float):
        self.node: 'Node | None' = None
        self.select = select
        self.prob = prob


class Node:
    def __init__(self, parent: 'Node | None', state: SearchState):
        self.value = -2.0
        self.total = 0.0
        self.visit = 0
        self.parent = parent
        self.children: list[Child] = []
        self.state = state

    def backprop(self, value: float):
        self.total += value
        self.visit += 1
        if self.parent:
            self.parent.backprop(value)


def _eval_nn(sv_enc: SparseVector, sv_dec: SparseVector, model: MyModel, device):
    v, p = model(
        torch.tensor(sv_enc.index, dtype=torch.int32, device=device),
        torch.tensor(sv_enc.value, dtype=torch.float32, device=device),
        torch.tensor(sv_enc.offset, dtype=torch.int32, device=device),
        torch.tensor(sv_dec.index, dtype=torch.int32, device=device),
        torch.tensor(sv_dec.value, dtype=torch.float32, device=device),
        torch.tensor(sv_dec.offset, dtype=torch.int32, device=device),
    )
    return v.tolist()[0][0], p.tolist()[0]


def _enumerate_actions(n_options: int, max_count: int, limit: int = 64) -> list[list[int]]:
    """Enumerate up to `limit` combinations of max_count items from n_options."""
    actions = []
    indices = list(range(max_count))
    for _ in range(limit):
        actions.append(indices.copy())
        for i in range(len(indices) - 1, -1, -1):
            if indices[i] < n_options - (len(indices) - i):
                indices[i] += 1
                for j in range(i + 1, len(indices)):
                    indices[j] = indices[j - 1] + 1
                break
        else:
            break
    return actions


def _create_node(parent, search_state: SearchState, your_index: int,
                 your_deck: list[int], model: MyModel, device) -> tuple[Node, LearnSample | None]:
    node = Node(parent, search_state)
    obs = search_state.observation
    state = obs.current

    if state.result >= 0:
        node.value = 0.0 if state.result == 2 else (1.0 if state.result == your_index else -1.0)
        node.backprop(node.value)
        return node, None

    actions = _enumerate_actions(len(obs.select.option), obs.select.maxCount)
    sv_enc = get_encoder_input(obs, your_deck)
    sv_dec = get_decoder_input(obs, actions)
    value, policy = _eval_nn(sv_enc, sv_dec, model, device)

    v = value if state.yourIndex == your_index else -value
    node.value = v
    node.backprop(v)

    total_p = 0.0
    for i, act in enumerate(actions):
        p = math.exp(policy[i] * 10.0) if i < len(policy) else 1e-6
        node.children.append(Child(act, p))
        total_p += p
    for c in node.children:
        c.prob /= total_p

    return node, LearnSample(value, policy[:len(actions)], sv_enc, sv_dec)


def mcts_agent(obs_dict: dict, your_deck: list[int], model: MyModel, device) -> tuple[list[int], LearnSample]:
    obs = to_observation_class(obs_dict)
    your_index = obs.current.yourIndex
    state = obs.current

    active_opp = state.players[1 - your_index].active
    search_state = search_begin(
        obs,
        your_deck=random.sample(your_deck, state.players[your_index].deckCount),
        your_prize=random.sample(your_deck, len(state.players[your_index].prize)),
        opponent_deck=[1072] * state.players[1 - your_index].deckCount,
        opponent_prize=[1] * len(state.players[1 - your_index].prize),
        opponent_hand=[1] * state.players[1 - your_index].handCount,
        opponent_active=[1072] if (active_opp and active_opp[0] is None) else [],
    )
    root, sample = _create_node(None, search_state, your_index, your_deck, model, device)

    for _ in range(SEARCH_COUNT):
        current = root
        while True:
            best_val, next_child = -1e9, None
            c_exp = 0.4 * math.sqrt(current.visit)
            for child in current.children:
                if child.node is None:
                    v = current.total / current.visit if current.visit > 0 else 0.0
                    visit = 0
                else:
                    v = child.node.total / child.node.visit if child.node.visit > 0 else 0.0
                    visit = child.node.visit
                if current.state.observation.current.yourIndex != your_index:
                    v = -v
                v += c_exp * child.prob / (1 + visit)
                if v > best_val:
                    best_val, next_child = v, child

            if next_child is None:
                break
            if next_child.node is None:
                ss = search_step(current.state.searchId, next_child.select)
                next_child.node, _ = _create_node(current, ss, your_index, your_deck, model, device)
                break
            else:
                current = next_child.node
                if current.state.observation.current.result >= 0:
                    current.backprop(current.value)
                    break

    # Choose most-visited child
    best_child = max(root.children, key=lambda c: c.node.visit if c.node else 0, default=root.children[0])

    # Update training sample
    if sample:
        min_v = min((c.node.total / c.node.visit for c in root.children if c.node and c.node.visit > 0), default=0.0)
        root_v = root.total / root.visit if root.visit > 0 else 0.0
        sample.value = root_v
        for i, child in enumerate(root.children):
            if i >= len(sample.policy):
                break
            if child.node and child.node.visit > 0:
                sample.policy[i] = max(-1.0, min(1.0, child.node.total / child.node.visit - root_v))
            else:
                sample.policy[i] = max(-1.0, min(1.0, min_v - root_v - 0.03))

    search_end()
    return best_child.select, sample


def random_agent(obs_dict: dict) -> list[int]:
    obs = to_observation_class(obs_dict)
    return random.sample(list(range(len(obs.select.option))), obs.select.maxCount)


# ─── Batch helper ─────────────────────────────────────────────────────────────

class LearnInput:
    def __init__(self):
        self.index: list[int] = []
        self.value: list[float] = []
        self.offset: list[int] = []

    def add(self, sv: SparseVector):
        count = len(self.index)
        self.index.extend(sv.index)
        self.value.extend(sv.value)
        for o in sv.offset:
            self.offset.append(o + count)


# ─── Validation ───────────────────────────────────────────────────────────────

def validate_deck(deck: list[int]):
    _, start_data = battle_start(deck, deck)
    if start_data.errorPlayer >= 0:
        msgs = {1: "Invalid card ID", 2: ">4 copies of same card name",
                3: "No Basic Pokémon", 4: "Multiple ACE SPEC cards"}
        raise ValueError(f"Deck error: {msgs.get(start_data.errorType, 'unknown')}")
    battle_finish()
    print("Deck validation passed.")


# ─── Training loop ────────────────────────────────────────────────────────────

def progress(count: int, text: str):
    for current in range(count + 1):
        pct = 100 * current // count
        sys.stderr.write(f"\r{text} {pct}%   ")
        sys.stderr.flush()
        if current == count:
            sys.stderr.write("\n")
            sys.stderr.flush()
            return
        yield current


def run_game_mcts(deck, model, device, your_index: int) -> tuple[list[list[LearnSample]], int]:
    obs, _ = battle_start(deck, deck)
    samples: list[list[LearnSample]] = [[], []]
    while True:
        if obs["current"]["result"] >= 0:
            break
        if obs["current"]["yourIndex"] == your_index:
            selected, sample = mcts_agent(obs, deck, model, device)
            if sample:
                samples[obs["current"]["yourIndex"]].append(sample)
        else:
            selected = random_agent(obs)
        obs = battle_select(selected)
    battle_finish()
    return samples, obs["current"]["result"]


def train(n_iterations: int = 20, n_eval: int = 50, n_selfplay: int = 100,
          batch_size: int = 128, lr: float = 3e-4, out_dir: str = "out"):

    validate_deck(DECK)
    os.makedirs(out_dir, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    model = MyModel().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
    loss_fn_enc = torch.nn.HuberLoss(delta=0.2)
    loss_fn_dec = torch.nn.HuberLoss(reduction="none", delta=0.1)

    for iteration in range(n_iterations):
        print(f"\n=== Iteration {iteration} ===")
        torch.save(model.state_dict(), f"{out_dir}/model_{iteration}.pth")

        model.eval()
        with torch.inference_mode():
            # Evaluation
            results = [0, 0, 0]
            for i in progress(n_eval, "Evaluating..."):
                obs, _ = battle_start(DECK, DECK)
                your_index = i % 2
                while True:
                    if obs["current"]["result"] >= 0:
                        break
                    if obs["current"]["yourIndex"] == your_index:
                        selected, _ = mcts_agent(obs, DECK, model, device)
                    else:
                        selected = random_agent(obs)
                    obs = battle_select(selected)
                battle_finish()
                r = obs["current"]["result"]
                results[2 if r == 2 else (0 if r == your_index else 1)] += 1
            total = results[0] + results[1]
            print(f"Win rate: {100 * results[0] // max(total, 1)}%  (W{results[0]} L{results[1]} D{results[2]})")

            # Self-play data collection
            sample_list: list[LearnSample] = []
            LAMBDA = 0.9
            for _ in progress(n_selfplay, "Self-play..."):
                obs, _ = battle_start(DECK, DECK)
                samples: list[list[LearnSample]] = [[], []]
                while True:
                    if obs["current"]["result"] >= 0:
                        break
                    selected, sample = mcts_agent(obs, DECK, model, device)
                    if sample:
                        samples[obs["current"]["yourIndex"]].append(sample)
                    obs = battle_select(selected)
                battle_finish()
                result = obs["current"]["result"]
                for p in range(2):
                    value = 1.0 if p == result else (-1.0 if result != 2 else 0.0)
                    for s in reversed(samples[p]):
                        label = (value + s.value) * 0.5
                        value = value * LAMBDA + s.value * (1.0 - LAMBDA)
                        s.value = label
                        sample_list.append(s)

        # Train
        print(f"Training on {len(sample_list)} samples...")
        model.train()
        random.shuffle(sample_list)
        batch_count = len(sample_list) // batch_size
        total_loss = 0.0
        for i in range(batch_count):
            batch = sample_list[i * batch_size:(i + 1) * batch_size]
            input_enc, input_dec = LearnInput(), LearnInput()
            mask, label_enc, label_dec = [], [], []
            for s in batch:
                input_enc.add(s.sv_enc)
                input_dec.add(s.sv_dec)
                label_enc.append(s.value)
                label_dec.extend(s.policy)
                n_act = len(s.policy)
                mask.extend([1.0] * n_act + [0.0] * (64 - n_act))
                label_dec.extend([0.0] * (64 - n_act))
                for _ in range(64 - n_act):
                    input_dec.offset.append(len(input_dec.index))

            mask_t = torch.tensor(mask, dtype=torch.float32, device=device).view(batch_size, -1)
            label_t_enc = torch.tensor(label_enc, dtype=torch.float32, device=device).view(batch_size, -1)
            label_t_dec = torch.tensor(label_dec, dtype=torch.float32, device=device).view(batch_size, -1)

            optimizer.zero_grad()
            out_enc, out_dec = model(
                torch.tensor(input_enc.index, dtype=torch.int32, device=device),
                torch.tensor(input_enc.value, dtype=torch.float32, device=device),
                torch.tensor(input_enc.offset, dtype=torch.int32, device=device),
                torch.tensor(input_dec.index, dtype=torch.int32, device=device),
                torch.tensor(input_dec.value, dtype=torch.float32, device=device),
                torch.tensor(input_dec.offset, dtype=torch.int32, device=device),
            )
            loss = loss_fn_enc(out_enc, label_t_enc) + (loss_fn_dec(out_dec, label_t_dec) * mask_t).sum() / batch_size
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        print(f"Avg loss: {total_loss / max(batch_count, 1):.4f}")

    torch.save(model.state_dict(), f"{out_dir}/model_final.pth")
    print(f"\nTraining complete. Model saved to {out_dir}/model_final.pth")


if __name__ == "__main__":
    train()
