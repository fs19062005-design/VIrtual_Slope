#!/usr/bin/env python3
"""
Simple TCP proxy to forward DesBridge data between machines.
Listens on DesBridge port and forwards to target machine.
"""

import socket
import threading
import argparse
import logging

# Configuration - change these values as needed
LISTEN_PORT = 12000
TARGET_HOST = "140.102.0.10"  # IP of Machine B (VS controller)
TARGET_PORT = 12000

def forward_data(source, destination):
    """Forward data from source socket to destination socket."""
    try:
        while True:
            data = source.recv(4096)
            if not data:
                break
            destination.send(data)
    except Exception:
        pass
    finally:
        source.close()
        destination.close()

def handle_client(client_socket, target_host, target_port):
    """Handle incoming client connection by creating proxy to target."""
    try:
        # Connect to target server
        target_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        target_socket.connect((target_host, target_port))
        
        # Start bidirectional forwarding
        client_to_target = threading.Thread(target=forward_data, args=(client_socket, target_socket))
        target_to_client = threading.Thread(target=forward_data, args=(target_socket, client_socket))
        
        client_to_target.daemon = True
        target_to_client.daemon = True
        
        client_to_target.start()
        target_to_client.start()
        
    except Exception as e:
        logging.error("Proxy error: {}".format(e))
        client_socket.close()

def start_proxy(listen_port=LISTEN_PORT, target_host=TARGET_HOST, target_port=TARGET_PORT):
    """Start TCP proxy server."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", listen_port))
    server.listen(5)
    
    # Set socket timeout to allow periodic checks for KeyboardInterrupt
    server.settimeout(1.0)
    
    logging.info("TCP Proxy listening on port {}, forwarding to {}:{}".format(listen_port, target_host, target_port))
    
    try:
        while True:
            try:
                client_socket, addr = server.accept()
                logging.info("Connection from {}".format(addr))
                client_thread = threading.Thread(target=handle_client, args=(client_socket, target_host, target_port))
                client_thread.daemon = True
                client_thread.start()
            except socket.timeout:
                # Timeout allows checking for KeyboardInterrupt
                continue
    except KeyboardInterrupt:
        logging.info("Shutting down proxy")
    finally:
        server.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simple TCP Proxy for DesBridge")
    parser.add_argument("--listen-port", type=int, default=LISTEN_PORT, help="Port to listen on")
    parser.add_argument("--target-host", default=TARGET_HOST, help="Target host IP")
    parser.add_argument("--target-port", type=int, default=TARGET_PORT, help="Target host port")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    start_proxy(args.listen_port, args.target_host, args.target_port)