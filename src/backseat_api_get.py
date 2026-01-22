import requests, time, threading, logging
from .config import config

logger = logging.getLogger(__name__)

BASE_URL = f"http://{config.backseat_ip}:{config.backseat_port}"

# Cache for phase info
_last_phase_info = None
_last_fetch_time = 0
_cache_lock = threading.Lock()
CACHE_TTL = 0.5  # Cache valid for 0.5 seconds

def get_current_phase_info(force_refresh: bool = False):

    global _last_phase_info, _last_fetch_time
    
    with _cache_lock:
        current_time = time.time()
        
        # Return cached data if fresh and not forcing refresh
        if not force_refresh and _last_phase_info is not None:
            if (current_time - _last_fetch_time) < CACHE_TTL:
                return _last_phase_info
        
        # Fetch new data
        url = f"{BASE_URL}/missions/current"
        try:
            resp = requests.get(url, timeout=config.backseat_timeout_tuple)
            resp.raise_for_status()
            mission = resp.json()
            _last_phase_info = mission
            _last_fetch_time = current_time
            return mission
        except Exception as e:
            logger.warning("Error fetching current phase info: %s", e)
            return _last_phase_info

def get_current_phase_id():

    phase_info = get_current_phase_info()
    if phase_info is None:
        return None
    return phase_info.get("currentPhaseId")

def get_current_mission_name():

    phase_info = get_current_phase_info()
    if phase_info is None:
        return None
    return phase_info.get("name")

def is_phase_enabled():

    phase_info = get_current_phase_info()
    if phase_info is None:
        logger.warning("Could not get phase info from Backseat API")
        return False
    
    state = phase_info.get("state")
    
    if state == "Enabled":
        return True
    else:
        return False
