#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

import time
import logging
import binascii
import asyncio
import argparse
import configparser
import sys
import re
import json
from infi.systray import SysTrayIcon

logging.basicConfig(level=logging.INFO)

import pywinusb.hid as hid
from bleak import BleakClient
from bleak import discover

VERSION = "1.2"
PIMAX_USB_VENDOR_ID = 0
LH_DB_FILE = ""
SLEEP_TIME_SEC_USB_FIND = 5
DEBUG_BYPASS_USB = True

BS_CMD_BLE_ID = "0000cb01-0000-1000-8000-00805f9b34fb"
BS_CMD_ID_WAKEUP_NO_TIMEOUT = 0x1200
BS_CMD_ID_WAKEUP_DEFAULT_TIMEOUT = 0x1201
BS_CMD_ID_WAKEUP_TIMEOUT = 0x1202
BS_DEFAULT_ID = 0xffffffff
BS_TIMEOUT_IN_SEC = 30

TRAY_ICON = "pimax.ico"

HS_LABEL = 'HeadSet'
BS1_LABEL = 'BS1'
BS2_LABEL = 'BS2'

hs_status = 'Off'
bs1_snhx = ""
bs2_snhx = ""
bs1_mac = ''
bs2_mac = ''
bs1_status = 'Off'
bs2_status = 'Off'

stations = []
bs_serials = []

quit_main_loop = 0

def find_pimax_headset():
    all_devices = hid.HidDeviceFilter(vendor_id = PIMAX_USB_VENDOR_ID).get_devices()

    if not all_devices:
        logging.debug("USB NOT FOUND")
        return False
    else:
       for device in all_devices:
            try:
                device.open()
                logging.debug("USB FOUND : " + str(device))
            finally:
                device.close()
    return True


def build_bs_ble_cmd(cmd_id, cmd_timeout, cmd_bs_id):
    ba = bytearray()
    ba += cmd_id.to_bytes(2, byteorder='big')
    ba += (cmd_timeout).to_bytes(2, byteorder='big')
    ba += cmd_bs_id.to_bytes(4, byteorder='little')
    ba += (0).to_bytes(12, byteorder='big')
    return ba

async def wake_up_bs(bs_mac_address, loop):
    try:
        async with BleakClient(bs_mac_address, loop=loop) as client:
            cmd = build_bs_ble_cmd(BS_CMD_ID_WAKEUP_DEFAULT_TIMEOUT, 0, BS_DEFAULT_ID)
            logging.debug("WAKE UP CMD : " + str(binascii.hexlify(cmd)))
            await client.write_gatt_char(BS_CMD_BLE_ID, cmd)
    except:
        logging.debug("ERROR DURING WAKE UP BLE : " + str(sys.exc_info()[0]))
        return False
    return True

async def ping_bs(bs_mac_address, bs_unique_id, loop):
    try:
        async with BleakClient(bs_mac_address, loop=loop) as client:
            cmd = build_bs_ble_cmd(BS_CMD_ID_WAKEUP_TIMEOUT, BS_TIMEOUT_IN_SEC, bs_unique_id)
            logging.debug("PING CMD : " + str(binascii.hexlify(cmd)))
            await client.write_gatt_char(BS_CMD_BLE_ID, cmd)
    except:
        logging.debug("ERROR DURING PING BLE : " + str(sys.exc_info()[0]))
        return False
    return True


def is_pimax_headset_present():
    global hs_status
    if not DEBUG_BYPASS_USB:
        if not find_pimax_headset():
            logging.info("Pimax Headset not found.")
            time.sleep(SLEEP_TIME_SEC_USB_FIND)
            hs_status = "Off"
            return False
        else:
            hs_status = "ON"
    else:
        hs_status = "DEBUG"
    return True

def load_configuration():
    config = configparser.ConfigParser()
    config.read('configuration.ini')
    logging.debug("CONFIG : " + config['HeadSet']['USB_VENDOR_ID'])
    global PIMAX_USB_VENDOR_ID
    global LH_DB_FILE
    PIMAX_USB_VENDOR_ID = int(config['HeadSet']['USB_VENDOR_ID'], 0)
    LH_DB_FILE = config['HeadSet']['LH_DB_FILE']
    logging.debug("LH DB FILE : " + LH_DB_FILE)

async def basescan():
    devices = await discover()
    for d in devices:
        bs = re.search("HTC BS", str(d))
        if bs:
            bsmac = re.search(r"(\A\w+:\w+:\w+:\w+:\w+:\w+)", str(d))
            bsid =  re.search(r"HTC BS \w\w(\w\w\w\w)", str(d))
            stations.append(bsmac.group(1) + " " + bsid.group(1))
            logging.info("Found BS: " + bsmac.group(1) + " " + bsid.group(1))

def do_nothing(systray):
    pass

def bs_discovery(systray):
    global bs1_status
    global bs2_status
    global bs1_mac
    global bs2_mac
    global bs1_sn
    global bs2_sn
    global bs1_snhx
    global bs2_snhx
    stations.clear()
    bs_serials.clear()
    bs1_mac = ""
    bs2_mac = ""
    bs1_sn = 0
    bs2_sn = 0
    bs1_snhx = "N/A"
    bs2_snhx = "N/A"
    bs1_status = "Off"
    bs2_status = "Off"
    systray.update(hover_text=tray_label())
    try:
        with open(LH_DB_FILE) as json_file:
            data = json.loads(json_file.read())
            known = data['known_universes']
            try:
                bs1_sn = data['known_universes'][0]['base_stations'][0]['base_serial_number']
                bs1_snhx = hex(bs1_sn)
                logging.info("Found BS1 serial: " + str(bs1_snhx))
            except:
                logging.info("Not Found BS1 serial in DB")
            try:
                bs2_sn = data['known_universes'][0]['base_stations'][1]['base_serial_number']
                bs2_snhx = hex(bs2_sn)
                logging.info("Found BS2 serial: " + str(bs2_snhx))
            except:
                logging.info("Not Found BS2 serial in DB")
        json_file.close()
    except:
        logging.info("Error parsing LightHouse DB JSON file")
        try:
            json_file.close()
        except:
            logging.info("Error closing LightHouse DB JSON file, wrong path?")            
    logging.info("Starting BS discovery...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(basescan())
    logging.info("Found BS: " + str(len(stations)))
    if len(stations) > 0:
        for base in stations:
            base_list = base.split(" ")
            if re.search(r'('+str(bs1_snhx)[-4:].upper()+')$', base_list[1].upper()):
                logging.debug("Found BS1 RE: " + str(bs1_snhx)[-4:].upper() + " in " + base_list[1].upper())
                bs1_mac = base_list[0]
                logging.info("Found BS1: MAC=" + str(bs1_mac) + " ID=" + str(bs1_snhx)[-8:].upper())
                bs1_status = "Discovered"
            if re.search(r'('+str(bs2_snhx)[-4:].upper()+')$', base_list[1].upper()):
                logging.debug("Found BS2 RE: " + str(bs2_snhx)[-4:].upper() + " in " + base_list[1].upper())
                bs2_mac = base_list[0]
                logging.info("Found BS2: MAC=" + str(bs2_mac) + " ID=" + str(bs2_snhx)[-8:].upper())
                bs2_status = "Discovered"
    systray.update(hover_text=tray_label())

def tray_label():
    global hs_status
    global bs1_status
    global bs2_status
    return HS_LABEL + " [" + hs_status + "] " + BS1_LABEL + " [" +str(bs1_snhx)[-4:].upper() + ":" + bs1_status + "] " + BS2_LABEL + " [" + str(bs2_snhx)[-4:].upper() + ":" + bs2_status + "]"

def on_quit_callback(systray):
    global quit_main_loop
    quit_main_loop = 1
    sys.exit()

def main_loop(systray):
            
    try:
        global bs1_status
        global bs2_status
        global quit_main_loop
        while True:
            # Step 0 : Check systray status
            logging.info("Check systray status="+str(quit_main_loop))
            if quit_main_loop == 1:
                break
            # Step 1 : find Pimax Headset
            systray.update(hover_text=tray_label())
            if not is_pimax_headset_present():
                continue
            systray.update(hover_text=tray_label())

            if len(bs1_mac) < 1 and len(bs2_mac) < 1:
                time.sleep(20)
                logging.info("Re-attempt discovery")
                bs_discovery(systray)
                continue

            logging.info("Step 1 : Headset is present.")

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Step 2 : wake up and set default timeout
            if len(bs1_mac) > 0:
                logging.debug("Waking up BS1 MAC=" + bs1_mac)
                if not loop.run_until_complete(wake_up_bs(bs1_mac, loop)):
                    logging.debug("Error in step 2 for BS1")
                    bs1_status = "Wakeup-error"
                    systray.update(hover_text=tray_label())
                    time.sleep(5)
                    if not loop.run_until_complete(wake_up_bs(bs1_mac, loop)):
                        logging.debug("Error in step 2 retry for BS1")
                        bs1_status = "Wakeup-error"
                        systray.update(hover_text=tray_label())
                        time.sleep(5)
                        continue
                    else:
                        bs1_status = "Wakeup"
                        systray.update(hover_text=tray_label())
                else:
                    bs1_status = "Wakeup"
                    systray.update(hover_text=tray_label())
    

            time.sleep(5)

            loop2 = asyncio.new_event_loop()
            asyncio.set_event_loop(loop2)

            if len(bs2_mac) > 0:
                logging.debug("Waking up BS2 MAC=" + bs2_mac)
                if not loop2.run_until_complete(wake_up_bs(bs2_mac, loop2)):
                    logging.debug("Error in step 2 for BS2")
                    time.sleep(5)
                    if not loop2.run_until_complete(wake_up_bs(bs2_mac, loop2)):
                        logging.debug("Error in step 2 retry for BS2")
                        bs2_status = "Wakeup-error"
                        systray.update(hover_text=tray_label())
                        time.sleep(5)
                        continue
                    else:
                        bs2_status = "Wakeup"
                        systray.update(hover_text=tray_label())
                else:
                    bs2_status = "Wakeup"
                    systray.update(hover_text=tray_label())

            logging.info("Step 2 : BS is waking up.... waiting 20 seconds")
            # must wait some time to be fully initialized
            time.sleep(20)

            if not is_pimax_headset_present():
                continue

            logging.info("Step 3 : Enter ping loop.")
            while True:

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                if len(bs1_mac) > 0:
                    logging.debug("Pinging BS1=" + str(bs1_snhx)[-8:].upper())
                    if not loop.run_until_complete(ping_bs(bs1_mac, bs1_sn, loop)):
                        logging.debug("Error in step 3 for BS1: MAC=" + bs1_mac + " ID=" + str(bs1_snhx)[-8:].upper()) 
                        bs1_status = "Ping-error"
                        systray.update(hover_text=tray_label())
                        time.sleep(5)
                        if not loop.run_until_complete(ping_bs(bs1_mac, bs1_sn, loop)):
                            logging.debug("Error in step 3 retry for BS1")
                            bs1_status = "Ping-error"
                            systray.update(hover_text=tray_label())
                            time.sleep(5)
                            break
                        else:
                            bs1_status = "Pinging"
                            systray.update(hover_text=tray_label())
                    else:
                        bs1_status = "Pinging"
                        systray.update(hover_text=tray_label())

                time.sleep(5)

                loop2 = asyncio.new_event_loop()
                asyncio.set_event_loop(loop2)

                if len(bs2_mac) > 0:
                    logging.debug("Pinging BS2=" + str(bs2_snhx)[-8:].upper())
                    if not loop2.run_until_complete(ping_bs(bs2_mac, bs2_sn, loop2)):
                        logging.debug("Error in step 3 for BS2: MAC=" + bs2_mac + " ID=" + str(bs2_snhx)[-8:].upper()) 
                        bs2_status = "Ping-error"
                        systray.update(hover_text=tray_label())
                        time.sleep(5)
                        if not loop2.run_until_complete(ping_bs(bs2_mac, bs2_sn, loop2)):
                            logging.debug("Error in step 3 retry for BS2")
                            bs2_status = "Ping-error"
                            systray.update(hover_text=tray_label())
                            time.sleep(5)
                            break
                        else:
                            bs2_status = "Pinging"
                            systray.update(hover_text=tray_label())
                    else:
                        bs2_status = "Pinging"
                        systray.update(hover_text=tray_label())

                time.sleep(BS_TIMEOUT_IN_SEC/2)

                if not is_pimax_headset_present():
                    break

                # Check systray status
                logging.info("Check systray status="+str(quit_main_loop))
                if quit_main_loop == 1:
                    break
            time.sleep(5)
    except:
        systray.shutdown()
              
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug_ignore_usb", help="Disable the USB search for headset", action="store_true")

    args = parser.parse_args()
    DEBUG_BYPASS_USB = args.debug_ignore_usb

    load_configuration()

    icon = TRAY_ICON
    hover_text = tray_label()

    menu_options = (('Run BaseStation Discovery', None, bs_discovery),
                    ('Version '+VERSION, None, do_nothing)
                    )
    
    with SysTrayIcon(icon, hover_text, menu_options, on_quit=on_quit_callback) as systray:
        bs_discovery(systray)
        main_loop(systray)
        