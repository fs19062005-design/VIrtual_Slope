
import socket, time, threading
from typing import Optional, Tuple
from dataclasses import dataclass
from src.config import config

import logging

logger = logging.getLogger(__name__)


@dataclass
class NavigationData:
    """
    Complete navigation data structure from DesBridge
    All fields are Optional to handle UNDEF values from sensors
    """
    # Position (Fields 1-6)
    latitude: Optional[float] = None           # Field 1: Latitude (°)
    longitude: Optional[float] = None          # Field 2: Longitude (°)
    sigmapos: Optional[float] = None           # Field 3: Position error estimate (m)
    depth: Optional[float] = None              # Field 4: Depth (m)
    altitude: Optional[float] = None           # Field 5: Altitude above seafloor (m)
    seabed: Optional[float] = None             # Field 6: Water column height (m)
    
    # Ground-referenced velocity - Geographic frame (Fields 7-10)
    north_speed: Optional[float] = None        # Field 7: North speed relative to seafloor (m/s)
    east_speed: Optional[float] = None         # Field 8: East speed relative to seafloor (m/s)
    down_speed: Optional[float] = None         # Field 9: Down speed relative to seafloor (m/s)
    up_speed: Optional[float] = None           # Field 10: Up speed relative to seafloor (m/s)
    
    # Ground-referenced velocity - Body frame (Fields 11-13)
    u_speed: Optional[float] = None            # Field 11: Speed along X axis in body frame (m/s)
    v_speed: Optional[float] = None            # Field 12: Speed along Y axis in body frame (m/s)
    w_speed: Optional[float] = None            # Field 13: Speed along Z axis in body frame (m/s)
    
    # Water velocity - Geographic frame (Fields 14-17)
    water_north_speed: Optional[float] = None  # Field 14: Water north speed (m/s)
    water_east_speed: Optional[float] = None   # Field 15: Water east speed (m/s)
    water_down_speed: Optional[float] = None   # Field 16: Water down speed (m/s)
    water_up_speed: Optional[float] = None     # Field 17: Water up speed (m/s)
    
    # Water velocity - Body frame (Fields 18-20)
    water_u_speed: Optional[float] = None      # Field 18: Water speed along X axis (m/s)
    water_v_speed: Optional[float] = None      # Field 19: Water speed along Y axis (m/s)
    water_w_speed: Optional[float] = None      # Field 20: Water speed along Z axis (m/s)
    
    # Current velocity (Fields 21-22)
    current_north_speed: Optional[float] = None  # Field 21: Current north speed (m/s)
    current_east_speed: Optional[float] = None   # Field 22: Current east speed (m/s)
    
    # Orientation (Fields 23-25)
    heading: Optional[float] = None            # Field 23: Heading (°, positive to starboard)
    roll: Optional[float] = None               # Field 24: Roll (°, positive when port side up)
    pitch: Optional[float] = None              # Field 25: Pitch (°, positive when bow up)
    
    # Angular rates (Fields 26-31)
    yaw_rate: Optional[float] = None           # Field 26: Yaw rate (°/s, positive to starboard)
    roll_rate: Optional[float] = None          # Field 27: Roll rate (°/s)
    pitch_rate: Optional[float] = None         # Field 28: Pitch rate (°/s)
    p: Optional[float] = None                  # Field 29: Angular velocity around X axis (°/s)
    q: Optional[float] = None                  # Field 30: Angular velocity around Y axis (°/s)
    r: Optional[float] = None                  # Field 31: Angular velocity around Z axis (°/s)
    
    # Accelerations (Fields 32-34)
    ax: Optional[float] = None                 # Field 32: Acceleration along X axis (m/s², gravity compensated)
    ay: Optional[float] = None                 # Field 33: Acceleration along Y axis (m/s²)
    az: Optional[float] = None                 # Field 34: Acceleration along Z axis (m/s²)


class DesBridgeDataProvider:
    """TCP server for receiving data from DesBridge with data export capability"""
    def __init__(self):

        self.host = config.desbridge_host
        self.port = config.desbridge_port

        self.server_socket: Optional[socket.socket] = None
        self.client_socket: Optional[socket.socket] = None
        self.client_address: Optional[Tuple[str, int]] = None
        self.running = False
        self.heartbeat_thread: Optional[threading.Thread] = None

        # Storage for latest navigation data
        self.latest_navigation: Optional[NavigationData] = None
        self.data_lock = threading.Lock()
        
    def get_latest_navigation(self) -> Optional[NavigationData]:
        """
        Get latest navigation data
        
        Returns:
            NavigationData: Latest navigation data or None if no data available
        """
        with self.data_lock:
            return self.latest_navigation
    
    def start_server(self):

        try:
            # Create, bind and listen (IPv4 socket)
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(1)

            logger.info("DesBridge server listening on %s:%s", self.host, self.port)

            # Accept loop
            while True:
                try:
                    client_sock, client_addr = self.server_socket.accept()
                    self.client_socket = client_sock
                    self.client_address = client_addr

                    logger.info("DesBridge connected from %s", self.client_address)

                    self.running = True

                    # Start heartbeat thread
                    self.heartbeat_thread = threading.Thread(target=self.send_heartbeat, daemon=True)
                    self.heartbeat_thread.start()

                    # Handle client messages (blocks until client disconnects)
                    self.handle_client()

                except ConnectionResetError:
                    logger.warning("DesBridge disconnected")
                except Exception:
                    logger.exception("Error handling DesBridge client")
                finally:
                    # Ensure client cleanup and continue waiting for next connection
                    self.cleanup_client()
                    logger.info("Connection closed; waiting for new connection...")

        except KeyboardInterrupt:
            logger.info("DesBridge server stopping (KeyboardInterrupt)")
        except Exception:
            logger.exception("DesBridge server error during start")
        finally:
            self.cleanup()
    
    def send_heartbeat(self):
        """Send heartbeat messages every second"""
        while self.running and self.client_socket:
            try:
                # Send heartbeat
                heartbeat_msg = "$R_HBEAT\r\n"
                self.client_socket.send(heartbeat_msg.encode('ascii'))
                time.sleep(1)
                
            except (ConnectionResetError, BrokenPipeError):
                break
            except Exception:
                break
    
    def handle_client(self):
        """Handle messages from DesBridge (no console output)."""
        buffer = ""

        while self.running and self.client_socket:
            try:
                # Receive data from client
                data = self.client_socket.recv(4096)
                if not data:
                    break

                # Decode and add to buffer
                buffer += data.decode('ascii', errors='ignore')

                # Process all complete lines in buffer
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.rstrip('\r')

                    if line:
                        self.process_message(line)

            except ConnectionResetError:
                break
            except Exception:
                break
    
    def process_message(self, message: str):

        if message.startswith("$HBEAT"):
            # Received heartbeat response - process silently
            pass
        elif message.startswith("$NAVIGATION"):
            # Process navigation data
            self.parse_navigation(message)
        # Ignore all other messages
    
    def parse_navigation(self, nav_message: str):

        try:
            # Remove checksum if present
            if '*' in nav_message:
                nav_message = nav_message.split('*')[0]
            
            # Split by commas
            fields = nav_message.split(',')
            
            if len(fields) < 10:
                return
            
            # Extract all 34 fields from DesBridge $NAVIGATION message
            # Position (Fields 1-6)
            latitude = self.safe_float(fields[1]) if len(fields) > 1 else None
            longitude = self.safe_float(fields[2]) if len(fields) > 2 else None
            sigmapos = self.safe_float(fields[3]) if len(fields) > 3 else None
            depth = self.safe_float(fields[4]) if len(fields) > 4 else None
            altitude = self.safe_float(fields[5]) if len(fields) > 5 else None
            seabed = self.safe_float(fields[6]) if len(fields) > 6 else None
            
            # Ground-referenced velocity - Geographic frame (Fields 7-10)
            north_speed = self.safe_float(fields[7]) if len(fields) > 7 else None
            east_speed = self.safe_float(fields[8]) if len(fields) > 8 else None
            down_speed = self.safe_float(fields[9]) if len(fields) > 9 else None
            up_speed = self.safe_float(fields[10]) if len(fields) > 10 else None
            
            # Ground-referenced velocity - Body frame (Fields 11-13)
            u_speed = self.safe_float(fields[11]) if len(fields) > 11 else None
            v_speed = self.safe_float(fields[12]) if len(fields) > 12 else None
            w_speed = self.safe_float(fields[13]) if len(fields) > 13 else None
            
            # Water velocity - Geographic frame (Fields 14-17)
            water_north_speed = self.safe_float(fields[14]) if len(fields) > 14 else None
            water_east_speed = self.safe_float(fields[15]) if len(fields) > 15 else None
            water_down_speed = self.safe_float(fields[16]) if len(fields) > 16 else None
            water_up_speed = self.safe_float(fields[17]) if len(fields) > 17 else None
            
            # Water velocity - Body frame (Fields 18-20)
            water_u_speed = self.safe_float(fields[18]) if len(fields) > 18 else None
            water_v_speed = self.safe_float(fields[19]) if len(fields) > 19 else None
            water_w_speed = self.safe_float(fields[20]) if len(fields) > 20 else None
            
            # Current velocity (Fields 21-22)
            current_north_speed = self.safe_float(fields[21]) if len(fields) > 21 else None
            current_east_speed = self.safe_float(fields[22]) if len(fields) > 22 else None
            
            # Orientation (Fields 23-25)
            heading = self.safe_float(fields[23]) if len(fields) > 23 else None
            roll = self.safe_float(fields[24]) if len(fields) > 24 else None
            pitch = self.safe_float(fields[25]) if len(fields) > 25 else None
            
            # Angular rates (Fields 26-31)
            yaw_rate = self.safe_float(fields[26]) if len(fields) > 26 else None
            roll_rate = self.safe_float(fields[27]) if len(fields) > 27 else None
            pitch_rate = self.safe_float(fields[28]) if len(fields) > 28 else None
            p = self.safe_float(fields[29]) if len(fields) > 29 else None
            q = self.safe_float(fields[30]) if len(fields) > 30 else None
            r = self.safe_float(fields[31]) if len(fields) > 31 else None
            
            # Accelerations (Fields 32-34)
            ax = self.safe_float(fields[32]) if len(fields) > 32 else None
            ay = self.safe_float(fields[33]) if len(fields) > 33 else None
            az = self.safe_float(fields[34]) if len(fields) > 34 else None
            
            # Store navigation data with thread safety
            # Create NavigationData with all extracted fields
            # Fields not present in message will be None (from dataclass defaults)
            nav_data = NavigationData(
                latitude=latitude, longitude=longitude, sigmapos=sigmapos,
                depth=depth, altitude=altitude, seabed=seabed,
                north_speed=north_speed, east_speed=east_speed, 
                down_speed=down_speed, up_speed=up_speed,
                u_speed=u_speed, v_speed=v_speed, w_speed=w_speed,
                water_north_speed=water_north_speed, water_east_speed=water_east_speed,
                water_down_speed=water_down_speed, water_up_speed=water_up_speed,
                water_u_speed=water_u_speed, water_v_speed=water_v_speed, 
                water_w_speed=water_w_speed,
                current_north_speed=current_north_speed, current_east_speed=current_east_speed,
                heading=heading, roll=roll, pitch=pitch,
                yaw_rate=yaw_rate, roll_rate=roll_rate, pitch_rate=pitch_rate,
                p=p, q=q, r=r,
                ax=ax, ay=ay, az=az
            )
            
            with self.data_lock:
                self.latest_navigation = nav_data
            
        except Exception:
            logger.exception("Error parsing NAVIGATION")
    
    def safe_float(self, value: str) -> Optional[float]:
        """Safe conversion of string to float"""
        try:
            if not value or value.upper() == "UNDEF" or value.strip() == "":
                return None
            return float(value)
        except (ValueError, TypeError):
            return None
    
    def cleanup_client(self):
        """Clean up client resources"""
        self.running = False
        
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
            self.client_socket = None
            
        self.client_address = None
    
    def cleanup(self):
        """Clean up all server resources"""
        self.cleanup_client()
        
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
            self.server_socket = None


# Global instance for use by other modules
desbridge_provider = DesBridgeDataProvider()


def get_latest_navigation() -> Optional[NavigationData]:
    """
    Get latest navigation data from global provider instance
    
    Returns:
        NavigationData: Latest navigation data or None if no data available
    """
    return desbridge_provider.get_latest_navigation()


def start_desbridge_server():
    """Start DesBridge server in a separate daemon thread."""
    server_thread = threading.Thread(target=desbridge_provider.start_server, daemon=True)
    server_thread.start()
    return server_thread


if __name__ == "__main__":
    # Run DesBridge server standalone for testing
    # NOTE: For production use, prefer run_bridge_server.py which includes HTTP bridge
    logger.info("=== DesBridge Data Provider (STANDALONE MODE) ===")
    logger.info("Configuration:")
    logger.info("  Server IP: %s", config.desbridge_host)
    logger.info("  DesBridge client IP: 140.102.1.1 (expected)")
    logger.info("  Port: %s", config.desbridge_port)
    logger.info("")
    logger.info("Press Ctrl+C to stop")

    # Start server thread
    server_thread = start_desbridge_server()

    try:
        # Keep main thread alive while server runs
        while server_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received stop signal")
    finally:
        desbridge_provider.cleanup()
        logger.info("Server stopped")