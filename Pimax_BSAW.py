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

import argparse
import asyncio
import atexit
import binascii
import configparser
import datetime
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime
from datetime import timedelta

import pywinusb.hid as hid
import wx
import wx.lib
import wx.lib.newevent
import wx.lib.colourdb
import wx.dataview as dv
from bleak import BleakClient
from bleak import _logger as logger
from bleak import discover
from infi.systray import SysTrayIcon
from win10toast import ToastNotifier

LogMsgEvent, EVT_LOG_MSG = wx.lib.newevent.NewEvent()


class MainObj:

    def __init__(self):
        """
        Init function will initialize the instance with default runtime values
        :rtype: object
        """
        self.version = "1.5.0"
        self.pimax_usb_vendor_id = 0
        self.lh_db_file = ""
        self.sleep_time_sec_usb_find = 7
        self.debug_logs = False
        self.debug_bypass_usb = False

        self.tray_icon = "pimax.ico"
        self.logformat = "%(asctime)s %(levelname)s (%(module)s): %(message)s"

        self.hs_label = 'HeadSet'
        self.bs1_label = 'BS1'
        self.bs2_label = 'BS2'
        self.bs_timeout_in_sec = 60
        self.bs_disco_sleep = 5

        self.toomanynoted = False
        self.quit_main = False
        self.stations = []
        self.bs_serials = []

        self.systray = None
        self.hsthr = None
        self.bs1thr = None
        self.bs2thr = None
        self.logthr = None
        self.toaster = None

        self.blelock = False
        self.discovery = None
        self.disco = True
        self.mode = "Auto"

        self.panelupdate = "Initializing"
        self.panelstatus = [(0, ("Dashboard", "Status", self.panelupdate)), (1, ("", "", ""))]
        self.paneldata = [[str(k)] + list(v) for k, v in self.panelstatus]

    def set_threads(self, _systray, _hsthr, _bs1thr, _bs2thr, _logthr):
        """
        Set infi.systray, headset thread and basestations threads in main instance
        :type _logthr: object
        :param _bs2thr:
        :param _bs1thr:
        :param _hsthr:
        :type _systray: object
        """
        self.systray = _systray
        self.hsthr = _hsthr
        self.bs1thr = _bs1thr
        self.bs2thr = _bs2thr
        self.logthr = _logthr

    def settoaster(self, _toaster):
        """
        Set toaster object in main instance
        :type _toaster: object
        """
        self.toaster = _toaster

    def get_quit_main(self):
        """
        Return quit main value from main instance
        :return:
        """
        return self.quit_main

    def get_dashboard_except(self):
        self.panelstatus = [(0, ("Dashboard", "Status", self.panelupdate)), (1, ("", "", ""))]
        self.paneldata = [[str(k)] + list(v) for k, v in self.panelstatus]
        return self.paneldata

    def toast_err(self, _msg):
        """
        Function to display the error message as a Windows 10 toast notification
        :param _msg:
        """
        self.toaster.show_toast("PIMAX_BSAW",
                           _msg,
                           icon_path=maininst.tray_icon,
                           duration=5,
                           threaded=True)
        while self.toaster.notification_active(): time.sleep(0.1)

    def load_configuration(self, _toaster):
        """
        Load configuration file
        :param _toaster:
        """
        try:
            config = configparser.ConfigParser()
            config.read('configuration.ini')
            logging.debug("Configuration file Headset USB ID: " + config['HeadSet']['USB_VENDOR_ID'])
            self.pimax_usb_vendor_id = int(config['HeadSet']['USB_VENDOR_ID'], 0)
            conf_bs_timeout_in_sec = int(config['BaseStation']['BS_TIMEOUT_IN_SEC'], 0)
            if 30 <= conf_bs_timeout_in_sec <= 120:
                self.bs_timeout_in_sec = conf_bs_timeout_in_sec
                logging.debug("Configuration file BS timeout: " + config['BaseStation']['bs_timeout_in_sec'])
            self.lh_db_file = config['HeadSet']['LH_DB_FILE']
            logging.debug("Configuration file LightHouse DB filepath: " + self.lh_db_file)
        except Exception as err:
            if not self.quit_main:
                self.toast_err("Load configuration file exception: " + str(err))
                self.quit_main = True

    def setstandby(self):
        """
        Send standby command to both Basestations
        """
        logging.info("Sending Standby to Basestations")
        self.bs1thr.setaction("Standby")
        self.bs2thr.setaction("Standby")

    def setwakeup(self):
        """
        Send wakeup command to both Basestations
        """
        logging.info("Sending Wakeup to Basestations")
        self.bs1thr.setaction("Wakeup")
        self.bs2thr.setaction("Wakeup")

    def setmode(self):
        """
        Send wakeup command to both Basestations
        """
        if self.mode == "Auto":
            _mode = "Idle"
        else:
            _mode = "Auto"
        self.mode = _mode
        logging.info("Set BS mode to " + str(_mode))
        self.bs1thr.setmode(_mode)
        self.bs2thr.setmode(_mode)
        self.mode = _mode


class BaseStations(threading.Thread):

    def __init__(self, label, _maininst, _bs_timeout_in_sec, autostart=False):
        """
        Init function will initialize the thread with default values and store reference to the main instance
        :param label:
        :param _maininst:
        :param _bs_timeout_in_sec:
        :param autostart:
        """
        threading.Thread.__init__(self)
        self.setDaemon(True)
        self.start_orig = self.start
        self.start = self.start_local
        self.lock = threading.Lock()
        self.lock.acquire()  # lock until variables are set
        self.maininst = _maininst
        self.label = label
        self.bs_cmd_verify = True
        self.bs_cmd_ble_id = "0000cb01-0000-1000-8000-00805f9b34fb"
        self.bs_cmd_ble_id_v1 = "0000cb01-0000-1000-8000-00805f9b34fb"
        self.bs_cmd_ble_id_v2 = 0x12
        self.bs_cmd_id_wakeup_v2 = 0x01
        self.bs_cmd_id_sleep_v2 = 0x00
        self.bs_cmd_id_wakeup_no_timeout = 0x1200
        self.bs_cmd_id_wakeup_default_timeout = 0x1201
        self.bs_cmd_id_wakeup_timeout = 0x1202
        self.bs_default_id = 0xffffffff
        self.bs_timeout_in_sec = _bs_timeout_in_sec
        self.bs_loop_sleep = 25
        self.bs_loop_retry = 3
        self.bs_loop_retry_disconnect = 7
        self.bs_disconnects = 0
        self.bs_version = 1
        self.bs_version_force = 0
        self.bs_model = ""
        self.bs_manufacturer = ""
        self.bs_soc = ""
        self.bs_fw = ""
        self.bs_fw2 = ""
        self.status = "N/A"
        self.action = "Off"
        self.tlock = True
        self.islocked = False
        self.ping_cmd = False
        self.wakeup_cmd = False
        self.sn = 0
        self.snhx = ""
        self.snshx = "N/A"
        self.mac = ""
        self.discovered = False
        self.connected = False
        self.paired = False
        self.standby = False
        self.errque = []
        self.toomanysecs = 180
        self.toomanycnt = 20
        self.client = None
        self.test = 0
        self.test2 = 0
        self.mode = "Auto"

        self.loop = asyncio.new_event_loop()
        self.loop.set_debug(maininst.debug_logs)

        self.t_wait_loop = 1
        self.t_last_cmd = time.time()
        self.action = "Wakeup"
        self.state = 0

        if autostart:
            self.start()  # automatically start thread on init

    def run(self):
        """
        Run function called by self.start_orig() will release the lock, run the async function
        :rtype: object
        """
        self.lock.release()
        self.loop.run_until_complete(self.connect_bs(self.loop))

    async def connect_bs(self, _loop):
        """
        Async function what will loop connection to the BS
        :param _loop:
        """

        while True:

            self.state = self.bs_pre_loop()

            prevact = self.action
            nextact = self.action

            if self.state == 9:
                break
            elif self.state == 1:
                continue

            try:
                # not implemented yet
                # def disconnect_bs_cb(_client):
                #    logging.debug(self.label + " disconnected MAC={}".format(_client.address))
                #    self.connected = False
                async with BleakClient(self.mac, loop=_loop) as self.client:
                    # not implemented yet
                    # client.set_disconnected_callback(disconnect_bs_cb)
                    await self.client.connect()
                    if await self.client.is_connected():
                        logging.debug(self.label + " connected")
                        self.connected = True

                        while await self.client.is_connected():

                            self.state = self.bs_pre_loop()

                            self.t_wait_loop = self.bs_loop_sleep

                            if self.state == 9:
                                logging.debug(self.label + " disconnecting")
                                await self.client.disconnect()
                                break
                            elif self.state == 1:
                                continue

                            cmd, prevact, nextact = self.bs_pre_action()

                            self.purgeerrque()

                            try:
                                if len(cmd) < 1:
                                    logging.debug(self.label + " skipping cmd for action=" + prevact + " next=" + nextact)
                                    self.setstatus(prevact)
                                else:
                                    logging.debug(self.label + " sending cmd for action=" + prevact + " next=" + nextact)
                                    while maininst.blelock:
                                        time.sleep(0.2)
                                    maininst.blelock = True
                                    if self.is_version() == 2:
                                        await self.client.write_gatt_char(self.bs_cmd_ble_id, cmd, self.bs_cmd_verify)
                                    else:
                                        await self.client.write_gatt_char(self.bs_cmd_ble_id, cmd, self.bs_cmd_verify)
                                    maininst.blelock = False
                                    if self.is_standby() and prevact == "Standby":
                                        logging.info(self.label + " set Standby done, status Off")
                                        self.standby = False
                                        self.setstatus("Off")
                                    elif self.wakeup_cmd:
                                        logging.debug(self.label + " set Wakeup flag to False")
                                        self.wakeup_cmd = False
                                        self.setstatus(prevact)
                                    else:
                                        self.setstatus(prevact)
                                self.action = nextact
                                self.t_last_cmd = time.time()
                            except Exception as err:
                                connected = await self.client.is_connected()
                                maininst.blelock = False
                                errmsg = self.label + " action: " + self.action + " exception triggered:" + str(err)
                                self.bs_proc_err(connected, prevact, nextact, errmsg)
                                continue
                    else:
                        errmsg = self.label + " while " + self.action + " got disconnected: " + str(
                        self.bs_disconnects)
                        self.bs_proc_err(False, prevact, nextact, errmsg)
                        continue
            except Exception as err:
                errmsg = self.label + " error initiating BLE connection: " + str(err)
                self.bs_proc_err(False, prevact, nextact, errmsg)
                continue

    def bs_proc_err(self, _connected, _prev, _next, _errmsg):
        self.t_last_cmd = time.time()
        self.t_wait_loop = self.bs_loop_retry
        self.action = _prev
        self.setstatus(_prev + "-error")
        logging.debug(_errmsg)
        self.logmanyerrors()
        if not _connected:
            self.connected = False
            self.t_wait_loop = self.bs_loop_retry_disconnect
            self.bs_disconnects += 1

    def bs_pre_loop(self):
        """
        bs_connect pre loop
        :return:
        """

        if len(self.mac) < 1:
            logging.debug(self.label + " not found, skipping keepalive")
            time.sleep(2)
            return 1
        if self.is_standby() and self.is_connected():
            logging.debug(self.label + " go to action, standby requested")
            self.action = "Standby"
            time.sleep(1)
            return 0
        if maininst.get_quit_main():
            logging.debug(self.label + " thread exiting due to quit main, connected=" + str(self.is_connected()))
            return 9
        if maininst.disco:
            logging.debug(self.label + " skipping action due to running discovery")
            time.sleep(2)
            return 1
        if self.tlock:
            logging.debug(self.label + " skipping action due to thread lock")
            time.sleep(2)
            return 1
        if not maininst.hsthr.connected:
            logging.debug(self.label + " skipping action due to HS Off status")
            time.sleep(2)
            return 1
        if self.action == "":
            logging.debug(self.label + " skipping action due to empty action")
            time.sleep(2)
            return 1
        if time.time() - self.t_last_cmd <= self.t_wait_loop:
            #logging.debug(self.label + " skipping action due to timer")
            time.sleep(1)
            return 1
        return 0

    def bs_pre_action(self):

        logging.debug(self.label + " build cmd for action=" + self.action)

        _prev = self.action
        _next = ""
        _exec = self.action

        if self.action[-6:] == "-error":
            _exec = self.action[:-6]
            _next = _exec
        elif self.action == "Standby":
            _exec = "Standby"
            _next = "Off"
        elif self.action == "Off":
            _exec = ""
            _next = ""
        elif self.action == "Wakeup":
            _exec = "Wakeup"
        elif self.wakeup_cmd:
            _exec = "Wakeup"
        elif self.ping_cmd:
            if not self.wakeup_cmd and (time.time() - self.t_last_cmd > self.bs_timeout_in_sec - 5
                                          and not self.ping_cmd):
                _exec = "Wakeup"
            elif self.ping_cmd:
                _exec = "Ping"

        if self.mode == "Auto" and _next == "":
            _next = "Ping"

        if len(_exec) < 1:
            return "", _prev, _next
        else:
            logging.debug(
                self.label + " prebuild_cmd=" + _exec)
            cmd = self.build_bs_ble_cmd(_exec)
            logging.debug(
                self.label + " MAC=" + self.mac + " BLE CMD : " + str(binascii.hexlify(cmd)) +
                " UUID: " + self.bs_cmd_ble_id)
            return cmd, _prev, _next

    def build_bs_ble_cmd(self, action):
        return self.build_2_bs_ble_cmd(action)

    def build_2_bs_ble_cmd(self, action):
        """
        Return the BLE command as bytearray based on input action string
        :rtype: text
        :param action:
        :return:
        """
        if self.is_version() == 2:
            cmd_id = self.bs_cmd_id_wakeup_v2
            if action == "Standby":
                cmd_id = self.bs_cmd_id_sleep_v2
            elif action == "Off":
                cmd_id = self.bs_cmd_id_sleep_v2
            ba = bytearray()
            ba += cmd_id.to_bytes(1, byteorder='big')
            logging.debug(
                self.label + " build2 action:" + action + " MAC=" + self.mac + " BLE CMD : " + str(binascii.hexlify(ba)))
            return ba
        else:
            cmd_id = self.bs_cmd_id_wakeup_default_timeout
            cmd_timeout = self.bs_timeout_in_sec
            cmd_bs_id = self.sn
            if action == "Wakeup":
                cmd_timeout = self.bs_cmd_id_wakeup_timeout
                cmd_bs_id = self.bs_default_id
            elif action == "Standby":
                cmd_id = self.bs_cmd_id_wakeup_timeout
                cmd_timeout = 4
            ba = bytearray()
            ba += cmd_id.to_bytes(2, byteorder='big')
            ba += cmd_timeout.to_bytes(2, byteorder='big')
            ba += cmd_bs_id.to_bytes(4, byteorder='little')
            ba += (0).to_bytes(12, byteorder='big')
            logging.debug(
                self.label + " build2 action:" + action + " MAC=" + self.mac + " BLE CMD : " + str(
                    binascii.hexlify(ba)))
            return ba

    def purgeerrque(self):
        t_now = datetime.now()
        t_delta = t_now - timedelta(seconds=self.toomanysecs)
        for errevt in self.errque:
            if (errevt - t_delta).total_seconds() < 0:
                self.errque.remove(errevt)

    def logmanyerrors(self):
        """
        Store errors timestamp in a list
        Write warning in log if more than self.toomanycnt errors are logged over self.toomanysecs seconds
        :rtype: object
        """
        try:
            t_now = datetime.now()
            self.errque.append(t_now)
            if len(self.errque) >= self.toomanycnt:
                warningmsg = "Too many errors from " + self.label + " (" + str(self.toomanycnt) + " over "\
                             + str(self.toomanysecs)\
                             + " seconds), hints: check distance, re-plug BT dongle or re-pair the BS in Windows!"
                logging.warning(warningmsg)
                if not self.maininst.toomanynoted:
                    self.maininst.toast_err(warningmsg)
                    self.maininst.toomanynoted = True
                self.errque.clear()
        except Exception as err:
            logging.error("Too many errors exception: " + str(err))
            self.maininst.toast_err("Too many errors exception: " + str(err))

    def is_active(self):
        if not self.tlock or self.status == "Off" or len(self.mac) < 1:
            return True
        else:
            return False

    def getlasterrsecs(self):
        if self.errque:
            return str((datetime.now()-self.errque[-1]).seconds)
        else:
            return ""

    def setserial(self, serial):
        """
        Set BS serial number
        :param serial:
        """
        if not int(serial):
            pass
        self.sn = serial
        if self.sn == 0:
            self.mac = ""
            self.snhx = ""
            self.snshx = "N/A"
            self.paired = False
            self.status = "N/A"
            self.mac = ""
        else:
            self.snhx = hex(self.sn)
            self.snshx = hex(self.sn)[-4:].upper()

    def setpairing(self, _mac, _version):
        """
        Set BS pairing
        :param _mac:
        :param _version:
        """
        if not _mac:
            pass
        self.mac = _mac
        if int(_version) == 2:
            self.bs_cmd_ble_id = str(UUID(self.bs_cmd_ble_id_v2))
            self.bs_version = 2
        else:
            self.bs_cmd_ble_id = self.bs_cmd_ble_id_v1
            self.bs_version = 1
        self.setstatus("Discovered")

    def setlock(self, _lock):
        """
        Set thread lock
        :type _lock: object
        """
        self.islocked = False
        self.tlock = _lock

    def setaction(self, _action):
        """
        Set standby flag is the BS is connected
        """
        if _action == "Standby":
            self.setstatus("Standby")
            self.standby = True
        else:
            self.t_last_cmd = time.time() - self.bs_loop_sleep
            self.action = "Wakeup"
            self.standby = False
            self.wakeup_cmd = True

    def setmode(self, _mode):
        self.mode = _mode

    def setstatus(self, _status):
        """
        Set BS status
        :param _status:
        """
        # logging.debug(self.label + " setstatus " + _status)
        if _status == "Discovered":
            self.wakeup_cmd = False
            self.discovered = True
        elif _status == "Wakeup-error":
            self.wakeup_cmd = False
        elif _status == "Ping-error":
            self.ping_cmd = False
        elif _status == "Ping":
            self.ping_cmd = True
        elif _status == "Standby":
            self.standby = True
            self.ping_cmd = False
            self.wakeup_cmd = False
        if self.status != _status:
            if _status == "Discovered":
                logging.info(self.label + " v" + str(self.bs_version) + " via BLE")
            elif _status == "Wakeup-error":
                logging.error(self.label + " error sending Wakeup command")
            elif _status == "Wakeup":
                logging.info(self.label + " success sending Wakeup command")
            elif _status == "Ping-error":
                logging.error(self.label + " error sending Ping command")
            elif _status == "Ping":
                logging.info(self.label + " success sending Ping command")
            elif _status == "Standby":
                logging.debug(self.label + " set status to Standby")
            elif _status == "Off":
                logging.debug(self.label + " set status to Off")
        self.status = _status

    def gettray(self):
        """
        Return string to display in system tray hover text
        :return:
        """
        if self.snshx == "N/A":
            return f"{self.label} [{self.snshx}]"
        return f"{self.label} [{self.snshx}:{self.status}]"

    def getstatus(self):
        """
        Return string with the BS status
        :return:
        """
        return f"{self.status}"

    def getshortsnhx(self):
        """
        Return string with short hex type serial number
        :return:
        """
        return f"{self.snshx}"

    def getmac(self):
        """
        Return string with MAC address
        :return:
        """
        return f"{self.mac}"

    def getserial(self):
        """
        Return string with MAC address
        :return:
        """
        return f"{self.sn}"

    def getsnhx(self):
        """
        Return string with full hex type serial number
        :return:
        """
        return f"{self.snhx}"

    def getversion(self):
        """
        Return string with bs version
        :return:
        """
        return f"{self.bs_version}"

    def is_connected(self):
        """
        Return boolean for BLE connected status
        :return:
        """
        return self.connected

    def is_standby(self):
        """
        Return boolean for go to standby command
        :return:
        """
        return bool(self.standby)

    def is_version(self):
        """
        Return integer for BS version
        :return:
        """
        return int(self.bs_version)

    def start_local(self):
        """
        Start the thread with original run and acquire the lock
        """
        self.start_orig()
        self.lock.acquire()

    def destroy(self):
        """
        Override the destroy thread adding lock release and loop close
        """
        self.lock.release()
        self.loop.close()


class HeadSet(threading.Thread):

    def __init__(self, label, _maininst, autostart=False):
        """
        Init function will initialize the thread with default values and store reference to the main instance
        :param label:
        :param _maininst:
        :param autostart:
        """
        threading.Thread.__init__(self)
        self.setDaemon(True)
        self.start_orig = self.start
        self.start = self.start_local
        self.lock = threading.Lock()
        self.lock.acquire()  # lock until variables are set
        self.maininst = _maininst
        self.label = label
        self.status_initial = "N/A"
        self.status = self.status_initial
        self.tlock = False
        self.islocked = False
        self.connected = False
        self.hs_vendor = ""
        self.hs_product = ""

        if autostart:
            self.start()  # automatically start thread on init

    def run(self):
        """
        Run function what will check Headset connection via USB
        """
        try:
            self.lock.release()

            while True:

                time.sleep(maininst.sleep_time_sec_usb_find)

                if maininst.get_quit_main():
                    logging.debug(self.label + " thread exiting due to quit main")
                    break
                if self.tlock:
                    logging.debug(self.label + " thread lock active")
                    self.islocked = True
                    continue
                if maininst.disco:
                    logging.debug(self.label + " detection paused, discovery running")
                    self.islocked = True
                    continue
                if self.maininst.debug_bypass_usb:
                    self.setstatus("DEBUG")
                    self.islocked = False
                    continue
                self.islocked = False
                all_devices = hid.HidDeviceFilter(vendor_id=self.maininst.pimax_usb_vendor_id).get_devices()
                if not all_devices:
                    logging.debug(self.label + " not found on USB")
                    self.setstatus("Off")
                else:
                    for device in all_devices:
                        try:
                            device.open()
                            self.setstatus("On")
                            logging.debug(self.label + " found on USB: " + str(device))
                            self.hs_vendor = str(device.vendor_name) + " (" + str(device.vendor_id) + ")"
                            self.hs_product = str(device.product_name) + " (" + str(device.product_id) + ")"
                        finally:
                            device.close()

        except Exception as err:
            logging.error("Error: %s in %s thread: %s" % (self.__class__.__name__, self.label, str(err)))

    def setlock(self, _lock):
        """
        Set thread lock
        :param _lock:
        """
        self.islocked = False
        self.tlock = _lock

    def gettray(self):
        """
        Return string to display in system tray hover text
        :return:
        """
        return f"{self.label} [{self.status}]"

    def getstatus(self):
        """
        Return string with Headset status
        :return:
        """
        return f"{self.status}"

    def setstatus(self, _status):
        """
        Set Headset status
        :param _status:
        """
        if _status == "On":
            self.connected = True
        elif _status == "Off":
            self.connected = False
        elif _status == "DEBUG":
            self.connected = True
        if self.status != _status:
            if _status == "On":
                logging.info(self.label + " is active")
                self.maininst.setwakeup()
            elif _status == "Off":
                logging.info(self.label + " is Off")
                if self.status != self.status_initial:
                    self.maininst.setstandby()
            elif _status == "DEBUG":
                logging.info(self.label + " is forced On")
                self.maininst.setwakeup()
        self.status = _status

    def isoff(self):
        """
        Return true if the headset in connected or in debug mode
        :return:
        """
        return bool(self.connected)

    def destroy(self):
        """
        Override the destroy thread adding lock release
        """
        self.lock.release()

    def start_local(self):
        """
        Start the thread with original run and acquire the lock
        """
        self.start_orig()
        self.lock.acquire()


class WxLogHandler(logging.Handler):

    def __init__(self, get_log_dest_func):
        """
        Logging handler to redirect messages to the wxPython window
        :param get_log_dest_func:
        """
        logging.Handler.__init__(self)
        self._get_log_dest_func = get_log_dest_func
        self.level = logging.DEBUG

    def flush(self):
        pass

    def emit(self, record):
        """
        This function will forward the event message to the destination window
        :param record:
        """
        try:
            msg = self.format(record)
            event = LogMsgEvent(message=msg, levelname=record.levelname, levelno=record.levelno)

            log_dest = self._get_log_dest_func()

            def after_func(get_log_dest_func=self._get_log_dest_func, event=event):
                _log_dest = get_log_dest_func()
                if _log_dest:
                    wx.PostEvent(_log_dest, event)

            wx.CallAfter(after_func)

        except Exception as err:
            sys.stderr.write("Error: %s failed while emitting a log record (%s): %s\n" % (
                self.__class__.__name__, repr(record), str(err)))


class LevelFilter(object):
    def __init__(self, level):
        """
        Filter for log level
        :param level:
        """
        self.level = level

    def filter(self, record):
        """
        Filter will forward only records with a level greater or equal self.level
        :type record: object
        """
        return record.levelno >= self.level


class LogWnd(wx.Frame):

    def __init__(self):
        """
        wxPython logging window
        """
        #import wx.lib.inspection
        #wx.lib.inspection.InspectionTool().Show()

        try:
            frame_style = wx.CAPTION
            wx.lib.colourdb.updateColourDB()

            self.wxorange = wx.Colour("ORANGE RED")
            self.wxdarkgreen = wx.Colour("DARK GREEN")

            wx.Frame.__init__(self, None,
                              title="Status panel", style=frame_style | wx.RESIZE_BORDER)

            self.Bind(EVT_LOG_MSG, self.on_log_msg)

            self.Bind(wx.EVT_CLOSE, self.oncloseevt)

            self.SetIcon(wx.Icon("pimax.ico"))

            (self.display_width_, self.display_height_) = wx.GetDisplaySize()

            frame_width = self.display_width_ * 90 / 100
            frame_height = self.display_height_ * 85 / 100
            self.SetSize(wx.Size(frame_width, frame_height))

            panel_width = self.GetClientSize().GetWidth()-2
            panel_height = self.GetClientSize().GetHeight()-46

            status_width = 500
            text_width = panel_width - status_width
            text_height = panel_height
            if text_width < 1:
                text_width = 100

            value_width = panel_width - text_width
            unit_width = value_width/10
            c0_width = int(unit_width*2)
            c1_width = int(unit_width*2)
            if c0_width < 120:
                c0_width = 120
            if c1_width < 120:
                c1_width = 120
            c2_width = int(unit_width*6)
            delta = (c0_width+c1_width+c2_width)-value_width
            if delta > 10:
                c2_width = c2_width - delta
            if c2_width < 260:
                c2_width = 260

            status_width = c0_width + c1_width + c2_width

            self.dvc = dv.DataViewCtrl(self,
                                       style=wx.BORDER_THEME
                                       | dv.DV_ROW_LINES # nice alternating bg colors
                                       #| dv.DV_HORIZ_RULES
                                       | dv.DV_VERT_RULES
                                       | dv.DV_MULTIPLE
                                       | dv.DV_NO_HEADER
                                       , size=(status_width, text_height)
                                       )

            self.model = StatusModel(getpaneldata())

            self.dvc.AssociateModel(self.model)

            c0 = self.dvc.AppendTextColumn("Item " + str(c0_width) + " " + str(value_width),  1, width=c0_width, align=wx.ALIGN_RIGHT, mode=dv.DATAVIEW_CELL_INERT)
            c1 = self.dvc.AppendTextColumn("Characteristic " + str(c1_width),   2, width=c1_width, align=wx.ALIGN_RIGHT, mode=dv.DATAVIEW_CELL_INERT)
            c2 = self.dvc.AppendTextColumn("Value " + str(c2_width-4),   3, width=c2_width-4, align=wx.ALIGN_LEFT, mode=dv.DATAVIEW_CELL_INERT)

            for c in self.dvc.Columns:
                c.Sortable = False
                c.Reorderable = False

            log_font = wx.Font(9, wx.FONTFAMILY_MODERN, wx.NORMAL, wx.FONTWEIGHT_NORMAL)

            panel = wx.Panel(self, wx.ID_ANY)

            style = wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL | wx.TE_RICH2

            self.text = wx.TextCtrl(panel, wx.ID_ANY, size=(text_width, text_height),
                                    style=style)
            self.text.SetFont(log_font)

            sizer = wx.BoxSizer(wx.VERTICAL)
            wbox = wx.BoxSizer(wx.HORIZONTAL)
            hbox = wx.BoxSizer(wx.HORIZONTAL)
            wbox.Add(self.text, 0, wx.ALL | wx.EXPAND | wx.LEFT, 0)
            wbox.Add(self.dvc, 0, wx.ALL | wx.EXPAND | wx.RIGHT, 0)

            self.closebtn = wx.Button(panel, wx.ID_ANY, 'Close')
            self.closebtn.Bind(wx.EVT_BUTTON, self.onclosebutton)
            self.Bind(wx.EVT_BUTTON, self.onclosebutton, self.closebtn)
            self.copybtn = wx.Button(panel, wx.ID_ANY, label="Copy to clipboard")
            self.copybtn.Bind(wx.EVT_BUTTON, self.oncopybutton)
            self.Bind(wx.EVT_BUTTON, self.oncopybutton, self.copybtn)
            self.debugbtn = wx.Button(panel, wx.ID_ANY, label="Headset Debug")
            self.debugbtn.Bind(wx.EVT_BUTTON, self.ondebugbutton)
            self.Bind(wx.EVT_BUTTON, self.ondebugbutton, self.debugbtn)
            self.bsmodebtn = wx.Button(panel, wx.ID_ANY, label="BS Switch mode")
            self.bsmodebtn.Bind(wx.EVT_BUTTON, self.onbsmodebutton)
            self.Bind(wx.EVT_BUTTON, self.onbsmodebutton, self.bsmodebtn)
            self.wakeupbtn = wx.Button(panel, wx.ID_ANY, label="BS Wakeup")
            self.wakeupbtn.Bind(wx.EVT_BUTTON, self.onwakeupbutton)
            self.Bind(wx.EVT_BUTTON, self.onwakeupbutton, self.wakeupbtn)
            self.standbybtn = wx.Button(panel, wx.ID_ANY, label="BS Standby")
            self.standbybtn.Bind(wx.EVT_BUTTON, self.onstandbybutton)
            self.Bind(wx.EVT_BUTTON, self.onstandbybutton, self.standbybtn)
            self.discobtn = wx.Button(panel, wx.ID_ANY, label="Run BS discovery")
            self.discobtn.Bind(wx.EVT_BUTTON, self.ondiscobutton)
            self.Bind(wx.EVT_BUTTON, self.ondiscobutton, self.discobtn)

            hbox.Add(self.copybtn, 1, wx.ALL | wx.ALIGN_CENTER, 5)
            hbox.Add(self.debugbtn, 1, wx.ALL | wx.ALIGN_CENTER, 5)
            hbox.Add(self.bsmodebtn, 1, wx.ALL | wx.ALIGN_CENTER, 5)
            hbox.Add(self.standbybtn, 1, wx.ALL | wx.ALIGN_CENTER, 5)
            hbox.Add(self.wakeupbtn, 1, wx.ALL | wx.ALIGN_CENTER, 5)
            hbox.Add(self.discobtn, 1, wx.ALL | wx.ALIGN_CENTER, 5)
            hbox.Add(self.closebtn, 1, wx.ALL | wx.ALIGN_CENTER, 5)
            sizer.Add(wbox, flag=wx.ALL | wx.EXPAND)
            sizer.Add(hbox, 1, flag=wx.ALL | wx.ALIGN_CENTER, border=5)
            panel.SetSizer(sizer)
            panel.Layout()
            panel.Fit()

            self.CenterOnScreen()
            self.dataObj = None

            self.Raise()

        except Exception as err:
            toast_err("Status panel error: " + str(err))

    def oncloseevt(self, e):
        """
        The close button will hide the window without destroying it to keep the logging messages flowing in
        :param e:
        """
        e.Veto()
        self.Show(False)
        self.Hide()

    def onclosebutton(self, e):
        """
        The close button will hide the window without destroying it to keep the logging messages flowing in
        :param e:
        """
        self.Show(False)
        self.Hide()

    def ondiscobutton(self, e):
        """
        The close button will hide the window without destroying it to keep the logging messages flowing in
        :param e:
        """
        call_bs_discovery(maininst.systray)

    def oncopybutton(self, e):
        """
        The copy button will fill the clipboard with the logging messages in the window
        :param e:
        """
        self.dataObj = wx.TextDataObject()
        self.dataObj.SetText(self.text.GetValue())
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(self.dataObj)
            wx.TheClipboard.Close()
        else:
            wx.MessageBox("Unable to open the clipboard", "Error")

    def ondebugbutton(self, e):
        if maininst.debug_bypass_usb:
            maininst.debug_bypass_usb = False
            self.debugbtn.SetLabel("Headset Debug")
        else:
            maininst.debug_bypass_usb = True
            self.debugbtn.SetLabel("Headset Auto")

    def onwakeupbutton(self, e):
        maininst.setwakeup()

    def onstandbybutton(self, e):
        maininst.setstandby()

    def onbsmodebutton(self, e):
        maininst.setmode()

    def on_log_msg(self, e):
        """
        This function is triggered by the bind for the EVT_LOG_MSG event.
        Autoscroll is enabled if vertical scrollbar is near the bottom
        :param e:
        """
        try:
            msg = re.sub("\r\n?", "\n", e.message)

            if e.levelno >= 40:
                self.text.SetDefaultStyle(wx.TextAttr(wx.RED))
            elif e.levelno >= 30:
                self.text.SetDefaultStyle(wx.TextAttr(self.wxorange))
            elif e.levelno >= 20:
                self.text.SetDefaultStyle(wx.TextAttr(wx.BLACK))
            elif e.levelno >= 10:
                self.text.SetDefaultStyle(wx.TextAttr(self.wxdarkgreen))

            # msg = msg + " sc=" + str(self.text.GetScrollPos(wx.VERTICAL))

            sbrng = self.text.GetScrollRange(wx.VERTICAL)
            sbpos = self.text.GetScrollPos(wx.VERTICAL)+self.text.GetVirtualSize().GetHeight()
            sboldpos = self.text.GetScrollPos(wx.VERTICAL)

            current_pos = self.text.GetInsertionPoint()
            end_pos = self.text.GetLastPosition()

            # autoscroll = (current_pos == end_pos)

            if sbrng-sbpos <= 10:
                # msg = msg + " YESASB"
                reposition = False
                autoscroll = True
            else:
                current_pos = self.text.GetScrollPos(wx.VERTICAL)
                # msg = msg + " NOASB"
                reposition = True
                autoscroll = False

            # msg = msg + " sbrng=" + str(sbrng) + " sbpos=" + str(sbpos) + " cur=" + str(current_pos) + " end=" + str(
            #    end_pos)

            if autoscroll:
                # msg = msg + " YESA"
                self.text.AppendText("%s\n" % msg)
                if reposition:
                    self.text.SetScrollPos(wx.VERTICAL, self.text.GetScrollRange(wx.VERTICAL), True)
            else:
                # msg = msg + " NOA"
                self.text.Freeze()
                (selection_start, selection_end) = self.text.GetSelection()
                self.text.SetEditable(True)
                self.text.SetInsertionPoint(end_pos)
                self.text.WriteText("%s\n" % msg)
                self.text.SetEditable(False)
                self.text.SetInsertionPoint(current_pos)
                self.text.SetSelection(selection_start, selection_end)
                self.text.Thaw()
                if reposition:
                    self.text.SetScrollPos(wx.VERTICAL, sboldpos, True)
                else:
                    self.text.SetScrollPos(wx.VERTICAL, self.text.GetScrollRange(wx.VERTICAL), True)
                #self.text.Refresh()

        except Exception as err:
            sys.stderr.write(
                "Error: %s failed while responding to a log message: %s.\n" % (self.__class__.__name__, str(err)))

        if e is not None:
            e.Skip(True)


class StatusModel(dv.DataViewIndexListModel):
    def __init__(self, data):
        dv.DataViewIndexListModel.__init__(self, len(data))
        self.wxgray = wx.Colour(47, 79, 79)
        self.data = data

    def GetColumnType(self, col):
        return "string"

    # This method is called to provide the data object for a
    # particular row,col
    def GetValueByRow(self, row, col):
        return self.data[row][col]

    # Report how many columns this model provides data for.
    def GetColumnCount(self):
        return len(self.data[0])

    # Report the number of rows in the model
    def GetCount(self):
        return len(self.data)

    # Called to check if non-standard attributes should be used in the
    # cell at (row, col)
    def GetAttrByRow(self, row, col, attr):
        if col == 1:
            attr.SetColour(self.wxgray)
            attr.SetBold(True)
            attr.SetItalic(True)
            return True
        if col == 3:
            attr.SetColour('blue')
            attr.SetBold(True)
            return True
        return False

    def AddRow(self, value):
        # update data structure
        self.data.append(value)
        # notify views
        self.RowAppended()


class LogThread(threading.Thread):

    def __init__(self, autostart=True):
        """
        Run the log window in a thread.
        Access the frame with self.frame

        :type autostart: object
        """
        threading.Thread.__init__(self)
        self.setDaemon(True)
        self.start_orig = self.start
        self.start = self.start_local
        self.frame = None  # to be defined in self.run
        self.framepnl = None
        self.status = ""
        self.lock = threading.Lock()
        self.lock.acquire()  # lock until variables are set

        if autostart:
            self.start()  # automatically start thread on init

    def run(self):
        """
        Initialize the frame with with the wxPython class and run the window MainLoop
        """
        import wx
        atexit.register(disable_asserts)

        app = wx.App(False)

        frame = LogWnd()

        # define frame and release lock
        self.frame = frame
        self.lock.release()

        app.MainLoop()

    def destroy(self):
        """
         Override the destroy adding frame destroy first
        """
        self.frame.Destroy()

    def start_local(self):
        """
        Start the thread with original run and acquire the lock
        """
        self.start_orig()
        self.lock.acquire()


class UUID:
    def __init__(self, val, common_name=None):
        '''We accept: 32-digit hex strings, with and without '-' characters,
           4 to 8 digit hex strings, and integers'''
        if isinstance(val, int):
            if (val < 0) or (val > 0xFFFFFFFF):
                raise ValueError(
                    "Short form UUIDs must be in range 0..0xFFFFFFFF")
            val = "%04X" % val
        elif isinstance(val, self.__class__):
            val = str(val)
        else:
            val = str(val)  # Do our best

        val = val.replace("-", "")
        if len(val) <= 8:  # Short form
            val = ("0" * (8 - len(val))) + val + "00001000800000805F9B34FB"

        self.binVal = binascii.a2b_hex(val.encode('utf-8'))
        if len(self.binVal) != 16:
            raise ValueError(
                "UUID must be 16 bytes, got '%s' (len=%d)" % (val,
                                                              len(self.binVal)))
        self.commonName = common_name

    def __str__(self):
        s = binascii.b2a_hex(self.binVal).decode('utf-8')
        return "-".join([s[0:8], s[8:12], s[12:16], s[16:20], s[20:32]])

    def __eq__(self, other):
        return self.binVal == UUID(other).binVal

    def __hash__(self):
        return hash(self.binVal)

    def getCommonName(self):
        s = str(self)
        if s.endswith("-0000-1000-8000-00805f9b34fb"):
            s = s[0:8]
            if s.startswith("0000"):
                s = s[4:]
        return s


def runlogthread():
    """
    Run the Logging window thread and makes the frame accessible
    :return:
    """
    lt = LogThread()  # run wx MainLoop as thread
    #frame = lt.frame  # access to wx Frame
    lt.frame.Show(False)
    return lt


def consolewin(systray):
    """
    Function for the system tray menu to show the Logging window
    :param systray:
"""
    try:
        maininst.logthr.frame.Show(True)
        maininst.logthr.frame.Raise()
    except Exception as err:
        maininst.logthr = runlogthread()
        maininst.logthr.frame.Show(True)
        maininst.logthr.frame.Raise()
        toast_err("ex=" + str(err))


def disable_asserts():
    """
    Disable wxPython error messages when destroying the windows
    """
    import wx
    wx.DisableAsserts()


async def basescan():
    """
    Async function which runs the BLE discovery
    """
    try:
        devices = await discover(timeout=10)
        for d in devices:
            bs = re.search("HTC BS", str(d))
            bs2 = re.search("LHB-", str(d))
            found = False
            if bs:
                _bsmac = re.search(r"(\A\w+:\w+:\w+:\w+:\w+:\w+)", str(d))
                _bsid = re.search(r"HTC BS \w\w(\w\w\w\w)", str(d))
                bsmac = _bsmac.group(1)
                bsid = _bsid.group(1)
                if any(str(macs[:17]).upper() == str(bsmac).upper() in macs for macs in maininst.stations):
                    logging.debug("Skipping BS v1 already discovered: " + bsmac + " " + bsid)
                else:
                    maininst.stations.append(bsmac + " " + bsid + " 1")
                    logging.info("Found BS v1 via BLE Scan: " + bsmac + " " + bsid)
            elif bs2:
                _bsmac = re.search(r"(\A\w+:\w+:\w+:\w+:\w+:\w+)", str(d))
                _bsid = re.search(r"LHB-\w\w\w\w(\w\w\w\w)", str(d))
                bsmac = _bsmac.group(1)
                bsid = _bsid.group(1)
                if any(str(macs[:17]).upper() == str(bsmac).upper() in macs for macs in maininst.stations):
                    logging.debug("Found BS v2 already discovered, skip: " + bsmac + " " + bsid)
                else:
                    maininst.stations.append(bsmac + " " + bsid + " 2")
                    logging.info("Found BS v2 via BLE Scan: " + bsmac + " " + bsid)
    except Exception as err:
        logging.debug("BLE scan exception")
        toast_err("Discovery scan exception: " + str(err))


async def getsvcs(_bsthr, _loop):
    """
    Async function which runs the get services and dump in debug logs
    """
    try:
        async with BleakClient(_bsthr.mac, loop=_loop) as client:
            logging.debug(_bsthr.label + " DEBUG Get services: " + str(_bsthr.mac))
            x = await client.is_connected()
            logging.debug(_bsthr.label + " Connected: {0}".format(x))
            for service in client.services:
                logging.debug(_bsthr.label + "[Service] {0}: {1}".format(service.uuid, service.description))
                if service.uuid == "0000fe59-0000-1000-8000-00805f9b34fb":
                    _bsthr.bs_soc = str(service.description)
                for char in service.characteristics:
                    if "read" in char.properties:
                        try:
                            value = bytes(await client.read_gatt_char(char.uuid))
                            if _bsthr.bs_version == 2:
                                if char.uuid == "00002a00-0000-1000-8000-00805f9b34fb":
                                    _bsthr.bs_model = str(value.decode("utf-8"))
                                if char.uuid == "00002a29-0000-1000-8000-00805f9b34fb":
                                    _bsthr.bs_manufacturer = str(value.decode("utf-8"))
                                if char.uuid == "00002a24-0000-1000-8000-00805f9b34fb":
                                    _bsthr.bs_fw = str(value.decode("utf-8"))
                                if char.uuid == "00002a25-0000-1000-8000-00805f9b34fb":
                                    _bsthr.bs_fw2 = str(value.decode("utf-8"))
                            else:
                                if char.uuid == "00002a00-0000-1000-8000-00805f9b34fb":
                                    _bsthr.bs_model = str(value.decode("utf-8"))
                                if char.uuid == "00002a23-0000-1000-8000-00805f9b34fb":
                                    _bsthr.bs_manufacturer = str(value.decode("utf-8"))
                                if char.uuid == "00002a29-0000-1000-8000-00805f9b34fb":
                                    _bsthr.bs_soc = str(value.decode("utf-8"))
                                if char.uuid == "00002a24-0000-1000-8000-00805f9b34fb":
                                    _bsthr.bs_fw = str(value.decode("utf-8"))
                        except Exception as e:
                            value = str(e).encode()
                    else:
                        value = None
                    logging.debug(_bsthr.label +
                        " \t[Characteristic] {0}: ({1}) | Name: {2}, Value: {3} ".format(
                            char.uuid, ",".join(char.properties), char.description, value
                        )
                    )
                    for descriptor in char.descriptors:
                        value = await client.read_gatt_descriptor(descriptor.handle)
                        logging.debug(_bsthr.label +
                            "\t\t[Descriptor] {0}: (Handle: {1}) | Value: {2} ".format(
                                descriptor.uuid, descriptor.handle, bytes(value)
                            )
                        )
    except Exception as err:
        logging.debug(_bsthr.label + "BLE Getsvcs exception:" + str(err))
        pass


def do_nothing(systray):
    """
    Function for the system tray menu to act as stub for nothing to do
    :param systray:
    """
    pass


def call_bs_discovery(systray):
    """
    Run the bs_discovery function in its own thread
    :rtype: object
    """
    try:
        if not maininst.discovery.is_alive():
            maininst.discovery = threading.Thread(target=bs_discovery, args=(systray,))
            maininst.discovery.start()
    except Exception as err:
        logging.debug("Exception on call bs_discovery: " + str(err))
        maininst.discovery = threading.Thread(target=bs_discovery, args=(systray,))
        maininst.discovery.start()
    #bs_discovery(systray)


def bs_discovery(systray):
    """
    Function for the system tray menu to trigger a new BS discovery
    The serial numbers are loaded from the Lighthouse DB and then a BLE discovery is run
    :param systray:
    :return:
    """

    def addbs(_thisbs, _base):
        _base_list = base.split(" ")
        logging.debug("Found " + _thisbs.label + " RE: " + _thisbs.getshortsnhx() + " in " + _base_list[1].upper())
        if _thisbs.bs_version_force > 0:
            _thisbs.setpairing(base_list[0], _thisbs.bs_version_force)
        else:
            _thisbs.setpairing(_base_list[0], int(_base_list[2]))
        logging.info("Found " + _thisbs.label + ": v" + str(_thisbs.bs_version) + " MAC=" + str(
            _thisbs.mac) + " ID=" + _thisbs.getsnhx())
        while maininst.blelock:
            time.sleep(0.2)
        maininst.blelock = True
        try:
            scanloop.run_until_complete(getsvcs(_thisbs, scanloop))
        except Exception as err:
            logging.debug(_thisbs.label + " Gesvsc failed: " + str(err))
            pass
        maininst.blelock = False

    try:
        maininst.disco = True
        bs_paired = 0
        logging.info("Starting Basestations discovery")

        maininst.stations.clear()
        maininst.bs_serials.clear()
        maininst.bs1thr.setlock(True)
        maininst.bs2thr.setlock(True)

        logging.debug("Reset serials")

        maininst.bs1thr.setserial(0)
        maininst.bs2thr.setserial(0)

        logging.debug("Going to read the LH DB file")

        try:
            with open(maininst.lh_db_file) as json_file:
                data = json.loads(json_file.read())
                # known = data['known_universes']
                try:
                    maininst.bs1thr.setserial(data['known_universes'][0]['base_stations'][0]['base_serial_number'])
                    logging.info("Found BS1 serial in DB: " + maininst.bs1thr.getsnhx())
                    bs_paired += 1
                except Exception:
                    logging.info("Not Found BS1 serial in DB")
                try:
                    maininst.bs2thr.setserial(data['known_universes'][0]['base_stations'][1]['base_serial_number'])
                    logging.info("Found BS2 serial in DB: " + maininst.bs2thr.getsnhx())
                    bs_paired += 1
                except Exception:
                    logging.info("Not Found BS2 serial in DB")
            json_file.close()
        except Exception as err:
            logging.error("Error parsing LightHouse DB JSON file: " + str(err))
            toast_err("Error parsing LightHouse DB JSON file: " + str(err))
            try:
                json_file.close()
            except Exception:
                logging.error("Error closing LightHouse DB JSON file, wrong path?")
                toast_err("Error closing LightHouse DB JSON file, wrong path?")
        if bs_paired == 0:
            logging.error("Use Pitool to pair at least one Basestation with the Headset")
            toast_err("Use Pitool to pair at least one Basestation with the Headset")
            return
        logging.debug("Starting BLE discovery...")
        try:
            scanloop = asyncio.new_event_loop()
            scanloop.set_debug(False)
            while maininst.blelock:
                time.sleep(0.2)
            maininst.blelock = True
            disco_retries = 0
            while len(maininst.stations) < bs_paired:
                disco_retries += 1
                logging.info("BLE Discovery scan number: " + str(disco_retries))
                scanloop.run_until_complete(basescan())
                time.sleep(4)
                if disco_retries > 19:
                    err_msg = "Couldn't find all Basestations, found " + str(
                        len(maininst.stations)) + " expected " + str(bs_paired)
                    logging.info(err_msg)
                    toast_err(err_msg)
                    break
            maininst.blelock = False
            logging.info("Found BS count via BLE Discovery: " + str(len(maininst.stations)))
            if len(maininst.stations) > 0:
                for base in maininst.stations:
                    base_list = base.split(" ")
                    if re.search(r'(' + maininst.bs1thr.getshortsnhx() + ')$', base_list[1].upper()):
                        addbs(maininst.bs1thr, base)
                    if re.search(r'(' + maininst.bs2thr.getshortsnhx() + ')$', base_list[1].upper()):
                        addbs(maininst.bs2thr, base)
        except Exception as err:
            maininst.blelock = False
            maininst.disco = False
            logging.error("BLE discovery exception: " + str(err))
            toast_err("BLE Discovery exception: " + str(err))
        time.sleep(maininst.bs_disco_sleep)
        maininst.disco = False
        maininst.bs1thr.setlock(False)
        time.sleep(1)
        maininst.bs2thr.setlock(False)
        logging.info("Basestations discovery done")
    except Exception as err:
        maininst.disco = False
        maininst.blelock = False
        logging.error("Main discovery exception: " + str(err))
        toast_err("Main discovery exception: " + str(err))


def on_quit_callback(systray):
    """
    Function for the system tray menu to set the quit main loop and trigger the program shutdown
    :param systray:
    """
    if maininst.bs1thr or maininst.bs2thr:
        maininst.setstandby()
    maininst.quit_main = True


def updatepaneldata():
    # self.status = {("ciao", "mondo"), ("ecco", "mano")}
    # self.data = [[str(k)] + list(v) for k, v in self.status]

    try:
        while True:
            if maininst.get_quit_main():
                break
            time.sleep(1)
            if logthr.frame.IsShown():

                idx = 0
                status = {}

                def addstatus( r1, r2 , r3, status, idx):
                    nstatus = {}
                    nstatus[idx] = r1, r2, r3
                    status.update(nstatus)
                    idx += 1
                    return idx

                def addstatusbs(thisbs, status, idx):
                    idx = addstatus("Basestation " + thisbs.label, "", "", status, idx)
                    idx = addstatus("", "Status", str(thisbs.getstatus()), status, idx)
                    idx = addstatus("", "Mode", str(thisbs.mode), status, idx)
                    if len(thisbs.getserial()) > 0:
                        idx = addstatus("", "Serial Hex", str(thisbs.getsnhx()).upper()[-8:], status, idx)
                        idx = addstatus("", "Serial Integer", str(thisbs.getserial()), status, idx)
                    if len(thisbs.getmac()) > 0:
                        idx = addstatus("", "Connected", str(thisbs.is_connected()), status, idx)
                        idx = addstatus("", "Version", "v" + str(thisbs.bs_version), status, idx)
                        idx = addstatus("", "MAC", str(thisbs.getmac()), status, idx)
                        idx = addstatus("", "Disconnections", str(thisbs.bs_disconnects), status, idx)
                        idx = addstatus("", "Last errors", str(len(thisbs.errque)) + " in " + str(thisbs.toomanysecs)
                                        + " seconds", status, idx)
                        if len(thisbs.getlasterrsecs()) > 0:
                            idx = addstatus("", "Last error", str(thisbs.getlasterrsecs()) + " seconds ago", status, idx)
                        if len(thisbs.bs_model) > 0:
                            idx = addstatus("", "Model", str(thisbs.bs_model), status, idx)
                        if len(thisbs.bs_manufacturer) > 0:
                            idx = addstatus("", "Manufacturer", str(thisbs.bs_manufacturer), status, idx)
                        if len(thisbs.bs_soc) > 0:
                            idx = addstatus("", "Chipset", str(thisbs.bs_soc), status, idx)
                        if len(thisbs.bs_fw) > 0:
                            idx = addstatus("", "Firmware", str(thisbs.bs_fw), status, idx)
                        if len(thisbs.bs_fw2) > 0:
                            idx = addstatus("", "", str(thisbs.bs_fw2), status, idx)
                    return idx

                idx = addstatus("Dashboard", "Status", maininst.panelupdate, status, idx)
                idx = addstatus("", "", "", status, idx)
                idx = addstatus("Headset", "", "", status, idx)
                idx = addstatus("", "Status", str(maininst.hsthr.getstatus()), status, idx)
                if len(maininst.hsthr.hs_vendor) > 0:
                    idx = addstatus("", "Vendor", str(maininst.hsthr.hs_vendor), status, idx)
                if len(maininst.hsthr.hs_product) > 0:
                    idx = addstatus("", "Product", str(maininst.hsthr.hs_product), status, idx)
                idx = addstatusbs(maininst.bs1thr, status, idx)
                idx = addstatusbs(maininst.bs2thr, status, idx)
                maininst.panelstatus = status
                try:
                    status = sorted(status.items())
                    maininst.paneldata = [[str(k)] + list(v) for k, v in status]
                    #time.sleep(0.2)
                    logthr.frame.model = StatusModel(maininst.paneldata)
                    logthr.frame.dvc.AssociateModel(logthr.frame.model)
                    #time.sleep(0.2)
                    maininst.panelupdate = "Updating"
                    logthr.frame.dvc.Refresh()
                    #logging.debug("Panel update=" + str(status))
                except Exception as err:
                    if not maininst.quit_main:
                        toast_err("Update panel inner thread exception: " + str(err))
                        logging.debug("Panel inner closed: " + str(err))
                        maininst.panelupdate = "Error"
                        logthr.frame.model = StatusModel(maininst.get_dashboard_except())
                        logthr.frame.dvc.AssociateModel(logthr.frame.model)
                        #logthr.frame.dvc.Refresh()
                    pass
    except Exception as err:
        if not maininst.quit_main:
            logging.debug("Panel inner exception: " + str(err))
            toast_err("Update panel thread exception: " + str(err))
            maininst.panelupdate = "Error"
            logthr.frame.model = StatusModel(maininst.get_dashboard_except())
            logthr.frame.dvc.AssociateModel(logthr.frame.model)
            #logthr.frame.dvc.Refresh()


def getpaneldata():
    return maininst.paneldata

def toast_err(_msg):
    """
    Function to display the error message as a Windows 10 toast notification
    :param _msg:
    """
    toaster.show_toast("PIMAX_BSAW",
                       _msg,
                       icon_path=maininst.tray_icon,
                       duration=5,
                       threaded=True)
    while toaster.notification_active():
        time.sleep(0.1)


def main(_logger):
    """
    Main loop for the program
    :param _logger:
    """
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--debug_ignore_usb", help="Disable the USB search for headset", action="store_true")
        parser.add_argument("--debug_logs", help="Enable DEBUG level logs", action="store_true")
        parser.add_argument("--version", help="Print version", action="store_true")

        args = parser.parse_args()

        maininst.debug_bypass_usb = args.debug_ignore_usb
        maininst.debug_logs = args.debug_logs

        if args.version:
            toast_err("Version: " + str(maininst.version))
            sys.exit()

        if maininst.debug_logs:
            maininst.MIN_LEVEL = logging.DEBUG
            os.environ["BLEAK_LOGGING"] = "True"
        else:
            maininst.MIN_LEVEL = logging.INFO
            os.environ["BLEAK_LOGGING"] = "False"

        logging.basicConfig(format=maininst.logformat, level=maininst.MIN_LEVEL)
        log_formatter = logging.Formatter("%(asctime)s %(levelname)s (%(module)s): %(message)s", "%H:%M:%S")
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(log_formatter)
        h.setLevel(maininst.MIN_LEVEL)

        wx_handler = WxLogHandler(lambda: logthr.frame)
        wx_handler.setFormatter(log_formatter)
        wx_handler.setLevel(maininst.MIN_LEVEL)
        wx_handler.addFilter(LevelFilter(maininst.MIN_LEVEL))
        logging.getLogger().addHandler(wx_handler)

        _logger.addHandler(h)
        _logger = logging.getLogger(__name__)

        menu_options = (('Run BaseStation Discovery', None, call_bs_discovery),
                        ('Status panel', None, consolewin),
                        ('Version ' + maininst.version, None, do_nothing)
                        )

        with SysTrayIcon(maininst.tray_icon, "Initializing...", menu_options, on_quit=on_quit_callback) as systray:
            try:
                logging.info("Pimax_BSAW Version: " + maininst.version)
                maininst.settoaster(toaster)
                maininst.load_configuration(toaster)
                if maininst.get_quit_main():
                    raise Exception("Exiting due to configuration file load error")
                logging.info("Configuration loaded")

                bs1thr = BaseStations(maininst.bs1_label, maininst, maininst.bs_timeout_in_sec)
                bs2thr = BaseStations(maininst.bs2_label, maininst, maininst.bs_timeout_in_sec)
                hsthr = HeadSet(maininst.hs_label, maininst)
                maininst.set_threads(systray, hsthr, bs1thr, bs2thr, logthr)
                logging.debug("Threads initialized")

                tray_label = hsthr.gettray() + " " + bs1thr.gettray() + " " + bs2thr.gettray()
                systray.update(hover_text=tray_label)

                hsthr.start()

                maininst.discovery = threading.Thread(target=bs_discovery, args=(systray,))
                maininst.discovery.start()
                maininst.discovery.join()

                time.sleep(3)

                logging.debug("Starting threads")
                bs1thr.start()
                time.sleep(1)
                bs2thr.start()
                logging.debug("Threads started")

                updatethr = threading.Thread(target=updatepaneldata, args=())
                updatethr.start()

                while True:
                    if maininst.quit_main:
                        logging.debug("Quit main_loop, waiting for threads exiting")
                        timeref = time.time()
                        while hsthr.is_alive() or bs1thr.is_alive() or bs2thr.is_alive():
                            time.sleep(0.1)
                            if time.time() - timeref > 5:
                                break
                        logging.debug("Quit main_loop, systray status=" + str(maininst.quit_main))
                        break

                    tray_label = hsthr.gettray() + " " + bs1thr.gettray() + " " + bs2thr.gettray()
                    systray.update(hover_text=tray_label)

                    if not hsthr.is_alive():
                        raise Exception(hsthr.label + " thread has crashed!")
                    if not bs1thr.is_alive():
                        raise Exception(bs1thr.label + " thread has crashed!")
                    if not bs2thr.is_alive():
                        raise Exception(bs1thr.label + " thread has crashed!")

                    time.sleep(1)

            except Exception as err:
                if not maininst.quit_main:
                    toast_err("Main thread loop exception: " + str(err))
                systray.shutdown()
                sys.exit()

    except Exception as err:
        if not maininst.quit_main:
            toast_err("Main thread exception: " + str(err))
        systray.shutdown()
        sys.exit()


if __name__ == "__main__":
    toaster = ToastNotifier()
    maininst = MainObj()
    logthr = runlogthread()
    main(logger)
