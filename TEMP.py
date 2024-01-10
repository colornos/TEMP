import sys
import pygatt.backends
import logging
from configparser import ConfigParser
import time
import subprocess
from struct import *
import os
import threading
import urllib3
import urllib.parse

# Plugin Code
class Plugin:
    def __init__(self):
        # Initialize the HTTP connection manager
        self.http = urllib3.PoolManager()

    def get_pi_info(self):
        # Function to extract specific Raspberry Pi info
        pi_info = {'hardware': '', 'revision': '', 'serial': '', 'model': ''}
        try:
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if line.startswith('Hardware'):
                        pi_info['hardware'] = line.strip().split(': ')[1].strip()
                    elif line.startswith('Revision'):
                        pi_info['revision'] = line.strip().split(': ')[1].strip()
                    elif line.startswith('Serial'):
                        pi_info['serial'] = line.strip().split(': ')[1].strip()
                    elif line.startswith('Model'):
                        pi_info['model'] = line.strip().split(': ')[1].strip()
        except Exception as e:
            logging.getLogger(__name__).error("Error reading Raspberry Pi info: " + str(e))
        return pi_info

    def execute(self, config, temperaturedata):
        log = logging.getLogger(__name__)
        log.info('Starting plugin: ' + __name__)

        pi_info = self.get_pi_info()  # Get Raspberry Pi info

        # Read RFID and PIN from files
        with open("/home/pi/Start/rfid.txt", "r") as f1:
            rfid = f1.read().strip()
        with open("/home/pi/Start/pin.txt", "r") as f3:
            pin = f3.read().strip()

        if not rfid:
            log.info("No card")
            with open("/home/pi/Start/plugin_response.txt", "w") as f2:
                f2.write("No card")
            return

        temperature = temperaturedata[0]['temperature']
        headers = {
            'User-Agent': 'RaspberryPi/TEMP.py',
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        # Prepare form data with temperature data and specific Raspberry Pi info
        form_data = {
            'rfid': rfid,
            'one': temperature,
            'pin': pin,
            'hardware': pi_info['hardware'],
            'revision': pi_info['revision'],
            'serial': pi_info['serial'],
            'model': pi_info['model']
        }

        encoded_data = urllib.parse.urlencode(form_data)
        r = self.http.request('POST', 'https://colornos.com/sensors/temperature.php', body=encoded_data, headers=headers)
        response = r.data.decode('utf-8')
        with open("/home/pi/Start/plugin_response.txt", "w") as f2:
            f2.write(response)
        log.info('Finished plugin: ' + __name__)
        return response

# Main Script Code
Char_temperature = '00002A1C-0000-1000-8000-00805f9b34fb'  # temperature data

def sanitize_timestamp(timestamp):
    # This function is expected to convert or sanitize the timestamp
    # from the Bluetooth device. If the original timestamp format is already
    # suitable, it might simply return the current Unix time.
    retTS = time.time()
    return retTS

def decodetemperature(handle, values):
    # This function decodes the temperature data received from the Bluetooth device.
    # The unpacking format '<BHxxxxxxI' is specific to the data structure sent by the device.
    # This might differ based on your device's specifications.
    data = unpack('<BHxxxxxxI', bytes(values[0:14]))
    retDict = {}
    retDict["valid"] = (data[0] == 0x02)  # Checks if the first byte indicates valid data
    retDict["temperature"] = data[1]      # Temperature value
    retDict["timestamp"] = sanitize_timestamp(data[2])  # Timestamp of the reading
    return retDict

def processIndication(handle, values):
    # This function processes the indication received from the Bluetooth device.
    # It checks the handle to determine if the indication is for temperature data
    # and then processes it accordingly.
    if handle == handle_temperature:
        result = decodetemperature(handle, values)
        if result not in temperaturedata:
            log.info(str(result))
            temperaturedata.append(result)
        else:
            log.info('Duplicate temperature data record')
    else:
        log.debug('Unhandled Indication encountered')

def continuous_scan(devname):
    while True:
        found = scan_for_device(devname)
        if found:
            log.info(f"{devname} found, proceeding with connection and data handling.")
            break
        time.sleep(5)  # Adjust as needed for efficient scanning

def scan_for_device(devname):
    try:
        found_devices = adapter.scan(timeout=3)  # Reduced scanning timeout
        for device in found_devices:
            if device['name'] == devname:
                return True
    except pygatt.exceptions.BLEError as e:
        log.error(f"BLE error encountered: {e}")
        adapter.reset()
    return False

def connect_device(address):
    device_connected = False
    tries = 3  # Reduced number of tries
    device = None

    while not device_connected and tries > 0:
        try:
            device = adapter.connect(address, 8, addresstype)
            device_connected = True
        except pygatt.exceptions.NotConnectedError as e:
            log.error(f"Connection attempt failed: {e}")
            tries -= 1
            time.sleep(0.5)  # Reduced delay between retries
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            break

    return device

def init_ble_mode():
    p = subprocess.Popen("sudo btmgmt le on", stdout=subprocess.PIPE, shell=True)
    (output, err) = p.communicate()
    if not err:
        log.info(output)
        return True
    else:
        log.info(err)
        return False

config = ConfigParser()
config.read('/home/pi/Start/TEMP/TEMP.ini')

# Logging setup
numeric_level = getattr(logging, config.get('Program', 'loglevel').upper(), None)
if not isinstance(numeric_level, int):
    raise ValueError('Invalid log level: %s' % loglevel)
logging.basicConfig(level=numeric_level, format='%(asctime)s %(levelname)-8s %(funcName)s %(message)s', datefmt='%a, %d %b %Y %H:%M:%S', filename=config.get('Program', 'logfile'), filemode='w')
log = logging.getLogger(__name__)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(numeric_level)
formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(funcName)s %(message)s')
ch.setFormatter(formatter)
log.addHandler(ch)

ble_address = config.get('TEMP', 'ble_address')
device_name = config.get('TEMP', 'device_name')
device_model = config.get('TEMP', 'device_model')

if device_model == 'MBP70':
    addresstype = pygatt.BLEAddressType.public
    time_offset = 0
else:
    addresstype = pygatt.BLEAddressType.random
    time_offset = 0

log.info('TEMP Started')
if not init_ble_mode():
    sys.exit()

adapter = pygatt.backends.GATTToolBackend()
adapter.start()

plugin = Plugin()

# Directly connect to the device if BLE address is known
if ble_address:
    device = connect_device(ble_address)
else:
    # Use continuous_scan if BLE address is not known
    continuous_scan(device_name)
    device = connect_device(ble_address)

# Proceed with the rest of the script
if device:
    temperaturedata = []
    handle_temperature = device.get_handle(Char_temperature)
    continue_comms = True

    try:
        device.subscribe(Char_temperature, callback=processIndication, indication=True)
    except pygatt.exceptions.NotConnectedError:
        continue_comms = False

    if continue_comms:
        log.info('Waiting for notifications for another 30 seconds')
        time.sleep(30)
        try:
            device.disconnect()
        except pygatt.exceptions.NotConnectedError:
            log.info('Could not disconnect...')

        log.info('Done receiving data from temperature thermometer')
        if temperaturedata:
            temperaturedatasorted = sorted(temperaturedata, key=lambda k: k['timestamp'], reverse=True)
            plugin.execute(config, temperaturedatasorted)
