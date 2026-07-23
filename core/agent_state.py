import os
import json
import time
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(BASE_DIR, "data", "agent_state.json")

# Default Agent Configurations
DEFAULT_AGENTS = {
    "DataFeedServer": {
        "name": "NEXUS",
        "role": "Data Feed Server",
        "description": "Streams high-frequency market ticks natively from broker.",
        "status": "Initializing...",
        "is_active": False,
        "lastActive": ""
    },
    "SignalProcessor": {
        "name": "LUMINA",
        "role": "Signal Processor",
        "description": "Filters market noise and synthesizes setup conditions.",
        "status": "Resting...",
        "is_active": False,
        "lastActive": ""
    },
    "ExecutionEngine": {
        "name": "AETHER",
        "role": "Execution Engine",
        "description": "The central brain. Evaluates models and triggers live market orders.",
        "status": "Awaiting market open...",
        "is_active": False,
        "lastActive": ""
    },
    "RiskManager": {
        "name": "AEGIS",
        "role": "Risk Manager",
        "description": "Monitors portfolio drawdowns and manages dynamic capital exposure.",
        "status": "Monitoring portfolio bounds.",
        "is_active": False,
        "lastActive": ""
    },
    "BootupCoordinator": {
        "name": "ORACLE",
        "role": "Coordinator",
        "description": "Synchronizes pipeline health and handles auto catch-up sequences.",
        "status": "System synchronized.",
        "is_active": False,
        "lastActive": ""
    }
}

def _read_state():
    if not os.path.exists(STATE_FILE):
        return DEFAULT_AGENTS.copy()
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_AGENTS.copy()

def _write_state(state):
    tmp_file = STATE_FILE + ".tmp"
    try:
        with open(tmp_file, "w") as f:
            json.dump(state, f, indent=4)
        os.replace(tmp_file, STATE_FILE)
    except Exception as e:
        # Pass silently, will retry next time
        pass

def update_agent_status(agent_id, status, is_active=False):
    """
    Safely update a single agent's status.
    Since we don't have portalocker, we'll use a simple retry loop on read/write to minimize race conditions.
    """
    for _ in range(3):
        try:
            state = _read_state()
            if agent_id not in state:
                state[agent_id] = DEFAULT_AGENTS.get(agent_id, {}).copy()
            
            state[agent_id]["status"] = status
            state[agent_id]["is_active"] = is_active
            state[agent_id]["lastActive"] = datetime.datetime.now().strftime('%H:%M:%S')
            
            _write_state(state)
            break
        except Exception:
            time.sleep(0.05)

def get_all_agent_states():
    return _read_state()
