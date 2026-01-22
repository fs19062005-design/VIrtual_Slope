import glob, yaml, logging, os
from typing import Optional, Dict, Any
from src.config import config

logger = logging.getLogger(__name__)


def find_mission_yaml_file(mission_name: str) -> Optional[str]:

    pattern = os.path.join(config.params_directory, f"WBMS-VS_params_*_{mission_name}.yaml")
    matches = glob.glob(pattern)
    
    if len(matches) == 0:
        logger.warning("No VS params file found for mission '%s' (pattern: %s)", mission_name, pattern)
        return None
    elif len(matches) > 1:
        logger.error("Multiple VS params files found for mission '%s': %s", mission_name, matches)
        return None
    
    return matches[0]


# Cache for loaded phases to avoid reloading YAML multiple times
_phases_cache: Dict[str, Dict[int, Dict[str, Any]]] = {}


def load_all_phases(mission_name: str, use_cache: bool = True) -> Dict[int, Dict[str, Any]]:

    # Check cache first
    if use_cache and mission_name in _phases_cache:
        logger.debug("Using cached phases for mission '%s'", mission_name)
        return _phases_cache[mission_name]
    
    try:
        yaml_file = find_mission_yaml_file(mission_name)
        if yaml_file is None:
            return {}
        
        logger.info("Loading VS parameters for mission '%s' from %s", mission_name, yaml_file)
        
        with open(yaml_file, 'r') as f:
            data = yaml.safe_load(f)
            
        vs_params = data.get('VS_params')
        if vs_params is None:
            logger.error("Missing 'VS_params' section in %s", yaml_file)
            return {}
        
        logger.info("Loaded %d phases for mission '%s'", len(vs_params), mission_name)
        
        # Cache the result
        _phases_cache[mission_name] = vs_params
        return vs_params
        
    except Exception as e:
        logger.error("Error loading VS params for mission '%s': %s", mission_name, e)
        return {}
