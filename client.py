#!/usr/bin/env python3
"""
Raspberry Pi 5 GPIO Pin Monitor with Network Reconnection
This program monitors 4 GPIO pins for switch changes and sends the data to a server.
Uses gpiozero for better compatibility with Raspberry Pi 5.
Includes network monitoring and automatic reconnection capabilities.
"""

from gpiozero import Button
import socket
import time
import json
import configparser
import os
import sys
import signal
import logging
from logging.handlers import RotatingFileHandler
import subprocess
import threading
from queue import Queue
import urllib.request

# Setup logging
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_file = '/var/log/gpio_monitor.log'
log_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
log_handler.setFormatter(log_formatter)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)

logger = logging.getLogger('gpio_monitor')
logger.setLevel(logging.INFO)
logger.addHandler(log_handler)
logger.addHandler(console_handler)

# Default configuration
DEFAULT_CONFIG = {
    'device': {
        'name': 'Andon-1',
    },
    'server': {
        'ip': '192.168.1.128',
        'port': 5000
    },
    'gpio': {
        'pins': '23,24,25,12',
        'debounce_time': 100  # milliseconds
    },
    'network': {
        'check_interval': 30,  # seconds between network checks
        'reconnect_timeout': 300,  # max seconds to spend trying to reconnect
        'wifi_interface': 'wlan0',
        'ethernet_interface': 'eth0',
        'gateway_check': 'true',  # Check default gateway connectivity
        'server_check': 'true'   # Check server connectivity
    }
}

CONFIG_FILE = '/etc/gpio_monitor.conf'

class NetworkManager:
    def __init__(self, config):
        self.config = config
        self.wifi_interface = config['network']['wifi_interface']
        self.ethernet_interface = config['network']['ethernet_interface']
        self.server_ip = config['server']['ip']
        self.server_port = int(config['server']['port'])
        self.check_interval = int(config['network']['check_interval'])
        self.reconnect_timeout = int(config['network']['reconnect_timeout'])
        self.gateway_check = config['network']['gateway_check'].lower() == 'true'
        self.server_check = config['network']['server_check'].lower() == 'true'
        self.is_connected = False
        self.last_check_time = 0
        self.gateway_ip = None
        
    def check_interface_status(self, interface):
        """Check if a network interface is up and has an IP address"""
        try:
            result = subprocess.run(['ip', 'addr', 'show', interface], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                output = result.stdout
                # Check if interface is UP and has an inet address
                if 'state UP' in output and 'inet ' in output:
                    return True
            return False
        except Exception as e:
            logger.debug(f"Error checking interface {interface}: {e}")
            return False
    
    def get_default_gateway(self):
        """Get the default gateway IP address"""
        try:
            result = subprocess.run(['ip', 'route', 'show', 'default'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                output = result.stdout.strip()
                # Parse "default via 192.168.1.1 dev wlan0" format
                parts = output.split()
                if len(parts) >= 3 and parts[0] == 'default' and parts[1] == 'via':
                    return parts[2]
            return None
        except Exception as e:
            logger.debug(f"Error getting default gateway: {e}")
            return None
    
    def test_server_connectivity(self):
        """Test connectivity to the specific server"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((self.server_ip, self.server_port))
            sock.close()
            return result == 0
        except Exception as e:
            logger.debug(f"Error testing server connectivity: {e}")
            return False
    
    def test_gateway_connectivity(self):
        """Test connectivity to the default gateway"""
        if not self.gateway_ip:
            self.gateway_ip = self.get_default_gateway()
            if not self.gateway_ip:
                logger.debug("No default gateway found")
                return False
        
        try:
            # Ping the gateway
            result = subprocess.run(['ping', '-c', '1', '-W', '3', self.gateway_ip], 
                                  capture_output=True, timeout=10)
            return result.returncode == 0
        except Exception as e:
            logger.debug(f"Error pinging gateway {self.gateway_ip}: {e}")
            return False
    
    def test_lan_connectivity(self):
        """Test LAN connectivity using available methods"""
        connectivity_tests = []
        
        # Test server connectivity if enabled
        if self.server_check:
            server_ok = self.test_server_connectivity()
            connectivity_tests.append(('server', server_ok))
            if server_ok:
                return True  # If server is reachable, we're good
        
        # Test gateway connectivity if enabled
        if self.gateway_check:
            gateway_ok = self.test_gateway_connectivity()
            connectivity_tests.append(('gateway', gateway_ok))
            if gateway_ok:
                return True  # If gateway is reachable, network is up
        
        # Log test results
        test_results = ', '.join([f"{name}: {result}" for name, result in connectivity_tests])
        logger.debug(f"Connectivity tests - {test_results}")
        
        # If no tests were enabled or all failed
        return False
    
    def restart_network_interface(self, interface):
        """Restart a network interface"""
        try:
            logger.info(f"Restarting network interface {interface}")
            
            # Bring interface down
            subprocess.run(['sudo', 'ip', 'link', 'set', interface, 'down'], 
                         timeout=30, check=True)
            time.sleep(2)
            
            # Bring interface up
            subprocess.run(['sudo', 'ip', 'link', 'set', interface, 'up'], 
                         timeout=30, check=True)
            time.sleep(5)
            
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error restarting interface {interface}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error restarting interface {interface}: {e}")
            return False
    
    def restart_wifi(self):
        """Restart WiFi connection"""
        try:
            logger.info("Attempting to restart WiFi connection")
            
            # First try to restart the interface
            if self.restart_network_interface(self.wifi_interface):
                time.sleep(10)  # Wait for connection to establish
                
                # If interface restart didn't work, try wpa_supplicant restart
                if not self.check_interface_status(self.wifi_interface):
                    logger.info("Restarting wpa_supplicant service")
                    subprocess.run(['sudo', 'systemctl', 'restart', 'wpa_supplicant'], 
                                 timeout=30, check=True)
                    time.sleep(15)
                
                # Try DHCP renewal
                logger.info("Renewing DHCP lease")
                subprocess.run(['sudo', 'dhclient', '-r', self.wifi_interface], 
                             timeout=30)
                time.sleep(2)
                subprocess.run(['sudo', 'dhclient', self.wifi_interface], 
                             timeout=30)
                time.sleep(10)
                
                # Update gateway after network restart
                self.gateway_ip = None
                
                return self.check_interface_status(self.wifi_interface)
            
            return False
            
        except Exception as e:
            logger.error(f"Error restarting WiFi: {e}")
            return False
    
    def restart_ethernet(self):
        """Restart Ethernet connection"""
        try:
            logger.info("Attempting to restart Ethernet connection")
            
            if self.restart_network_interface(self.ethernet_interface):
                time.sleep(5)
                
                # Try DHCP renewal
                logger.info("Renewing DHCP lease for Ethernet")
                subprocess.run(['sudo', 'dhclient', '-r', self.ethernet_interface], 
                             timeout=30)
                time.sleep(2)
                subprocess.run(['sudo', 'dhclient', self.ethernet_interface], 
                             timeout=30)
                time.sleep(10)
                
                # Update gateway after network restart
                self.gateway_ip = None
                
                return self.check_interface_status(self.ethernet_interface)
            
            return False
            
        except Exception as e:
            logger.error(f"Error restarting Ethernet: {e}")
            return False
    
    def attempt_reconnection(self):
        """Attempt to reconnect to the internet"""
        logger.info("Starting network reconnection attempts")
        start_time = time.time()
        
        while time.time() - start_time < self.reconnect_timeout:
            # Check current interface status
            wifi_up = self.check_interface_status(self.wifi_interface)
            ethernet_up = self.check_interface_status(self.ethernet_interface)
            
            logger.info(f"Interface status - WiFi: {wifi_up}, Ethernet: {ethernet_up}")
            
            # Try to restart interfaces that are down
            if not wifi_up:
                if self.restart_wifi():
                    logger.info("WiFi restart successful")
                    if self.test_lan_connectivity():
                        logger.info("LAN connectivity restored via WiFi")
                        return True
            
            if not ethernet_up:
                if self.restart_ethernet():
                    logger.info("Ethernet restart successful")
                    if self.test_lan_connectivity():
                        logger.info("LAN connectivity restored via Ethernet")
                        return True
            
            # If interfaces are up but no LAN connectivity, try connectivity test
            if (wifi_up or ethernet_up) and self.test_lan_connectivity():
                logger.info("LAN connectivity confirmed")
                return True
            
            # Wait before next attempt
            logger.info("Waiting 30 seconds before next reconnection attempt")
            time.sleep(30)
        
        logger.error(f"Failed to restore LAN connectivity after {self.reconnect_timeout} seconds")
        return False
    
    def check_connectivity(self):
        """Check network connectivity and attempt reconnection if needed"""
        current_time = time.time()
        
        # Only check if enough time has passed since last check
        if current_time - self.last_check_time < self.check_interval:
            return self.is_connected
        
        self.last_check_time = current_time
        
        # Test internet connectivity
        was_connected = self.is_connected
        self.is_connected = self.test_lan_connectivity()
        
        if not self.is_connected:
            if was_connected:
                logger.warning("LAN connectivity lost!")
            
            # Attempt reconnection
            self.is_connected = self.attempt_reconnection()
        
        return self.is_connected

class GPIOMonitor:
    def __init__(self):
        self.config = self.load_config()
        self.device_name = self.config['device']['name']
        self.server_ip = self.config['server']['ip']
        self.server_port = int(self.config['server']['port'])
        self.pins = [int(pin) for pin in self.config['gpio']['pins'].split(',')]
        self.debounce_time = int(self.config['gpio']['debounce_time'])
        
        self.pin_states = {}
        self.pin_timestamps = {}
        self.running = True
        self.last_send_failed = False  # Track if last send attempt failed
        
        # Initialize network manager
        self.network_manager = NetworkManager(self.config)
        
        # Setup signal handling for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Initialize GPIO
        self.setup_gpio()
        
        # Start network monitoring thread
        self.network_thread = threading.Thread(target=self.network_monitor_loop, daemon=True)
        self.network_thread.start()
        
    def load_config(self):
        """Load configuration from file or create default config if not exists"""
        config = configparser.ConfigParser()
        
        # Set default configuration
        for section, items in DEFAULT_CONFIG.items():
            if not config.has_section(section):
                config.add_section(section)
            for key, value in items.items():
                config.set(section, key, str(value))
        
        # Try to read configuration file
        if os.path.exists(CONFIG_FILE):
            try:
                config.read(CONFIG_FILE)
                logger.info(f"Configuration loaded from {CONFIG_FILE}")
            except Exception as e:
                logger.error(f"Error loading configuration: {e}")
                logger.info("Using default configuration")
        else:
            logger.info(f"Config file {CONFIG_FILE} not found, using default configuration")
            
            # Create default config file
            try:
                with open(CONFIG_FILE, 'w') as configfile:
                    config.write(configfile)
                logger.info(f"Default configuration saved to {CONFIG_FILE}")
            except Exception as e:
                logger.error(f"Could not save default configuration: {e}")
        
        return config
    
    def setup_gpio(self):
        """Initialize GPIO pins using gpiozero"""
        self.buttons = {}
        
        # Setup pins with pull-up resistors using gpiozero
        for pin in self.pins:
            # Create Button object with pull-up and debounce
            button = Button(pin, pull_up=True, bounce_time=self.debounce_time/1000.0)
            
            # Set initial state and timestamp
            self.pin_states[pin] = not button.is_pressed  # gpiozero inverts logic for buttons
            self.pin_timestamps[pin] = time.time()
            
            # Add event callbacks
            button.when_pressed = lambda p=pin: self.pin_pressed(p)
            button.when_released = lambda p=pin: self.pin_released(p)
            
            # Store button object
            self.buttons[pin] = button
            
        logger.info(f"GPIO pins {self.pins} initialized with pull-up resistors")
    
    def pin_pressed(self, pin):
        """Callback function when a pin is pressed (goes LOW)"""
        current_time = time.time()
        
        # Calculate time difference (how long it was HIGH/released) in seconds
        time_diff_sec = current_time - self.pin_timestamps[pin]
        
        logger.info(f"Pin {pin} changed to LOW (pressed), was HIGH for {time_diff_sec:.3f} seconds")
        
        # Send data to server (or queue if network is down)
        self.handle_pin_data(pin, False, time_diff_sec)  # False = LOW
        
        # Update state and timestamp
        self.pin_states[pin] = False  # LOW
        self.pin_timestamps[pin] = current_time
    
    def pin_released(self, pin):
        """Callback function when a pin is released (goes HIGH)"""
        current_time = time.time()
        
        # Calculate time difference (how long it was LOW/pressed) in seconds
        time_diff_sec = current_time - self.pin_timestamps[pin]
        
        logger.info(f"Pin {pin} changed to HIGH (released), was LOW for {time_diff_sec:.3f} seconds")
        
        # Send data to server (or queue if network is down)
        self.handle_pin_data(pin, True, time_diff_sec)  # True = HIGH
        
        # Update state and timestamp
        self.pin_states[pin] = True  # HIGH
        self.pin_timestamps[pin] = current_time
    
    def handle_pin_data(self, pin, state, time_diff_sec):
        """Handle pin data - send immediately if network is up"""
        data = {
            'device_name': self.device_name,
            'pin': pin,
            'state': 'HIGH' if state else 'LOW',
            'time_diff_sec': round(time_diff_sec, 3),
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        if self.network_manager.is_connected:
            # If we previously failed to send and now we're reconnected, send warning first
            if self.last_send_failed:
                self.send_connectivity_warning()
                self.last_send_failed = False
            
            success = self.send_data_to_server(data)
            if not success:
                logger.warning(f"Failed to send pin {pin} data to server")
                self.last_send_failed = True
        else:
            logger.warning(f"Pin {pin} data lost - no network connection")
            self.last_send_failed = True
    
    def send_connectivity_warning(self):
        """Send a connectivity warning message to the server"""
        warning_data = {
            'device_name': self.device_name,
            'pin': -1,  # Special pin for connectivity messages
            'state': 'CONNECTIVITY_RESTORED',
            'time_diff_sec': 0.0,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        success = self.send_data_to_server(warning_data)
        if success:
            logger.info("Sent connectivity restoration notice to server")
        else:
            logger.warning("Failed to send connectivity restoration notice")
    
    def send_data_to_server(self, data):
        """Send pin change data to the server"""
        try:
            # Create socket with timeout
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)  # 5 second timeout
            
            # Connect to server
            s.connect((self.server_ip, self.server_port))
            
            # Send data with proper encoding
            json_data = json.dumps(data)
            logger.debug(f"Sending data: {json_data}")
            
            s.sendall(json_data.encode('utf-8'))
            
            # Wait for response with timeout
            response = s.recv(1024).decode('utf-8')
            
            # Close the connection
            s.close()
            
            if response == 'OK':
                logger.info(f"Data for pin {data['pin']} sent successfully")
                return True
            else:
                logger.warning(f"Server returned unexpected response: {response}")
                return False
                    
        except ConnectionRefusedError:
            logger.error(f"Connection refused by server {self.server_ip}:{self.server_port}")
            return False
        except socket.timeout:
            logger.error(f"Connection to server {self.server_ip}:{self.server_port} timed out")
            return False
        except socket.gaierror:
            logger.error(f"Address-related error connecting to server {self.server_ip}:{self.server_port}")
            return False
        except Exception as e:
            logger.error(f"Error sending data to server: {e}")
            return False
    
    def network_monitor_loop(self):
        """Background thread to monitor network connectivity"""
        logger.info("Network monitoring thread started")
        
        while self.running:
            try:
                # Check network connectivity
                was_connected = self.network_manager.is_connected
                self.network_manager.check_connectivity()
                
                # Log connectivity changes
                if was_connected and not self.network_manager.is_connected:
                    logger.warning("Network connectivity lost")
                    self.last_send_failed = True
                elif not was_connected and self.network_manager.is_connected:
                    logger.info("Network connectivity restored")
                    # Don't send warning here - wait for next GPIO event
                
                time.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                logger.error(f"Error in network monitoring loop: {e}")
                time.sleep(10)
    
    def signal_handler(self, sig, frame):
        """Handle termination signals gracefully"""
        logger.info("Shutdown signal received, cleaning up...")
        self.running = False
        self.cleanup()
        sys.exit(0)
    
    def cleanup(self):
        """Clean up GPIO resources"""
        for pin, button in self.buttons.items():
            button.close()
        logger.info("GPIO resources cleaned up")
    
    def run(self):
        """Main loop to keep the program running"""
        logger.info(f"GPIO Monitor started on {self.device_name}")
        logger.info(f"Monitoring pins: {self.pins}")
        logger.info(f"Will connect to server: {self.server_ip}:{self.server_port}")
        
        # Test initial network connectivity
        self.network_manager.check_connectivity()
        if self.network_manager.is_connected:
            logger.info("Initial LAN connectivity confirmed")
        else:
            logger.warning("Initial LAN connectivity check failed")
        
        try:
            # Keep the program running
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Program interrupted by user")
        finally:
            self.cleanup()

if __name__ == "__main__":
    monitor = GPIOMonitor()
    monitor.run()