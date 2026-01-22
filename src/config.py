import yaml


class Config:
    """Simple configuration manager"""
    def __init__(self):
        self.config_file = "config.yaml"
        self._load_config()

    def _load_config(self):
        try:
            with open(self.config_file, 'r', encoding='utf-8') as file:
                config_data = yaml.safe_load(file)
            
            # Backseat API
            self.backseat_ip = config_data['backseat_ip']
            self.backseat_port = config_data['backseat_port']
            self.backseat_connection_timeout = config_data['backseat_connection_timeout']
            self.backseat_response_timeout = config_data['backseat_response_timeout']
            self.backseat_timeout_tuple = (self.backseat_connection_timeout, self.backseat_response_timeout)
            self.overload_command_duration = config_data['overload_command_duration']
            
            # Virtual Slope
            self.max_angle = config_data['max_angle']
            self.command_period = config_data['command_period']
            self.transition_time = config_data['transition_time']
            
            # Safety
            self.altitude_threshold_level = config_data['altitude_threshold_level']
            self.altitude_threshold_ascend = config_data['altitude_threshold_ascend']
            self.wait_time = config_data['wait_time']
            
            # Depth limits
            self.min_depth = config_data['min_depth']
            self.max_depth = config_data['max_depth']
            
            # Monitoring
            self.monitoring_check_interval = config_data['monitoring_check_interval']
            
            # DesBridge server
            self.desbridge_host = config_data['desbridge_host']
            self.desbridge_port = config_data['desbridge_port']
            
            # Line start detection tolerances
            self.line_start_tolerance_lat_lon_meters = config_data['line_start_tolerance_lat_lon_meters']
            self.line_start_tolerance_depth_meters = config_data['line_start_tolerance_depth_meters']
            self.line_start_tolerance_heading_degrees = config_data['line_start_tolerance_heading_degrees']
            
            # Subphase coordinate tolerance (for both END and START points)
            self.subphase_coordinates_tolerance_meters = config_data['subphase_coordinates_tolerance_meters']
            
            # Test mode
            self.test_mode = config_data['test_mode']
            self.test_initial_bottom_depth = config_data['test_initial_bottom_depth']
            
            # Logging
            self.log_directory = config_data['log_directory']
            self.console_log_level = config_data.get('console_log_level', 'INFO')
            self.file_log_level = config_data.get('file_log_level', 'DEBUG')
            
            self.params_directory = config_data['params_directory']

        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file '{self.config_file}' not found")
        except KeyError as e:
            raise KeyError(f"Missing configuration key: {e}")
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML configuration: {e}")


# Global configuration instance
config = Config()