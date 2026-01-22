import time, logging, numpy, math
from enum import Enum
from typing import Optional
from .backseat_api_overload import send_z_command
from .config import config


logger = logging.getLogger(__name__)


class State(Enum):
    """Safety states for depth control"""
    NORMAL = "NORMAL"
    HOLD = "HOLD"
    ASCEND = "ASCEND"
    WAIT = "WAIT"
    RETURN = "RETURN"


class DepthController:

    
    def __init__(self, start_z: float, end_z: float, step: float, max_angle_step: float, trajectory_down: bool, previous_step: float):

        # Virtual Slope trajectory
        self.current_z = start_z
        self.end_z = end_z
        self.step = step
        self.end_z_reached = False
        self.target_step = step 
        self.current_step = previous_step
        
        # Safety parameters
        self.max_angle_step = max_angle_step
        self.trajectory_down = trajectory_down
        # Safety thresholds (from config)
        self.altitude_threshold_level = config.altitude_threshold_level
        self.altitude_threshold_ascend = config.altitude_threshold_ascend
        self.wait_time = config.wait_time
        
        self.command_depth: float = start_z
        
        # State management
        self.state = State.NORMAL
        self.state_start_time: Optional[float] = None
        # Transient flag: indicates WAIT was entered after ASCEND
        self._wait_from_ascend: bool = False

        # Error compensation for smooth transitions
        self.planned_z = start_z  # Track planned trajectory without smoothing
        self.error_compensation_active = False
        self.original_target_step = step  # Store original step value
        self.original_previous_step = previous_step  # Store original previous step
        
        # Create transition list and iterator for step transitions
        self.transition_list = numpy.linspace(previous_step, step, config.transition_time)
        self.step_iterator = iter(self.transition_list)
        logger.debug(self.transition_list)
        
        logger.info("DepthController initialized: %sm → %sm, step=%.4fm", start_z, end_z, step)
        logger.info("Trajectory: %s", ('DOWN (safety enabled)' if trajectory_down else 'UP'))
        if trajectory_down:
            logger.info("Max angle step: %.4fm", max_angle_step)

        self.step_transition_active = (previous_step != step)
        if self.step_transition_active:
            logger.info("Step transition: %.4f → %.4f over %d steps", 
                       previous_step, step, len(self.transition_list))
        else:
            logger.info("No step transition needed: step=%.4f", step)
    def update(self, altitude: Optional[float]) -> bool:

        self._update_step_transition()

        # 1. Handle state transitions based on altitude
        self._handle_transitions(altitude)
        
        active_state = self.state
        self._execute_current_state()

        self._advance_vs(background=(active_state != State.NORMAL))

        if active_state == State.RETURN and not self.trajectory_down:
            # For UPWARD RETURN use unified `command_depth` as hold target
            if self.current_z <= self.command_depth:
                self._set_state(State.NORMAL)

        return self.end_z_reached
    
    def _handle_transitions(self, altitude: Optional[float]) -> None:

        # altitude unavailable -> resume NORMAL
        if altitude is None:
            if self.state != State.NORMAL:
                self._set_state(State.NORMAL)
            return

        # --- Altitude-priority rules ---
        if altitude < self.altitude_threshold_ascend:
            # preserve previous interrupt logging behaviour
            if self.state in (State.WAIT, State.RETURN, State.HOLD):
                logger.warning("%s INTERRUPTED: altitude dropped to %.1fm (critical)", self.state.value, altitude)
            self._set_state(State.ASCEND)
            return

        if self.trajectory_down and altitude < self.altitude_threshold_level:
            if self.state in (State.WAIT, State.RETURN, State.HOLD):
                logger.warning("%s INTERRUPTED: altitude dropped to %.1fm (warning)", self.state.value, altitude)
            self._set_state(State.HOLD)
            return

        # --- State-driven rules (applied only if altitude did not force a change) ---
        if self.state == State.ASCEND:
            self._set_state(State.WAIT)
            return

        if self.state == State.HOLD:
            self._set_state(State.WAIT)
            return

        if self.state == State.WAIT:
            if self._wait_finished():
                self._set_state(State.RETURN)
            return

        if self.state == State.RETURN:
            if self._return_caught_vs():
                self._set_state(State.NORMAL)
            return

        # else: state == NORMAL -> nothing to do
    
    def _set_state(self, new_state: State) -> None:

        if self.state == new_state:
            return
        
        old_state = self.state

        # Update state
        self.state = new_state

        # Enter new state (pass the previous state for context)
        self._on_enter_state(new_state, old_state)

        logger.info("→ State transition: %s → %s", old_state.value, new_state.value)
    
    def _on_enter_state(self, state: State, from_state: Optional[State]) -> None:

        if state == State.ASCEND:
            self.state_start_time = None
            self.command_depth = self.current_z
            logger.warning("CRITICAL SAFETY ASCEND starting from current depth %.1fm", self.command_depth)
        
        elif state == State.HOLD:
            # HOLD is solely a safety hold for downward trajectories
            self.state_start_time = None
            logger.info("SAFETY HOLD at %.1fm", self.command_depth)
        
        elif state == State.WAIT:
            self.state_start_time = time.time()
            # Determine whether WAIT was entered after ASCEND; if so we will
            # continue to adjust `command_depth` downward in `_state_wait()`.
            self._wait_from_ascend = (from_state == State.ASCEND)
            if self._wait_from_ascend:
                logger.info("WAIT after ASCEND - continuing ascend for %s", self.wait_time)
            else:
                logger.info("WAIT after HOLD - holding for %s", self.wait_time)
        
        elif state == State.RETURN:
            logger.info("RETURN from %.1fm to VS trajectory %.1fm", self.command_depth, self.current_z)
        
        elif state == State.NORMAL:
            # Clear all safety variables
            self.state_start_time = None
            # Log only when transitioning into NORMAL from a different state
            if from_state != State.NORMAL:
                logger.info("Safety deactivated - resuming normal VS operation")
    
    def _execute_current_state(self) -> None:
        """Execute the behavior of the current state"""
        if self.state == State.NORMAL:
            self._state_normal()
        elif self.state == State.HOLD:
            self._state_hold()
        elif self.state == State.ASCEND:
            self._state_ascend()
        elif self.state == State.WAIT:
            self._state_wait()
        elif self.state == State.RETURN:
            self._state_return()
    
    def _state_normal(self) -> None:
        """Execute normal Virtual Slope operation"""
        if self.end_z_reached:
            command_z = self.end_z
        else:
            command_z = self.current_z
            next_z = self.current_z + self.current_step

            if self.trajectory_down:
                if next_z >= self.end_z:
                    logger.debug("Next step would exceed end_z (%.2f >= %.2f), switching to hold end_z", next_z, self.end_z)
                    command_z = self.end_z
                    self.current_z = self.end_z
                    self.end_z_reached = True
            else:
                if next_z <= self.end_z:
                    logger.debug("Next step would go below end_z (%.2f <= %.2f), switching to hold end_z", next_z, self.end_z)
                    command_z = self.end_z
                    self.current_z = self.end_z
                    self.end_z_reached = True
        self.command_depth = command_z
        logger.debug("NORMAL: commanding depth=%.2fm (current_z=%.2fm, end_z_reached=%s)", command_z, self.current_z, self.end_z_reached)
        self._send_command(command_z)
    
    def _state_hold(self) -> None:
        """Hold position - either during altitude warning or waiting for VS catchup"""
        self._send_command(self.command_depth)
        logger.debug("HOLD safety: depth=%.2fm", self.command_depth)
        
        # VS advancement is centralized in `update()`; do not advance here.
    
    def _state_ascend(self) -> None:
        """Emergency ascend - reduce depth to gain altitude"""
        # Ascend by reducing depth
        # Step the command depth upward (reduce numerical depth)
        self.command_depth -= self.max_angle_step
        self.command_depth = self._clamp_depth(self.command_depth)

        self._send_command(self.command_depth)
        logger.debug("ASCEND: %.2fm (VS: %.2fm)", self.command_depth, self.current_z)
        
        # VS advancement is centralized in `update()`; do not advance here.
    
    def _state_wait(self) -> None:
        """Stabilization wait period after leaving danger zone"""
        
        elapsed = time.time() - self.state_start_time if self.state_start_time else 0
        
        # Continue ascending if we entered WAIT after ASCEND, otherwise hold position
        if self._wait_from_ascend:
            self.command_depth -= self.max_angle_step
            self.command_depth = self._clamp_depth(self.command_depth)
            logger.debug("WAIT: %.1fs/%.1fs (ascending: %.2fm)", elapsed, self.wait_time, self.command_depth)
        else:
            logger.debug("WAIT: %.1fs/%.1fs (holding: %.2fm)", elapsed, self.wait_time, self.command_depth)

        self._send_command(self.command_depth)
        
        # VS advancement is centralized in `update()`; do not advance here.
    
    def _state_return(self) -> None:
        """Return to Virtual Slope trajectory by descending"""
        
        # DOWNWARD behaviour: descend gradually toward VS
        if self.trajectory_down:
            # Calculate next step
            next_return_depth = self.command_depth + self.max_angle_step
            next_return_depth = self._clamp_depth(next_return_depth)

            # Check if next step would catch or pass VS
            if next_return_depth >= self.current_z:
                # Final step - align exactly with VS and send command
                self.command_depth = self.current_z
                self._send_command(self.command_depth)
                logger.info("RETURN COMPLETE: aligned at %.2fm (VS: %.2fm)", self.command_depth, self.current_z)
            else:
                # Continue return descent
                self.command_depth = next_return_depth
                self._send_command(self.command_depth)
                logger.debug("RETURN: %.2fm → VS: %.2fm (gap: %.2fm)", self.command_depth, self.current_z, self.current_z - self.command_depth)

            # VS advancement is centralized in `update()`; do not advance here.
            return

        # UPWARD behaviour: hold `command_depth` until VS catches up
        self._send_command(self.command_depth)
        logger.debug("RETURN (UP) holding at %.2fm until VS <= %.2fm", self.command_depth, self.command_depth)

        # If VS has caught up then resume NORMAL
        if self.current_z <= self.command_depth:
            self._set_state(State.NORMAL)

    def _update_step_transition(self):
        """Update step transition with error compensation"""
        if not self.step_transition_active:
            return

        try:
            self.current_step = next(self.step_iterator)
            logger.debug("Step transition: %.4f", self.current_step)
        except StopIteration:
            self.step_transition_active = False
            self._calculate_error_compensation()
            logger.info("Step transition completed, starting error compensation")
    
    def _calculate_error_compensation(self):
        smoothed_movement = sum(self.transition_list)
        linear_movement = self.original_target_step * len(self.transition_list)
        accumulated_error = linear_movement - smoothed_movement

        total_trajectory = self.end_z - self.planned_z 
        remaining_trajectory = total_trajectory - linear_movement
        
        if abs(remaining_trajectory) > 0 and abs(self.original_target_step) > 0:
            remaining_steps = math.ceil(abs(remaining_trajectory / self.original_target_step))
            
            if remaining_steps > 0:
                error_compensation_per_step = accumulated_error / remaining_steps
                self.current_step = self.original_target_step + error_compensation_per_step
                self.target_step = self.current_step
                self.error_compensation_active = True
                
                logger.info("Error compensation: %.4fm error over %.0f steps (%.4fm/step → %.4fm/step)", 
                           accumulated_error, remaining_steps, self.original_target_step, self.current_step)
                logger.debug("Movements: linear=%.4f, smoothed=%.4f, diff=%.4f", 
                           linear_movement, smoothed_movement, accumulated_error)
                logger.debug("Trajectories: total=%.4f, smoothed=%.4f, remaining=%.4f", 
                           total_trajectory, smoothed_movement, remaining_trajectory)
            else:
                self.current_step = self.original_target_step
                logger.info("No error compensation needed - end of subphase")
        else:
            self.current_step = self.original_target_step
            logger.info("No error compensation possible - using original step: %.4f", self.original_target_step)

    def _send_command(self, z: float) -> bool:
        try:
            success = send_z_command(z)
        except Exception:
            logger.exception("Error while sending depth command")
            return False
        return success
    

    
    def _clamp_depth(self, depth: float) -> float:

        return max(config.min_depth, min(depth, config.max_depth))
    
    def _advance_vs(self, background: bool = False) -> None:
        logger.debug("_advance_vs: current_z=%.2f, current_step=%.4f, end_z=%.2f, end_z_reached=%s, trajectory_down=%s", 
                 self.current_z, self.current_step, self.end_z, self.end_z_reached, self.trajectory_down)
        
        if self.end_z_reached:
            logger.debug("_advance_vs: Already at end_z, returning")
            return

        end_reached = False
        if self.trajectory_down:
            end_reached = self.current_z >= self.end_z
        else:
            # UP trajectory: moving to lesser depth (lower z value) 
            end_reached = self.current_z <= self.end_z
            
        if end_reached:
            self.current_z = self.end_z
            self.end_z_reached = True
            logger.debug("END_Z reached: %.2f m (trajectory=%s)", self.end_z, 
                        'DOWN' if self.trajectory_down else 'UP')
            if background:
                logger.debug("[Background] END_Z reached: %s m", self.end_z)
            return

        # Advance by one step - the step value already has correct sign
        self.current_z += self.current_step
    
    def _wait_finished(self) -> bool:

        if self.state_start_time is None:
            return False
        
        elapsed = time.time() - self.state_start_time
        return elapsed >= self.wait_time
    
    def _return_caught_vs(self) -> bool:
        # Check current position against current VS depth
        return self.command_depth >= self.current_z
    
    