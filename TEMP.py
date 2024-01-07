#!/usr/bin/python3

import sys
import pygatt
import logging
from configparser import ConfigParser
import time
import urllib3
import urllib.parse
from struct import *

# Plugin Class
class Plugin:
    def __init__(self):
        self.http = urllib3.PoolManager()

    def get_pi_info(self):
        pi_info_keys = ['Hardware', 'Revision', 'Serial', 'Model']
        pi_info = {key.lower(): '' for key in pi_info_keys}
        try:
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    split_line = line.strip().split(': ')
                    if split_line[0] in pi_info_keys:
                        pi_info[split_line[0].lower()] = split_line[1]
        except IOError as e:
            logging.getLogger(__name__).error(f"Error reading Pi info: {e}")
        return pi_info

    def execute(self, config, temperature_data):
        log = logging.getLogger(__name__)
        log.info('Starting plugin: ' + __name__)
        pi_info = self.get_pi_info()

        try:
            with open("/home/pi/Start/rfid.txt", "r") as f1:
                rfid = f1.read().strip()
            with open("/home/pi/Start/pin.txt", "r") as f3:
                pin = f3.read().strip()
        except IOError as e:
            log.error(f"File read error: {e}")
            return

        if not rfid:
            log.info("No card")
            with open("/home/pi/Start/plugin_response.txt", "w") as f2:
                f2.write("No card")
        else:
            temperature = temperature_data[0]['temperature']
            headers = {'User-Agent': 'RaspberryPi/TEMP.py', 'Content-Type': 'application/x-www-form-urlencoded'}
            form_data = {'rfid': rfid, 'one': temperature, 'pin': pin, **pi_info}
            encoded_data = urllib.parse.urlencode(form_data)
            r = self.http.request('POST', 'https://colornos.com/sensors/temperature.php', body=encoded_data, headers=headers)
            response = r.data.decode('utf-8')
            with open("/home/pi/Start/plugin_response.txt", "w") as f2:
                f2.write(response)
            log.info('Finished plugin: ' + __name__)
            return response

# Main Script Code
def sanitize_timestamp(timestamp):
    return time.time()

def decode_temperature(values):
    data = unpack('<BHxxxxxxI', bytes(values[0:14]))
    return {
        "valid": (data[0] == 0x02),
        "temperature": data[1],
        "timestamp": sanitize_timestamp(data[2])
    }

def process_indication(handle, values, handle_temperature, temperature_data, log):
    if handle == handle_temperature:
        result = decode_temperature(values)
        if result not in temperature_data:
            log.info(str(result))
            temperature_data.append(result)
        else:
            log.info('Duplicate temperature data record')
    else:
        log.debug('Unhandled Indication encountered')

def wait_for_device(adapter, devname, log, timeout=1800):
    found = False
    start_time = time.time()
    while not found and (time.time() - start_time) < timeout:
        try:
            found_devices = adapter.scan(timeout=5)
            for device in found_devices:
                if device['name'] == devname:
                    found = True
                    log.info(f"{devname} found.")
                    break
            if not found:
                log.debug(f"{devname} not found, retrying...")
            time.sleep(1)
        except pygatt.exceptions.BLEError as e:
            log.error(f"BLE error encountered: {e}. Resetting adapter.")
            adapter.reset()
            time.sleep(1)
    if not found:
        log.warning(f"Timeout reached. {devname} not found.")
    return found

def connect_device(adapter, address, log, addresstype):
    device_connected = False
    tries = 5
    while not device_connected and tries > 0:
        try:
            device = adapter.connect(address, 8, addresstype)
            device_connected = True
        except pygatt.exceptions.NotConnectedError as e:
            log.error(f"Connection attempt failed: {e}")
            tries -= 1
            time.sleep(1)
    return device

def setup_logging(config):
    numeric_level = getattr(logging, config.get('Program', 'loglevel').upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % loglevel)
    logging.basicConfig(level=numeric_level, format='%(asctime)s %(levelname)-8s %(funcName)s %(message)s',
                        datefmt='%a, %d %b %Y %H:%M:%S', filename=config.get('Program', 'logfile'), filemode='w')

def main():
    config = ConfigParser()
    config.read('/home/pi/Start/TEMP/TEMP.ini')
    setup_logging(config)

    log = logging.getLogger(__name__)
    adapter = pygatt.backends.GATTToolBackend()

    try:
        adapter.start()
        plugin = Plugin()
        ble_address = config.get('TEMP', 'ble_address')
        device_name = config.get('TEMP', 'device_name')
        device_model = config.get('TEMP', 'device_model')

        addresstype = pygatt.BLEAddressType.public if device_model == 'MBP70' else pygatt.BLEAddressType.random

        if wait_for_device(adapter, device_name, log):
            device = connect_device(adapter, ble_address, log, addresstype)
            if device:
                temperature_data = []
                handle_temperature = device.get_handle(Char_temperature)
                try:
                    device.subscribe(Char_temperature, callback=lambda handle, values: process_indication(handle, values, handle_temperature, temperature_data, log), indication=True)
                    time.sleep(30)  # Wait for notifications
                except pygatt.exceptions.NotConnectedError:
                    log.info('Could not subscribe to device')
                finally:
                    try:
                        device.disconnect()
                    except pygatt.exceptions.NotConnectedError:
                        log.info('Could not disconnect...')

                if temperature_data:
                    sorted_data = sorted(temperature_data, key=lambda k: k['timestamp'], reverse=True)
                    plugin.execute(config, sorted_data)
    except Exception as e:
        log.error(f"An error occurred: {e}")
    finally:
        try:
            adapter.stop()
            log.info("Adapter stopped")
        except Exception as e:
            log.error(f"Error stopping adapter: {e}")

if __name__ == "__main__":
    main()
