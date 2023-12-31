#!/usr/bin/python3

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
        self.http = urllib3.PoolManager()

    def execute(self, config, temperaturedata):
        log = logging.getLogger(__name__)
        log.info('Starting plugin: ' + __name__)

        configfile = os.path.dirname(os.path.realpath(__file__)) + '/' + __name__ + '.ini'
        pluginconfig = ConfigParser()
        pluginconfig.read(configfile)
        log.info('ini read from: ' + configfile)

        with open("/home/pi/Start/rfid.txt", "r") as f1:
            rfid = f1.read().strip()

        if not rfid:
            print("No card")
            with open("/home/pi/Start/plugin_response.txt", "w") as f2:
                f2.write("No card")
        else:
            temperature = temperaturedata[0]['temperature']
            headers = {
                'User-Agent': 'RaspberryPi/TEMP.py',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            form_data = {'rfid': rfid, 'one': temperature}
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
    retTS = time.time()
    return retTS

def decodetemperature(handle, values):
    data = unpack('<BHxxxxxxI', bytes(values[0:14]))
    retDict = {}
    retDict["valid"] = (data[0] == 0x02)
    retDict["temperature"] = data[1]
    retDict["timestamp"] = sanitize_timestamp(data[2])
    return retDict

def processIndication(handle, values):
    if handle == handle_temperature:
        result = decodetemperature(handle, values)
        if result not in temperaturedata:
            log.info(str(result))
            temperaturedata.append(result)
        else:
            log.info('Duplicate temperaturedata record')
    else:
        log.debug('Unhandled Indication encountered')

def wait_for_device(devname):
    found = False
    while not found:
        try:
            found = adapter.filtered_scan(devname)
        except pygatt.exceptions.BLEError:
            adapter.reset()
    return

def connect_device(address):
    device_connected = False
    tries = 3
    device = None
    while not device_connected and tries > 0:
        try:
            device = adapter.connect(address, 8, addresstype)
            device_connected = True
        except pygatt.exceptions.NotConnectedError:
            tries -= 1
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
config.read('/home/pi/Start/TEMP/TEMPPlugin.ini')

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

plugin = Plugin()  # Instantiate the plugin

while True:
    wait_for_device(device_name)
    device = connect_device(ble_address)
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
                plugin.execute(config, temperaturedatasorted)  # Call execute on the plugin instance directly
