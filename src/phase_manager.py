import asyncio, logging, time
from enum import Enum
from typing import Optional, Dict, Any, Tuple
from src.backseat_api_get import get_current_phase_id, is_phase_enabled, get_current_mission_name
from src.DesBridge_api import get_latest_navigation
from src.check_line_start import check_line_start, check_point
from src.mission_yaml_loader import load_all_phases
from src.config import config

logger = logging.getLogger(__name__)


class WaitingState(Enum):
    """Enum for tracking what the phase manager is waiting for"""
    NONE = "none"
    LINE_START = "line_start" 
    SUBPHASE = "subphase"


def subphase_sort_key(subphase_id: str) -> Tuple[int, int]:
    try:
        parts = subphase_id.split('-')
        return (int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        logger.warning("Invalid subphase ID format: %s", subphase_id)
        return (0, 0)


class PhaseManager:
    """Manages phase lifecycle, mission changes, and subphase transitions"""
    
    def __init__(self):
        # === Mission state ===
        self.current_mission_name: Optional[str] = None
        self.phases_data: Dict[int, Any] = {}
        
        # === Phase state ===
        self.last_phase_id: Optional[int] = None
        self.current_phase_id: Optional[int] = None
        
        # === Subphase state ===
        self.current_subphase_id: Optional[str] = None
        self.subphase_list: list = []  # Ordered list of subphases for current phase
        self.current_subphase_index: int = -1
        
        # === Waiting state ===
        self.waiting_state: WaitingState = WaitingState.NONE
        
        # === VS task ===
        self.vs_task: Optional[asyncio.Task] = None
        
        # === Step transition ===
        self.last_step: float = 0.0  # For smooth step transitions between subphases
    
    
    async def update(self) -> Optional[Tuple[str, Dict[str, Any]]]:

        # 1. Check for mission change
        await self._check_mission_change()
        
        # 2. Get current phase
        self.current_phase_id = await asyncio.to_thread(get_current_phase_id)
        
        if self.current_phase_id is None:
            return await self._handle_no_connection()
        
        # 3. Check if VS should stop (phase changed or disabled)
        should_stop = await self._check_should_stop_vs()
        if should_stop:
            await self.stop_vs(should_stop)
        
        # 4. Check if current subphase reached END coordinates (transition to next)
        if self.vs_task is not None and self.current_subphase_id is not None:
            next_subphase = await self._check_subphase_end_reached()
            if next_subphase is not None:
                # Stop current VS and return next subphase to start
                await self.stop_vs("subphase transition")
                return next_subphase
        
        # 5. Handle phase change
        if self.current_phase_id != self.last_phase_id:
            await self._handle_phase_change()
        
        # 6. Check for start conditions
        if self.waiting_state != WaitingState.NONE:
            return await self._check_start_conditions()
        
        return None
    
    async def stop_vs(self, reason: str):
        """Stop current VS task"""
        if self.vs_task is not None:
            logger.info("Stopping VS (%s)", reason)
            self.vs_task.cancel()
            try:
                await self.vs_task
            except asyncio.CancelledError:
                pass
            self.vs_task = None
    
    def set_vs_task(self, task: asyncio.Task):
        """Set current VS task (called after starting virtual_slope_loop)"""
        self.vs_task = task
    
    def get_last_step(self) -> float:
        """Get the step from previous subphase for smooth transition"""
        return self.last_step
    
    def set_last_step(self, step: float):
        """Store the step from completed subphase"""
        self.last_step = step
    
    async def cleanup(self):
        """Cleanup on shutdown"""
        await self.stop_vs("shutdown")
    
    async def _get_navigation_with_logging(self) -> Optional[Any]:
        """Get navigation data with periodic warning logging"""
        from src.DesBridge_api import get_latest_navigation
        nav_data = await asyncio.to_thread(get_latest_navigation)
        
        if nav_data is None:
            if not hasattr(self, '_last_nav_warning') or (time.time() - self._last_nav_warning > 30):
                logger.warning("No navigation data - operations paused (state: %s)", self.waiting_state.value)
                self._last_nav_warning = time.time()
        
        return nav_data
    
    # ========================================
    # PRIVATE METHODS (internal logic)
    # ========================================
    
    async def _check_subphase_end_reached(self) -> Optional[Tuple[str, Dict[str, Any]]]:

        if self.current_phase_id not in self.phases_data:
            return None
        
        phase_config = self.phases_data[self.current_phase_id]
        
        if self.current_subphase_id not in phase_config:
            return None
        
        subphase_data = phase_config[self.current_subphase_id]
        
        # Get navigation data
        nav_data = await self._get_navigation_with_logging()
        if nav_data is None:
            return None
        
        # Check if reached END coordinates
        if check_point(
            subphase_data['END_LAT'],
            subphase_data['END_LON'],
            nav_data,
            f"{self.current_subphase_id}_END"
        ):
            logger.info("Subphase %s reached END coordinates", self.current_subphase_id)
            
            # Move to next subphase
            self.current_subphase_index += 1
            
            if self.current_subphase_index < len(self.subphase_list):
                next_subphase_id = self.subphase_list[self.current_subphase_index]
                logger.info("Transitioning to next subphase: %s", next_subphase_id)
                
                if next_subphase_id in phase_config:
                    self.current_subphase_id = next_subphase_id
                    self.waiting_state = WaitingState.NONE
                    # Stop current VS and return next subphase to start
                    await self.stop_vs("subphase transition")
                    return (next_subphase_id, phase_config[next_subphase_id])
            else:
                logger.info("Last subphase %s reached END - continuing with END_Z until phase changes", self.current_subphase_id)
                # Do NOT stop VS - let it continue with END_Z
                # VS_controller will keep sending END_Z commands
        
        return None
    
    async def _check_mission_change(self):
        """Check if mission changed and reload YAML"""
        new_mission = await asyncio.to_thread(get_current_mission_name)
        
        if new_mission != self.current_mission_name:
            logger.info("Mission changed: '%s' → '%s'", self.current_mission_name, new_mission)
            
            await self.stop_vs("mission change")
            
            self.current_mission_name = new_mission
            self.waiting_state = WaitingState.NONE
            self.current_subphase_id = None
            self.current_subphase_index = -1
            self.subphase_list = []
            self.last_step = 0.0  # Reset step transition on mission change
            
            if new_mission:
                self.phases_data = load_all_phases(new_mission, use_cache=False)
                if self.phases_data:
                    logger.info("VS phases for mission '%s': %s", new_mission, list(self.phases_data.keys()))
            else:
                logger.info("No mission active - VS operations suspended")
                self.phases_data = {}
    
    async def _check_should_stop_vs(self) -> Optional[str]:

        if self.vs_task is None:
            return None
        
        # Stop if phase changed
        if self.current_phase_id != self.last_phase_id:
            return "phase changed"
        
        # Stop if phase became disabled
        if not await asyncio.to_thread(is_phase_enabled):
            return "phase disabled"
        
        return None
    
    async def _handle_phase_change(self):
        """Handle phase change - reset subphase state"""
        logger.info("Phase changed: %s → %s", self.last_phase_id, self.current_phase_id)
        
        # Reset subphase state
        self.current_subphase_id = None
        self.current_subphase_index = -1
        self.subphase_list = []
        self.waiting_state = WaitingState.NONE
        self.last_step = 0.0  # Reset step transition on phase change
        
        # Check if new phase exists in YAML
        if self.current_phase_id not in self.phases_data:
            logger.info("Phase %s not found in YAML - skipping", self.current_phase_id)
            self.last_phase_id = self.current_phase_id
            return
        
        # Check if phase is enabled
        if not await asyncio.to_thread(is_phase_enabled):
            logger.info("Phase %s is DISABLED - skipping Virtual Slope", self.current_phase_id)
            self.last_phase_id = self.current_phase_id
            return
        
        # Load subphases for this phase
        phase_config = self.phases_data[self.current_phase_id]
        
        if not isinstance(phase_config, dict):
            logger.error("Phase %s config is not a dictionary", self.current_phase_id)
            self.last_phase_id = self.current_phase_id
            return
        
        # Get sorted list of subphases
        self.subphase_list = sorted(phase_config.keys(), key=subphase_sort_key)
        
        if len(self.subphase_list) == 0:
            logger.error("Phase %s has no subphases", self.current_phase_id)
            self.last_phase_id = self.current_phase_id
            return
        
        logger.info("Phase %s activated - subphases: %s", self.current_phase_id, self.subphase_list)
        logger.info("Waiting for line start detection for first subphase %s", self.subphase_list[0])
        
        self.waiting_state = WaitingState.LINE_START
        self.last_phase_id = self.current_phase_id
    
    async def _check_start_conditions(self) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Check for line start or subphase start conditions"""
        nav_data = await self._get_navigation_with_logging()
        if nav_data is None:
            return None

        if self.current_phase_id not in self.phases_data:
            logger.warning("Current phase %s not in phases_data during start check", self.current_phase_id)
            self.waiting_state = WaitingState.NONE
            return None

        phase_config = self.phases_data[self.current_phase_id]

        # === Check for line start (first subphase) ===
        if self.waiting_state == WaitingState.LINE_START:
            if len(self.subphase_list) == 0:
                return None
            
            first_subphase_id = self.subphase_list[0]
            
            if first_subphase_id not in phase_config:
                logger.error("First subphase %s not found in phase config", first_subphase_id)
                self.waiting_state = WaitingState.NONE
                return None
            
            subphase_data = phase_config[first_subphase_id]
            
            # Check line start (with depth and heading)
            if check_line_start(first_subphase_id, subphase_data, nav_data):
                logger.info("Line start detected for subphase %s", first_subphase_id)
                self.current_subphase_id = first_subphase_id
                self.current_subphase_index = 0
                self.waiting_state = WaitingState.NONE
                return (first_subphase_id, subphase_data)
        
        # === Check for subphase transition (coordinates only) ===
        elif self.waiting_state == WaitingState.SUBPHASE:
            if self.current_subphase_index >= len(self.subphase_list):
                logger.warning("Subphase index out of range: %d >= %d", 
                             self.current_subphase_index, len(self.subphase_list))
                self.waiting_state = WaitingState.NONE
                return None
            
            next_subphase_id = self.subphase_list[self.current_subphase_index]
            
            if next_subphase_id not in phase_config:
                logger.error("Next subphase %s not found in phase config", next_subphase_id)
                self.waiting_state = WaitingState.NONE
                return None
            
            subphase_data = phase_config[next_subphase_id]
            
            # Check if reached start coordinates (lat/lon only)
            if check_point(
                subphase_data['START_LAT'],
                subphase_data['START_LON'],
                nav_data,
                next_subphase_id
            ):
                logger.info("Subphase start coordinates reached for %s", next_subphase_id)
                self.current_subphase_id = next_subphase_id
                self.waiting_state = WaitingState.NONE
                return (next_subphase_id, subphase_data)
        
        return None
    
    async def _handle_no_connection(self) -> None:
        """Handle loss of connection to Backseat API"""
        if self.last_phase_id is not None:
            logger.warning("Lost connection to Backseat API")
            self.last_phase_id = None
        
        self.waiting_state = WaitingState.NONE
        
        return None
