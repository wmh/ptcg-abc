"""Self-play training loop skeleton.

Once the Kaggle game engine is available, replace the stub GameSimulator
with the real environment and this loop will produce training data for RL.
"""
from __future__ import annotations
import argparse
import random
import time
from dataclasses import dataclass
from typing import Optional

from agent.heuristic_agent import HeuristicAgent
from agent.mcts_agent import ISMCTSAgent, GameSimulator
from env.game_state import GameState, PlayerState
from env.actions import end_turn


@dataclass
class GameResult:
    winner: str  # "player1" | "player2"
    turns: int
    duration_s: float


def play_game(agent1, agent2, max_turns: int = 200) -> GameResult:
    """Run one game between two agents. Returns the result."""
    state = GameState()
    # TODO: initialize state with shuffled decks once engine is wired
    state.player = PlayerState()
    state.opponent = PlayerState()
    sim = GameSimulator(state)

    start = time.monotonic()
    for turn in range(max_turns):
        current_agent = agent1 if state.is_my_turn else agent2
        legal = sim.get_legal_actions(state)
        if not legal:
            break
        obs = sim._state_to_obs(state, legal)
        action = current_agent.act(obs)
        state = sim.apply_action(action)
        winner = sim._check_winner(state)
        if winner is not None:
            return GameResult(
                winner="player1" if winner == "me" else "player2",
                turns=turn + 1,
                duration_s=time.monotonic() - start,
            )

    # Timeout: evaluate by prize count
    my_prizes = state.player.prize_count
    opp_prizes = state.opponent.prize_count
    winner = "player1" if my_prizes < opp_prizes else "player2"
    return GameResult(winner=winner, turns=max_turns, duration_s=time.monotonic() - start)


def evaluate(agent1, agent2, n_games: int = 100) -> float:
    """Return agent1's win rate over n_games."""
    wins = 0
    for i in range(n_games):
        if i % 2 == 0:
            r = play_game(agent1, agent2)
            if r.winner == "player1":
                wins += 1
        else:
            r = play_game(agent2, agent1)
            if r.winner == "player2":
                wins += 1
    return wins / n_games


def main():
    parser = argparse.ArgumentParser(description="Self-play evaluation")
    parser.add_argument("--games", type=int, default=20, help="Number of games")
    args = parser.parse_args()

    heuristic = HeuristicAgent()
    mcts = ISMCTSAgent(time_limit_s=1.0, n_determinizations=4)

    print(f"Running {args.games} games: MCTS vs Heuristic...")
    win_rate = evaluate(mcts, heuristic, n_games=args.games)
    print(f"MCTS win rate: {win_rate:.1%}")


if __name__ == "__main__":
    main()
