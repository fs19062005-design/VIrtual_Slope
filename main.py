import asyncio, math, time, logging
from src.DesBridge_api import get_latest_navigation, start_desbridge_server
from src.VS_controller import DepthController
from src.config import config
from src.logging_config import init_logging
from src.check_line_start import calculate_distance_meters
from src.phase_manager import PhaseManager

# Conditional import for test mode
if config.test_mode:
    from src.test_altitude_source import get_test_altitude, start_input_thread

# Initialize logging early
init_logging()
logger = logging.getLogger(__name__)

COMMAND_PERIOD = config.command_period
MAX_ANGLE = config.max_angle

def calculate_step(start_z: float, end_z: float, speed: float, distance: float) -> float:
    # Use configured command period for step calculation
    period = COMMAND_PERIOD
    return (((end_z - start_z) * speed) / distance) * period


async def virtual_slope_loop(subphase_id: str, subphase_data: dict, previous_step: float = 0.0, manager: PhaseManager | None = None):

    # Get current navigation data to determine actual start depth
    nav_data = await asyncio.to_thread(get_latest_navigation)
    actual_start_z = nav_data.depth if nav_data and nav_data.depth is not None else None
    
    # Get all subphase parameters
    end_z = subphase_data['END_Z']
    speed = subphase_data['SPEED']
    start_lat = subphase_data['START_LAT']
    start_lon = subphase_data['START_LON']
    end_lat = subphase_data['END_LAT']
    end_lon = subphase_data['END_LON']
    start_z = subphase_data['START_Z']

    # Calculate distance from coordinates
    distance = calculate_distance_meters(start_lat, start_lon, end_lat, end_lon)

    step = calculate_step(start_z, end_z, speed, distance)
    max_angle_step = speed * math.sin(math.radians(MAX_ANGLE)) * COMMAND_PERIOD
    trajectory_down = end_z > start_z

    logger.info("START - Subphase %s", subphase_id)
    logger.info("Parameters: START_Z=%.2f END_Z=%s SPEED=%s DISTANCE=%.2f m STEP=%.4f TRAJECTORY=%s", start_z, end_z, speed, distance, step, ('DOWN' if trajectory_down else 'UP'))
    logger.info("Coordinates: START(%.6f,%.6f) END(%.6f,%.6f)", start_lat, start_lon, end_lat, end_lon)
    logger.info("MAX_ANGLE_STEP=%.4f m (at %s°)", max_angle_step, MAX_ANGLE)

    # Create controller synchronously
    controller = DepthController(
        start_z=start_z,
        end_z=end_z,
        step=step,
        max_angle_step=max_angle_step,
        trajectory_down=trajectory_down,
        previous_step=previous_step,
    )

    try:
        # Fixed-period scheduler to keep loop cadence stable
        next_call = time.monotonic()
        while True:
            # schedule next tick
            next_call += COMMAND_PERIOD

            # Get latest navigation (run in thread if it is blocking)
            nav_data = await asyncio.to_thread(get_latest_navigation)
            
            # Get altitude (real or simulated based on test_mode)
            if config.test_mode:
                altitude = get_test_altitude(nav_data)
            else:
                altitude = nav_data.altitude if nav_data and nav_data.altitude is not None else None

            # Run controller.update in a thread to avoid blocking event loop
            await asyncio.to_thread(controller.update, altitude)

            # Sleep until next tick; if we're behind schedule, skip sleep and continue
            sleep_time = next_call - time.monotonic()
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            else:
                # behind schedule; continue immediately (could log if needed)
                continue

    except asyncio.CancelledError:
        logger.info("Subphase %s interrupted (cancelled)", subphase_id)
        raise
    except Exception as e:
        logger.exception("Subphase %s error: %s", subphase_id, e)
        raise
    finally:
        # Store the controller's final step (may include compensation) for next subphase
        try:
            if manager is not None:
                manager.set_last_step(controller.current_step)
                logger.debug("Saved final step %.6f to manager for next subphase", controller.current_step)
        except Exception:
            logger.exception("Failed to save final step to manager")


async def phase_monitor():

    logger.info("Starting DesBridge server...")
    start_desbridge_server()
    
    # Start test mode input thread if enabled
    if config.test_mode:
        start_input_thread(config.test_initial_bottom_depth)
        logger.warning("TEST MODE ENABLED - Using simulated altitude source")
        logger.warning("Enter bottom depth values in the terminal to test safety logic")
    
    # Initialize phase manager
    manager = PhaseManager()
    
    logger.info("PHASE MONITOR STARTED")

    try:
        while True:
            try:
                # Update phase manager state
                result = await manager.update()
                
                # If VS should start
                if result is not None:
                    subphase_id, subphase_data = result
                    previous_step = manager.get_last_step()  # Get step from previous subphase
                    logger.info(f"Starting VS for subphase {subphase_id}")
                    
                    # Get current navigation data for actual depth
                    nav_data = await asyncio.to_thread(get_latest_navigation)
                    actual_start_z = nav_data.depth if nav_data and nav_data.depth is not None else None
                    
                    # Calculate new step for current subphase using actual depth
                    planned_start_z = subphase_data['START_Z']
                    start_z = actual_start_z if actual_start_z is not None else planned_start_z
                    end_z = subphase_data['END_Z']
                    speed = subphase_data['SPEED']
                    start_lat = subphase_data['START_LAT']
                    start_lon = subphase_data['START_LON']
                    end_lat = subphase_data['END_LAT']
                    end_lon = subphase_data['END_LON']
                    distance = calculate_distance_meters(start_lat, start_lon, end_lat, end_lon)
                    current_step = calculate_step(start_z, end_z, speed, distance)
                    
                    # Store current step for next transition
                    manager.set_last_step(current_step)
                    
                    # Create VS task
                    vs_task = asyncio.create_task(
                        virtual_slope_loop(subphase_id, subphase_data, previous_step, manager)
                    )
                    
                    # Register task with manager
                    manager.set_vs_task(vs_task)
            
            except Exception as e:
                logger.exception("Error in phase monitor loop: %s", e)
                # Continue monitoring despite errors

            await asyncio.sleep(config.monitoring_check_interval)

    except asyncio.CancelledError:
        logger.info("Phase monitor cancelled, shutting down...")
        await manager.cleanup()


if __name__ == '__main__':
    try:
        asyncio.run(phase_monitor())
    except KeyboardInterrupt:
        logger.info("User requested termination (Ctrl+C)")
    except Exception as e:
        logger.exception("CRITICAL ERROR: %s", e)
