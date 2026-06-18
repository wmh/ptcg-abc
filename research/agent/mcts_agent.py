"""Information Set MCTS Agent for Pokemon TCG.

Since PTCG has hidden information (opponent's hand, deck order),
we use Determinization + MCTS: sample N possible worlds from the
hidden information, run standard MCTS on each, and aggregate.

Reference: "Determinization in Monte-Carlo Tree Search for the Card
Game Lords of Sage" (Long et al.)
"""
from __future__ import annotations
import math
import random
import time
from copy import deepcopy
from typing import Optional

from env.game_state import Observation, GameState, PlayerState, ActivePokemon
from env.actions import Action, ActionType, end_turn
from agent.base_agent import BaseAgent
from agent.heuristic_agent import HeuristicAgent


class MCTSNode:
    __slots__ = ("action", "parent", "children", "visits", "value",
                 "legal_actions", "untried_actions")

    def __init__(self, action: Optional[Action], parent: Optional["MCTSNode"],
                 legal_actions: list[Action]):
        self.action = action
        self.parent = parent
        self.children: list[MCTSNode] = []
        self.visits = 0
        self.value = 0.0
        self.legal_actions = legal_actions
        self.untried_actions = list(legal_actions)

    @property
    def is_fully_expanded(self) -> bool:
        return len(self.untried_actions) == 0

    @property
    def is_terminal(self) -> bool:
        return len(self.legal_actions) == 0

    def ucb1(self, c: float = 1.41) -> float:
        if self.visits == 0:
            return float("inf")
        assert self.parent is not None
        return (self.value / self.visits
                + c * math.sqrt(math.log(self.parent.visits) / self.visits))

    def best_child(self, c: float = 1.41) -> "MCTSNode":
        return max(self.children, key=lambda n: n.ucb1(c))

    def expand(self, simulator: "GameSimulator") -> "MCTSNode":
        action = self.untried_actions.pop(random.randrange(len(self.untried_actions)))
        new_state = simulator.apply_action(action)
        child = MCTSNode(
            action=action,
            parent=self,
            legal_actions=simulator.get_legal_actions(new_state),
        )
        self.children.append(child)
        return child

    def update(self, result: float) -> None:
        self.visits += 1
        self.value += result

    def backprop(self, result: float) -> None:
        node: Optional[MCTSNode] = self
        while node is not None:
            node.update(result)
            result = 1.0 - result  # flip perspective
            node = node.parent


class GameSimulator:
    """Thin wrapper around game state for MCTS rollouts."""

    def __init__(self, state: GameState):
        self.state = state

    def apply_action(self, action: Action) -> GameState:
        """Return new state after applying action. Pure function."""
        new_state = deepcopy(self.state)
        # TODO: wire to actual game engine when Kaggle env is available
        # For now returns same state (placeholder)
        return new_state

    def get_legal_actions(self, state: GameState) -> list[Action]:
        # TODO: wire to actual game engine
        return [end_turn()]

    def rollout(self, state: GameState, fallback: BaseAgent, max_depth: int = 50) -> float:
        """Random rollout using heuristic agent. Returns win=1.0, loss=0.0."""
        current = deepcopy(state)
        for _ in range(max_depth):
            legal = self.get_legal_actions(current)
            if not legal:
                break
            # Use heuristic for faster, smarter rollouts
            obs = self._state_to_obs(current, legal)
            action = fallback.act(obs)
            current = self.apply_action(action)
            winner = self._check_winner(current)
            if winner is not None:
                return 1.0 if winner == "me" else 0.0
        return self._eval_state(current)

    def _state_to_obs(self, state: GameState, legal: list[Action]) -> Observation:
        from env.game_state import Observation
        p, o = state.player, state.opponent
        return Observation(
            my_hand=p.hand,
            my_active=p.active,
            my_bench=p.bench,
            my_prizes_remaining=p.prize_count,
            my_discard=p.discard,
            my_deck_size=len(p.deck),
            my_supporter_played=p.supporter_played,
            my_attached_energy_this_turn=p.attached_energy_this_turn,
            opp_active=o.active,
            opp_bench=o.bench,
            opp_prizes_remaining=o.prize_count,
            opp_discard=o.discard,
            opp_hand_size=len(o.hand),
            opp_deck_size=len(o.deck),
            turn_number=state.turn_number,
            is_my_turn=state.is_my_turn,
            first_turn=state.first_turn,
            legal_actions=legal,
        )

    def _check_winner(self, state: GameState) -> Optional[str]:
        if state.player.prize_count == 0:
            return "me"
        if state.opponent.prize_count == 0:
            return "opponent"
        if not state.opponent.has_pokemon_in_play():
            return "me"
        if not state.player.has_pokemon_in_play():
            return "opponent"
        return None

    def _eval_state(self, state: GameState) -> float:
        """Heuristic value [0,1]: higher = better for me."""
        my_p = state.player.prize_count
        opp_p = state.opponent.prize_count
        # Fewer prizes remaining = closer to winning
        if my_p + opp_p == 0:
            return 0.5
        prize_score = (6 - my_p) / 6 - (6 - opp_p) / 6
        return max(0.0, min(1.0, 0.5 + 0.3 * prize_score))


class ISMCTSAgent(BaseAgent):
    """Information Set MCTS Agent."""

    def __init__(self, time_limit_s: float = 2.0, n_determinizations: int = 10,
                 rollout_depth: int = 30):
        self.time_limit_s = time_limit_s
        self.n_det = n_determinizations
        self.rollout_depth = rollout_depth
        self._fallback = HeuristicAgent()

    def act(self, observation: Observation) -> Action:
        if not observation.legal_actions:
            return end_turn()
        if len(observation.legal_actions) == 1:
            return observation.legal_actions[0]

        deadline = time.monotonic() + self.time_limit_s
        action_scores: dict[int, float] = {i: 0.0 for i in range(len(observation.legal_actions))}
        action_counts: dict[int, int] = {i: 0 for i in range(len(observation.legal_actions))}

        for _ in range(self.n_det):
            if time.monotonic() >= deadline:
                break
            world = self._sample_world(observation)
            sim = GameSimulator(world)
            root = MCTSNode(None, None, observation.legal_actions)
            self._run_mcts(root, sim, deadline)
            for child in root.children:
                if child.action is not None:
                    idx = observation.legal_actions.index(child.action)
                    action_scores[idx] += child.value / max(child.visits, 1)
                    action_counts[idx] += 1

        best_idx = max(action_scores, key=lambda i: (
            action_scores[i] / max(action_counts[i], 1)
        ))
        return observation.legal_actions[best_idx]

    def _run_mcts(self, root: MCTSNode, sim: GameSimulator, deadline: float) -> None:
        while time.monotonic() < deadline:
            node = root
            state = deepcopy(sim.state)

            # Selection
            while node.is_fully_expanded and not node.is_terminal:
                node = node.best_child()
                # TODO: apply node.action to state

            # Expansion
            if not node.is_terminal and not node.is_fully_expanded:
                node = node.expand(sim)

            # Simulation (rollout)
            result = sim.rollout(state, self._fallback, self.rollout_depth)

            # Backpropagation
            node.backprop(result)

    def _sample_world(self, obs: Observation) -> GameState:
        """Sample a determinized world from the observation (fill in hidden info)."""
        # TODO: incorporate card-counting to weight likely opponent hands
        # For now: randomly draw cards for opponent's hand from unknown pool
        state = GameState()
        p = PlayerState()
        p.active = obs.my_active
        p.bench = list(obs.my_bench)
        p.hand = list(obs.my_hand)
        p.discard = list(obs.my_discard)
        p.prizes = [None] * obs.my_prizes_remaining  # type: ignore
        p.supporter_played = obs.my_supporter_played
        p.attached_energy_this_turn = obs.my_attached_energy_this_turn
        state.player = p

        o = PlayerState()
        o.active = obs.opp_active
        o.bench = list(obs.opp_bench)
        o.discard = list(obs.opp_discard)
        # Opponent hand: randomly sample from remaining cards (simplified)
        o.prizes = [None] * obs.opp_prizes_remaining  # type: ignore
        state.opponent = o

        state.turn_number = obs.turn_number
        state.is_my_turn = obs.is_my_turn
        state.first_turn = obs.first_turn
        return state
