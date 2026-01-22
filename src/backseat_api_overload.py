import requests, logging
from .config import config

logger = logging.getLogger(__name__)

# Track last valid depth command
_last_valid_depth: float | None = None


def send_z_command(z_value: float) -> bool:

    global _last_valid_depth
    
    min_depth = config.min_depth
    max_depth = config.max_depth
    
    # Check if depth is within limits
    if z_value < min_depth or z_value > max_depth:
        if _last_valid_depth is not None:
            logger.warning("Depth %.1fm out of limits [%s-%s] - using last valid: %.1fm", z_value, min_depth, max_depth, _last_valid_depth)
            z_value = _last_valid_depth
        else:
            logger.warning("Depth %.1fm out of limits [%s-%s] - command rejected (no previous valid depth)", z_value, min_depth, max_depth)
            return False
    else:
        # Update last valid depth
        _last_valid_depth = z_value
    
    api_url = f"http://{config.backseat_ip}:{config.backseat_port}/missions/current/overload/parameters"
    
    params = {
        'timeout': config.overload_command_duration,
        'zCmd': "Depth",        
        'zSetpoint': z_value
    }
    
    try:
        response = requests.post(api_url, params=params, timeout=config.backseat_timeout_tuple)
        success = response.status_code == 200
        
        logger.debug("Z=%.1fm -> Status: %s %s", z_value, response.status_code, ('OK' if success else 'ERROR'))
        
        return success
        
    except Exception as e:
        logger.exception("Z=%.1fm -> Error: %s", z_value, e)
        return False