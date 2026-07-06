"""Generic agent: pilots this dir's deck.csv with the shared GenericPolicy. A first-class agent
(used as a cabt opponent now, but promotable to a primary deck — write a bespoke pilot if so)."""
import os, sys
_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
_d = _HERE
for _ in range(6):  # walk up to the repo root (depth-robust)
    if os.path.exists(os.path.join(_d, "agents", "_base", "generic_policy.py")):
        sys.path.insert(0, os.path.join(_d, "docs", "official", "models", "cg-lib"))
        sys.path.insert(0, os.path.join(_d, "agents", "_base"))
        break
    _d = os.path.dirname(_d)
sys.path.insert(0, _HERE)
from generic_policy import make_generic_agent  # noqa: E402
my_deck = [int(x) for x in open(os.path.join(_HERE, "deck.csv")) if x.strip()]
_impl = make_generic_agent(my_deck)
def agent(obs_dict):
    return _impl(obs_dict)
