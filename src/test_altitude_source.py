import os
import logging
from typing import Optional
from src.DesBridge_api import NavigationData

logger = logging.getLogger(__name__)

DEPTH_FILE = "test_bottom_depth.txt"


def set_bottom_depth(value: float):
    """Save bottom depth to file"""
    with open(DEPTH_FILE, 'w') as f:
        f.write(str(value))


def get_bottom_depth() -> float:
    """Read bottom depth from file"""
    try:
        if os.path.exists(DEPTH_FILE):
            with open(DEPTH_FILE, 'r') as f:
                return float(f.read().strip())
    except (ValueError, IOError) as e:
        logger.debug("TEST MODE: Could not read depth file: %s", e)
    return 20.0  # default
    
def get_test_altitude(nav_data: Optional[NavigationData]) -> Optional[float]:

    if nav_data is None:
        logger.warning("TEST MODE: Navigation data is None - cannot calculate simulated altitude")
        raise ValueError("TEST MODE ERROR: Navigation data unavailable")
    
    if nav_data.depth is None:
        logger.warning("TEST MODE: Depth is None - cannot calculate simulated altitude")
        raise ValueError("TEST MODE ERROR: Depth data unavailable from DesBridge")
    
    bottom_depth = get_bottom_depth()
    simulated_altitude = bottom_depth - nav_data.depth
    
    logger.info("TEST MODE: simulated altitude=%.2fm (bottom=%.2fm, depth=%.2fm)", 
                simulated_altitude, bottom_depth, nav_data.depth)
    
    return simulated_altitude

    
def start_input_thread(initial_bottom_depth: float = 20.0):
    """Initialize test mode with default bottom depth"""
    set_bottom_depth(initial_bottom_depth)
    logger.info("TEST MODE: Use 'python test_input.py' in separate terminal for input")
    logger.info("TEST MODE: Initial bottom depth set to %.2fm", initial_bottom_depth)


def stop_input_thread():
    """Cleanup function - removes depth file"""
    try:
        if os.path.exists(DEPTH_FILE):
            os.remove(DEPTH_FILE)
        logger.info("TEST MODE: Cleaned up depth file")
    except Exception as e:
        logger.warning("TEST MODE: Could not remove depth file: %s", e)
