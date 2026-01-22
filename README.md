VirtualSlope - AUV Depth Control System

AUV A18D depth control system integrated safety features.

Features

* Virtual Slope trajectory control for smooth depth transitions
* Safety system with altitude-based emergency activation
* Transition smoothing between subphases
* Error compensation for trajectory accuracy
* Integration with navigation and backseat driver APIs
* Support for both UP and DOWN trajectories
* Support for multiple missions compains

Installation

Copy all files except tcp_proxy.py to the machine inside the AUV. If the machine does not have direct communication with the DesBridge API, tcp_proxy.py must be uploaded to the computer that can receive DesBridge messages. The IP address of the TCP server is hardcoded in tcp_proxy.py and needs to be changed to the IP address of the machine running the main code.

After installation, automatic launch of the program on boot has to be configured.
This process is needed for both tcp_proxy.py and the main program.
The entry point of the Virtual Slope program is the file main.py.

Preferred method for automatic startup is a service created in systemd

Configuration

To correctly setup the system, file config.yaml has to be modified.

List of parameters that are critical for initial setup:
backseat_ip         #IP address of the computer with Backseat Driver API
backseat_port       #Port of the computer with Backseat Driver API
log_directory       #Directory for log storage
params_directory    #Directory with mission-specific yaml files

Other parameters are responsible for Virtual Slope execution and are used for adjusting the vehicle’s behaviour based on the user’s preference and experience.

Project Structure

VirtualSlope/
├── src/
│   ├── VS_controller.py          # Main depth controller
│   ├── DesBridge_api.py          # Navigation data source
│   ├── logging_config.py         # Logs management module
│   ├── mission_yaml_loader.py    # Module for finding mission params yaml file and data extraction
│   ├── check_line_start.py       # Module for AUV position check
│   ├── phase_manager.py          # Mission state manager 
│   ├── config.py                 # Configuration file processing
│   ├── mission_yaml_loader.py    # Mission file loader
│   ├── backseat_api_get.py       # Current Phase information source
│   ├── backseat_api_overload.py  # API interface for depth overload
│   └── test_altitude_source.py   # Replaces real navigation data for altitude (only for safety testing and development)
├── main.py                       # Application entry point and basic logic
├── config.yaml                   # Configuration file 
└── requirements.txt              # Python dependencies

Requirements

* Python 3.10+
* numpy 2.4.0+
* PyYAML 6.0+
* requests 2.32+

Author

Felix Sizemskii
