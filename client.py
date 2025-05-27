#!/usr/bin/env python3
"""
Raspberry Pi 5 GPIO Pin Monitor
This program monitors 4 GPIO pins for switch changes and sends the data to a server.
Uses gpiozero for better compatibility with Raspberry Pi 5.
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
    }
}

CONFIG_FILE = '/etc/gpio_monitor.conf'

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
        
        # Setup signal handling for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Initialize GPIO
        self.setup_gpio()
        
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
        
        # Send data to server
        self.send_data_to_server(pin, False, time_diff_sec)  # False = LOW
        
        # Update state and timestamp
        self.pin_states[pin] = False  # LOW
        self.pin_timestamps[pin] = current_time
    
    def pin_released(self, pin):
        """Callback function when a pin is released (goes HIGH)"""
        current_time = time.time()
        
        # Calculate time difference (how long it was LOW/pressed) in seconds
        time_diff_sec = current_time - self.pin_timestamps[pin]
        
        logger.info(f"Pin {pin} changed to HIGH (released), was LOW for {time_diff_sec:.3f} seconds")
        
        # Send data to server
        self.send_data_to_server(pin, True, time_diff_sec)  # True = HIGH
        
        # Update state and timestamp
        self.pin_states[pin] = True  # HIGH
        self.pin_timestamps[pin] = current_time
    
    def send_data_to_server(self, pin, state, time_diff_sec):
        """Send pin change data to the server"""
        data = {
            'device_name': self.device_name,
            'pin': pin,
            'state': 'HIGH' if state else 'LOW',
            'time_diff_sec': round(time_diff_sec, 3),  # Round to 3 decimal places (millisecond precision)
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        try:
            # Log connection attempt with specific details
            logger.info(f"Attempting to connect to server at {self.server_ip}:{self.server_port}")
            
            # Create socket with timeout
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)  # 5 second timeout
            
            # Connect to server
            s.connect((self.server_ip, self.server_port))
            
            # Log successful connection
            logger.info(f"Connected to server at {self.server_ip}:{self.server_port}")
            
            # Send data with proper encoding
            json_data = json.dumps(data)
            logger.debug(f"Sending data: {json_data}")
            
            s.sendall(json_data.encode('utf-8'))
            
            # Wait for response with timeout
            response = s.recv(1024).decode('utf-8')
            
            if response == 'OK':
                logger.info(f"Data for pin {pin} sent successfully")
            else:
                logger.warning(f"Server returned unexpected response: {response}")
            
            # Close the connection
            s.close()
                    
        except ConnectionRefusedError:
            logger.error(f"Connection refused by server {self.server_ip}:{self.server_port}. Check if server is running and the IP/port are correct.")
        except socket.timeout:
            logger.error(f"Connection to server {self.server_ip}:{self.server_port} timed out. Check network connectivity.")
        except socket.gaierror:
            logger.error(f"Address-related error connecting to server {self.server_ip}:{self.server_port}. Check if the IP address is valid.")
        except Exception as e:
            logger.error(f"Error sending data to server: {e}", exc_info=True)
    
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
        
        # Test server connection at startup
        self.test_server_connection()
        
        try:
            # Keep the program running
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Program interrupted by user")
        finally:
            self.cleanup()
            
    def test_server_connection(self):
        """Test connection to the server at startup"""
        try:
            logger.info(f"Testing connection to server at {self.server_ip}:{self.server_port}...")
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)  # 5 second timeout
            s.connect((self.server_ip, self.server_port))
            s.close()
            logger.info("Server connection test successful!")
        except ConnectionRefusedError:
            logger.error(f"Connection refused by server {self.server_ip}:{self.server_port}. Check if server is running and the IP/port are correct.")
        except socket.timeout:
            logger.error(f"Connection to server {self.server_ip}:{self.server_port} timed out. Check network connectivity.")
        except socket.gaierror:
            logger.error(f"Address-related error connecting to server {self.server_ip}:{self.server_port}. Check if the IP address is valid.")
        except Exception as e:
            logger.error(f"Error testing connection to server: {e}", exc_info=True)

if __name__ == "__main__":
    monitor = GPIOMonitor()
    monitor.run()