import math, logging
from typing import Dict
from src.DesBridge_api import NavigationData
from src.config import config

logger = logging.getLogger(__name__)


def calculate_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:

    R = 6371000  # Earth radius in meters
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_lat/2)**2 + 
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c


def calculate_heading_degrees(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> float:

    start_lat_rad = math.radians(start_lat)
    start_lon_rad = math.radians(start_lon)
    end_lat_rad = math.radians(end_lat)
    end_lon_rad = math.radians(end_lon)
    
    delta_lon = end_lon_rad - start_lon_rad
    
    y = math.sin(delta_lon) * math.cos(end_lat_rad)
    x = (math.cos(start_lat_rad) * math.sin(end_lat_rad) - 
         math.sin(start_lat_rad) * math.cos(end_lat_rad) * math.cos(delta_lon))
    
    heading_rad = math.atan2(y, x)
    heading_deg = math.degrees(heading_rad)
    
    # Convert to 0-360 range
    return (heading_deg + 360) % 360


def calculate_heading_difference(current_heading: float, target_heading: float) -> float:

    diff = abs(current_heading - target_heading)
    return min(diff, 360 - diff)


def check_line_start(subphase_id: str, subphase_data: Dict, current_nav: NavigationData) -> bool:
    
    # Validate navigation data
    if current_nav is None:
        logger.debug("No navigation data available")
        return False
        
    if (current_nav.latitude is None or current_nav.longitude is None or 
        current_nav.depth is None):
        logger.debug("Incomplete navigation data (missing lat/lon/depth)")
        return False
    
    # Extract target values from subphase data
    try:
        target_lat = subphase_data['START_LAT']
        target_lon = subphase_data['START_LON'] 
        target_depth = subphase_data['START_Z']
        end_lat = subphase_data['END_LAT']
        end_lon = subphase_data['END_LON']
    except KeyError as e:
        logger.error(f"Missing required field in subphase {subphase_id} data: {e}")
        return False
    
    # Calculate target heading from start to end point
    target_heading = calculate_heading_degrees(target_lat, target_lon, end_lat, end_lon)
    
    # Check horizontal distance (LAT/LON)
    distance_meters = calculate_distance_meters(
        current_nav.latitude, current_nav.longitude,
        target_lat, target_lon
    )
    
    # Get tolerance values from config
    tolerance_lat_lon = config.line_start_tolerance_lat_lon_meters
    tolerance_depth = config.line_start_tolerance_depth_meters
    tolerance_heading = config.line_start_tolerance_heading_degrees
    
    if distance_meters > tolerance_lat_lon:
        logger.debug(f"Subphase {subphase_id}: Distance {distance_meters:.1f}m > tolerance {tolerance_lat_lon}m")
        return False
    
    # Check depth
    depth_diff = abs(current_nav.depth - target_depth)
    if depth_diff > tolerance_depth:
        logger.debug(f"Subphase {subphase_id}: Depth diff {depth_diff:.1f}m > tolerance {tolerance_depth}m")
        return False
    
    # Check heading (optional - only if heading data is available)
    if current_nav.heading is not None:
        heading_diff = calculate_heading_difference(current_nav.heading, target_heading)
        if heading_diff > tolerance_heading:
            logger.debug(f"Subphase {subphase_id}: Heading diff {heading_diff:.1f}° > tolerance {tolerance_heading}°")
            return False
    else:
        logger.debug("No heading data available - skipping heading check")
    
    # All checks passed - line start detected
    heading_info = ""
    if current_nav.heading is not None:
        heading_diff = calculate_heading_difference(current_nav.heading, target_heading)
        heading_info = f", heading_diff={heading_diff:.1f}°"
    
    logger.info(f"Line start detected for subphase {subphase_id}: "
                f"pos_diff={distance_meters:.1f}m, depth_diff={depth_diff:.1f}m{heading_info}")
    
    return True


def check_point(
    target_lat: float,
    target_lon: float,
    current_nav: NavigationData,
    point_id: str = "unknown"
) -> bool:

    # Validate navigation data
    if current_nav is None:
        logger.debug("check_point: No navigation data available")
        return False
        
    if current_nav.latitude is None or current_nav.longitude is None:
        logger.debug("check_point: Incomplete navigation data (missing lat/lon)")
        return False
    
    # Get tolerance from config
    tolerance_meters = config.subphase_coordinates_tolerance_meters
    
    # Calculate horizontal distance
    distance_meters = calculate_distance_meters(
        current_nav.latitude, current_nav.longitude,
        target_lat, target_lon
    )
    
    # Check tolerance
    if distance_meters > tolerance_meters:
        logger.debug(f"Point {point_id}: Distance {distance_meters} > tolerance {tolerance_meters}")
        return False
    
    # Within tolerance
    logger.info("Point %s reached: distance=%.1fm (tolerance=%.1fm)", 
                point_id, distance_meters, tolerance_meters)
    return True



