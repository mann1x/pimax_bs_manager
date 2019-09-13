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
import os
import wx
import wx.lib
import wx.lib.newevent
import threading
import atexit

from infi.systray import SysTrayIcon

import pywinusb.hid as hid
from bleak import BleakClient
from bleak import discover
from bleak import _logger as logger

VERSION = "1.3"
PIMAX_USB_VENDOR_ID = 0
LH_DB_FILE = ""
SLEEP_TIME_SEC_USB_FIND = 5
DEBUG_BYPASS_USB = True

BS_CMD_BLE_ID = "0000cb01-0000-1000-8000-00805f9b34fb"
BS_CMD_ID_WAKEUP_NO_TIMEOUT = 0x1200
BS_CMD_ID_WAKEUP_DEFAULT_TIMEOUT = 0x1201
BS_CMD_ID_WAKEUP_TIMEOUT = 0x1202
BS_DEFAULT_ID = 0xffffffff
BS_TIMEOUT_IN_SEC = 60
BS_LOOP_SLEEP = 20
BS_LOOP_RETRY = 3

TRAY_ICON = "pimax.ico"

HS_LABEL = 'HeadSet'
BS1_LABEL = 'BS1'
BS2_LABEL = 'BS2'

hs_status = 'Searching'
bs1_snhx = ""
bs2_snhx = ""
bs1_mac = ''
bs2_mac = ''
bs1_status = 'Off'
bs2_status = 'Off'

hs_tlock = True
bs1_tlock = True
bs1_tlock = True
disco_tlock = True
bs1_wakeup_cmd = False
bs2_wakeup_cmd = False

stations = []
bs_serials = []

quit_main_loop = False

LogMsgEvent, EVT_LOG_MSG = wx.lib.newevent.NewEvent()

class wxLogHandler(logging.Handler):

    def __init__(self, get_log_dest_func):
        logging.Handler.__init__(self)
        self._get_log_dest_func = get_log_dest_func
        self.level = logging.DEBUG

    def flush(self):
        pass

    def emit(self, record):
        try:
            msg = self.format(record)
            event = LogMsgEvent(message=msg,levelname=record.levelname)
            
            log_dest = self._get_log_dest_func()
            
            def after_func(get_log_dest_func=self._get_log_dest_func, event=event):
                log_dest = get_log_dest_func()
                if (log_dest):
                    wx.PostEvent(log_dest, event)

            wx.CallAfter(after_func)

        except (Exception) as err:
            sys.stderr.write("Error: %s failed while emitting a log record (%s): %s\n" % (self.__class__.__name__, repr(record), str(err)))

class LogWnd(wx.Frame):
 
    def __init__(self):
        no_sys_menu = wx.CAPTION
        wx.Frame.__init__(self, None, 
                          title="Console Log", style=no_sys_menu|wx.RESIZE_BORDER)

        self.Bind(EVT_LOG_MSG, self.on_log_msg)
        
        self.SetIcon(wx.Icon("pimax.ico"))

        (self.display_length_, self.display_height_) = wx.GetDisplaySize()
       
        self.SetSize(wx.Size(self.display_length_ * 70 / 100,self.display_height_ * 70 / 100))

        log_font = wx.Font(9, wx.FONTFAMILY_MODERN, wx.NORMAL, wx.FONTWEIGHT_NORMAL)

        panel = wx.Panel(self, wx.ID_ANY)
        style = wx.TE_MULTILINE|wx.TE_READONLY|wx.HSCROLL|wx.TE_RICH2
        self.text = wx.TextCtrl(panel, wx.ID_ANY, size=(400,250),
                          style=style)
        self.text.SetFont(log_font) 

        closeBtn = wx.Button(panel, wx.ID_ANY, 'Close')
        self.Bind(wx.EVT_BUTTON, self.onCloseButton, closeBtn)
        copyBtn = wx.Button(panel, wx.ID_ANY, label="Copy to clipboard")     
        copyBtn.Bind(wx.EVT_BUTTON, self.onCopyButton)
        self.Bind(wx.EVT_BUTTON, self.onCopyButton, copyBtn)

        sizer = wx.BoxSizer(wx.VERTICAL)
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.text, 1, wx.ALL|wx.EXPAND, 5)
        hbox.Add(copyBtn, 0, wx.ALL|wx.CENTER, 5)
        hbox.Add(closeBtn, 0, wx.ALL|wx.CENTER, 5)
        sizer.Add(hbox, flag=wx.ALL|wx.CENTER, border=10)
        panel.SetSizer(sizer)

    def onCloseButton(self, e):
        self.Show(False)

    def onCopyButton(self, e):
        self.dataObj = wx.TextDataObject()
        self.dataObj.SetText(self.text.GetValue())
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(self.dataObj)
            wx.TheClipboard.Close()
        else:
            wx.MessageBox("Unable to open the clipboard", "Error")
       
    def on_log_msg(self, e):
        try:
            msg = re.sub("\r\n?", "\n", e.message)

            current_pos = self.text.GetInsertionPoint()
            end_pos = self.text.GetLastPosition()
            autoscroll = (current_pos == end_pos)

            if (autoscroll is True):
                self.text.AppendText("%s\n" % msg)
            else:
                self.text.Freeze()
                (selection_start, selection_end) = self.text.GetSelection()
                self.text.SetEditable(True)
                self.text.SetInsertionPoint(end_pos)
                self.text.WriteText("%s\n" % msg)
                self.text.SetEditable(False)
                self.text.SetInsertionPoint(current_pos)
                self.text.SetSelection(selection_start, selection_end)
                self.text.Thaw()
                self.text.Refresh()
                
        except (Exception) as err:
            sys.stderr.write("Error: %s failed while responding to a log message: %s.\n" % (self.__class__.__name__, str(err)))

        if (e is not None): e.Skip(True)

class logThread(threading.Thread):
    """Run the MainLoop as a thread. Access the frame with self.frame."""
    def __init__(self, autoStart=True):
        threading.Thread.__init__(self)
        self.setDaemon(1)
        self.start_orig = self.start
        self.start = self.start_local
        self.frame = None #to be defined in self.run
        self.lock = threading.Lock()
        self.lock.acquire() #lock until variables are set
        if autoStart:
            self.start() #automatically start thread on init

    def run(self):
        import wx 
        atexit.register(disable_asserts)

        app = wx.App(False)

        frame = LogWnd()

        #define frame and release lock
        self.frame = frame
        self.lock.release()

        app.MainLoop()
        
    def destroy(self):
        self.frame.Destroy()
        
    def start_local(self):
        self.start_orig()
        #After thread has started, wait until the lock is released
        #before returning so that functions get defined.
        self.lock.acquire()

def runLogThread():
    lt = logThread() #run wx MainLoop as thread
    frame = lt.frame #access to wx Frame
    lt.frame.Show(False)
    return lt

def consoleWin(systray):
    logthr.frame.Show(True)

def disable_asserts():
    import wx
    wx.DisableAsserts()

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
    except Exception as e:
        logging.debug("ERROR DURING WAKE UP BLE : " + str(e))
        return False
    return True

async def ping_bs(bs_mac_address, bs_unique_id, loop):
    try:
        async with BleakClient(bs_mac_address, loop=loop) as client:
            cmd = build_bs_ble_cmd(BS_CMD_ID_WAKEUP_TIMEOUT, BS_TIMEOUT_IN_SEC, bs_unique_id)
            logging.debug("PING CMD : " + str(binascii.hexlify(cmd)))
            await client.write_gatt_char(BS_CMD_BLE_ID, cmd)
    except Exception as e:
        logging.debug("ERROR DURING PING BLE : " + str(e))
        return False
    return True

async def shut_down_bs(bs_mac_address, bs_unique_id, loop):
    try:
        async with BleakClient(bs_mac_address, loop=loop) as client:
            cmd = build_bs_ble_cmd(BS_CMD_ID_WAKEUP_TIMEOUT, 2, bs_unique_id)
            logging.debug("PING CMD : " + str(binascii.hexlify(cmd)))
            await client.write_gatt_char(BS_CMD_BLE_ID, cmd)
    except Exception as e:
        logging.debug("ERROR DURING PING BLE : " + str(e))
        return False
    return True

def bs_standby():
    loop = asyncio.new_event_loop()
    loop.set_debug(False)
    asyncio.set_event_loop(loop)
    if len(bs1_mac) > 0:
        idx = 1
        while True:
            if loop.run_until_complete(shut_down_bs(bs1_mac, bs1_sn, loop)):
                logging.info("Standby command sent to BS1")
                break
            idx+=1
            if idx > 10:
                break
    if len(bs2_mac) > 0:
        idx = 1
        while True:
            if loop.run_until_complete(shut_down_bs(bs2_mac, bs2_sn, loop)):
                logging.info("Standby command sent to BS2")
                break
            idx+=1
            if idx > 10:
                break
    return True

def is_pimax_headset_present():
    global hs_tlock
    global hs_status
    hs_tlock = True
    if not DEBUG_BYPASS_USB:
        if not find_pimax_headset():
            if not hs_status == "Off":
                logging.info("Pimax Headset not found")
            if hs_status == "ON":
                logging.info("Issuing standby command to Base Stations")
                bs_standby()
            time.sleep(SLEEP_TIME_SEC_USB_FIND)
            hs_status = "Off"
            hs_tlock = True
            return False
        else:
            if not hs_status == "ON":
                logging.info("Pimax Headset active")
            hs_tlock = False
            hs_status = "ON"
    else:
        hs_tlock = False
        hs_status = "DEBUG"
    return True

def load_configuration():
    config = configparser.ConfigParser()
    config.read('configuration.ini')
    logging.debug("Configuration file Headset USB ID: " + config['HeadSet']['USB_VENDOR_ID'])
    global PIMAX_USB_VENDOR_ID
    global LH_DB_FILE
    global BS_TIMEOUT_IN_SEC
    PIMAX_USB_VENDOR_ID = int(config['HeadSet']['USB_VENDOR_ID'], 0)
    conf_BS_TIMEOUT_IN_SEC = int(config['BaseStation']['BS_TIMEOUT_IN_SEC'], 0)
    if conf_BS_TIMEOUT_IN_SEC >= 30 and conf_BS_TIMEOUT_IN_SEC <= 120:
        BS_TIMEOUT_IN_SEC = conf_BS_TIMEOUT_IN_SEC
        logging.debug("Configuration file BS timeout: " + config['BaseStation']['BS_TIMEOUT_IN_SEC'])
    LH_DB_FILE = config['HeadSet']['LH_DB_FILE']
    logging.debug("Configuration file LightHouse DB filepath: " + LH_DB_FILE)

async def basescan():
    devices = await discover()
    for d in devices:
        bs = re.search("HTC BS", str(d))
        if bs:
            bsmac = re.search(r"(\A\w+:\w+:\w+:\w+:\w+:\w+)", str(d))
            bsid =  re.search(r"HTC BS \w\w(\w\w\w\w)", str(d))
            stations.append(bsmac.group(1) + " " + bsid.group(1))
            logging.debug("Found BS via BLE Scan: " + bsmac.group(1) + " " + bsid.group(1))

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
    global bs1_tlock
    global bs2_tlock
    global bs1_wakeup_cmd
    global bs2_wakeup_cmd
    global disco_tlock
    global stations
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

    bs1_tlock = True
    bs2_tlock = True
    disco_tlock = True

    systray.update(hover_text=tray_label())
    
    try:
        with open(LH_DB_FILE) as json_file:
            data = json.loads(json_file.read())
            known = data['known_universes']
            try:
                bs1_sn = data['known_universes'][0]['base_stations'][0]['base_serial_number']
                bs1_snhx = hex(bs1_sn)
                logging.info("Found BS1 serial in DB: " + str(bs1_snhx))
            except:
                logging.info("Not Found BS1 serial in DB")
            try:
                bs2_sn = data['known_universes'][0]['base_stations'][1]['base_serial_number']
                bs2_snhx = hex(bs2_sn)
                logging.info("Found BS2 serial in DB: " + str(bs2_snhx))
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
    loop.set_debug(False)
    asyncio.set_event_loop(loop)
    loop.run_until_complete(basescan())
    logging.info("Found BS count via BLE Discovery: " + str(len(stations)))
    if len(stations) > 0:
        for base in stations:
            base_list = base.split(" ")
            if re.search(r'('+str(bs1_snhx)[-4:].upper()+')$', base_list[1].upper()):
                logging.debug("Found BS1 RE: " + str(bs1_snhx)[-4:].upper() + " in " + base_list[1].upper())
                bs1_mac = base_list[0]
                logging.info("Found BS1: MAC=" + str(bs1_mac) + " ID=" + str(bs1_snhx)[-8:].upper())
                bs1_status = "Discovered"
                bs1_tlock = False
                bs1_wakeup_cmd = False
            if re.search(r'('+str(bs2_snhx)[-4:].upper()+')$', base_list[1].upper()):
                logging.debug("Found BS2 RE: " + str(bs2_snhx)[-4:].upper() + " in " + base_list[1].upper())
                bs2_mac = base_list[0]
                logging.info("Found BS2: MAC=" + str(bs2_mac) + " ID=" + str(bs2_snhx)[-8:].upper())
                bs2_status = "Discovered"
                bs2_tlock = False
                bs2_wakeup_cmd = False
    systray.update(hover_text=tray_label())
    disco_tlock = False
    

def tray_label():
    global hs_status
    global bs1_status
    global bs2_status
    return HS_LABEL + " [" + hs_status + "] " + BS1_LABEL + " [" +str(bs1_snhx)[-4:].upper() + ":" + bs1_status + "] " + BS2_LABEL + " [" + str(bs2_snhx)[-4:].upper() + ":" + bs2_status + "]"

def on_quit_callback(systray):
    global quit_main_loop
    quit_main_loop = True
    logthr.destroy()
    #sys.exit()

class bs1Thread(threading.Thread):
    def __init__(self, systray, autoStart=True):
        threading.Thread.__init__(self)
        self.setDaemon(1)
        self.start_orig = self.start
        self.start = self.start_local
        self.lock = threading.Lock()
        self.lock.acquire() #lock until variables are set
        if autoStart:
            self.start() #automatically start thread on init

    def run(self):

        try:
            global hs_tlock
            global bs1_tlock
            global bs1_status
            global quit_main_loop
            global bs1_wait_loop
            global bs1_wakeup_cmd

            self.lock.release()

            t_last_cmd = time.time()
            t_wait_loop = 1
            
            bs1_wakeup_cmd = False
            ping_cmd = False

            loop = asyncio.new_event_loop()
            loop.set_debug(False)
            asyncio.set_event_loop(loop)

            while True:
                if quit_main_loop:
                    break

                if len(bs1_mac) < 1:
                    logging.debug("BS1 not found, skipping keepalive")
                    time.sleep(5)
                    continue    

                if hs_tlock:
                    time.sleep(5)
                    continue

                #logging.debug("NOW=%s LAST=%s WAIT=%s DIFF=%s", time.time(), t_last_cmd, t_wait_loop, time.time()-t_last_cmd)
                
                if time.time()-t_last_cmd <= t_wait_loop:
                    time.sleep(1)
                    continue

                if bs1_tlock:
                    logging.debug("BS1 loop wait lock, skipping keepalive")
                    continue
                
                if not bs1_wakeup_cmd or (time.time()-t_last_cmd > BS_TIMEOUT_IN_SEC-5 and not ping_cmd):
                    logging.debug("Waking up BS1 MAC=" + bs1_mac)
                    if not loop.run_until_complete(wake_up_bs(bs1_mac, loop)):
                        logging.info("Error wake-up for BS1")
                        t_wait_loop = BS_LOOP_RETRY
                        bs1_wakeup_cmd = False
                        bs1_status = "Wakeup-error"
                        systray.update(hover_text=tray_label())
                    else:
                        logging.info("Success wake-up for BS1")
                        t_last_cmd = time.time()
                        t_wait_loop = BS_LOOP_SLEEP
                        bs1_wakeup_cmd = True
                        bs1_status = "Wakeup"
                        systray.update(hover_text=tray_label())
                    t_last_cmd = time.time()
                    continue

                logging.debug("Pinging BS1: MAC=" + bs1_mac + " ID=" + str(bs1_snhx)[-8:].upper()) 
                if not loop.run_until_complete(ping_bs(bs1_mac, bs1_sn, loop)):
                    logging.info("Error ping for BS1")
                    t_wait_loop = BS_LOOP_RETRY
                    ping_cmd = False
                    bs1_status = "Ping-error"
                    systray.update(hover_text=tray_label())
                else:
                    if not ping_cmd:
                        logging.info("Success ping for BS1")
                    t_last_cmd = time.time()
                    t_wait_loop = BS_LOOP_SLEEP
                    ping_cmd = True
                    bs1_status = "Pinging"
                    systray.update(hover_text=tray_label())
                t_last_cmd = time.time()

        except Exception as err:
            logging.debug("Error: %s in main thread: %s.\n" % (self.__class__.__name__, str(err)))
            quit_main_loop = True
      
    def destroy(self):
        self.frame.Destroy()
        
    def start_local(self):
        self.start_orig()
        self.lock.acquire()

class bs2Thread(threading.Thread):
    def __init__(self, systray, autoStart=True):
        threading.Thread.__init__(self)
        self.setDaemon(1)
        self.start_orig = self.start
        self.start = self.start_local
        self.lock = threading.Lock()
        self.lock.acquire() #lock until variables are set
        if autoStart:
            self.start() #automatically start thread on init

    def run(self):

        try:
            global hs_tlock
            global bs2_tlock
            global bs2_status
            global quit_main_loop
            global bs2_wait_loop
            global bs2_wakeup_cmd
            self.lock.release()

            t_last_cmd = time.time()
            t_wait_loop = 1
            
            bs2_wakeup_cmd = False
            ping_cmd = False

            loop = asyncio.new_event_loop()
            loop.set_debug(False)
            asyncio.set_event_loop(loop)

            while True:
                if quit_main_loop:
                    break

                if len(bs2_mac) < 1:
                    logging.debug("BS2 not found, skipping keepalive")
                    time.sleep(5)
                    continue    

                if hs_tlock:
                    time.sleep(5)
                    continue

                #logging.debug("NOW=%s LAST=%s WAIT=%s DIFF=%s", time.time(), t_last_cmd, t_wait_loop, time.time()-t_last_cmd)
                
                if time.time()-t_last_cmd <= t_wait_loop:
                    time.sleep(1)
                    continue

                if bs2_tlock:
                    logging.debug("BS2 loop wait lock, skipping keepalive")
                    continue
                
                if not bs2_wakeup_cmd or (time.time()-t_last_cmd > BS_TIMEOUT_IN_SEC-5 and not ping_cmd):
                    logging.debug("Waking up BS2 MAC=" + bs2_mac)
                    if not loop.run_until_complete(wake_up_bs(bs2_mac, loop)):
                        logging.info("Error wake-up for BS2")
                        t_wait_loop = BS_LOOP_RETRY
                        bs2_wakeup_cmd = False
                        bs2_status = "Wakeup-error"
                        systray.update(hover_text=tray_label())
                    else:
                        logging.info("Success wake-up for BS2")
                        t_last_cmd = time.time()
                        t_wait_loop = BS_LOOP_SLEEP
                        bs2_wakeup_cmd = True
                        bs2_status = "Wakeup"
                        systray.update(hover_text=tray_label())
                    t_last_cmd = time.time()
                    continue

                logging.debug("Pinging BS2: MAC=" + bs2_mac + " ID=" + str(bs2_snhx)[-8:].upper()) 
                if not loop.run_until_complete(ping_bs(bs2_mac, bs2_sn, loop)):
                    logging.info("Error ping for BS2")
                    t_wait_loop = BS_LOOP_RETRY
                    ping_cmd = False
                    bs2_status = "Ping-error"
                    systray.update(hover_text=tray_label())
                else:
                    if not ping_cmd:
                        logging.info("Success ping for BS2")
                    t_last_cmd = time.time()
                    t_wait_loop = BS_LOOP_SLEEP
                    ping_cmd = True
                    bs2_status = "Pinging"
                    systray.update(hover_text=tray_label())
                t_last_cmd = time.time()

        except Exception as err:
            logging.debug("Error: %s in main thread: %s.\n" % (self.__class__.__name__, str(err)))
            quit_main_loop = True
      
    def destroy(self):
        self.frame.Destroy()
        
    def start_local(self):
        self.start_orig()
        self.lock.acquire()

def main_loop(systray):
    try:
        global hs_tlock
        global disco_tlock
        global bs1_sn
        global bs2_sn
        global bs1_mac
        global bs2_mac
        global bs1_status
        global bs2_status
        global quit_main_loop

        bslthr = bs1Thread(systray)
        time.sleep(2)
        bs2thr = bs2Thread(systray)

        while True:
            # Step 0 : Check systray status
            if quit_main_loop:
                logging.debug("Quit main_loop, systray status="+str(quit_main_loop))
                break

            # Step 1 : find Pimax Headset
            systray.update(hover_text=tray_label())
            if not is_pimax_headset_present():
                continue
            systray.update(hover_text=tray_label())

            if not disco_tlock and ((bs1_sn > 0 and len(bs1_mac) < 1) or (bs2_sn > 0 and len(bs2_mac) < 1)):
                logging.info("Headset is active, re-attempt discovery")
                bs_discovery(systray)
                continue

            time.sleep(5)

    except (Exception) as err:
        sys.stderr.write("Error in main thread: %s.\n", str(err))
        systray.shutdown()

class LevelFilter(object):
    def __init__(self, level):
        self.level = level

    def filter(self, record):
        return record.levelno >= self.level
              
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug_ignore_usb", help="Disable the USB search for headset", action="store_true")
    parser.add_argument("--debug_logs", help="Enable DEBUG level logs", action="store_true")

    args = parser.parse_args()
    DEBUG_BYPASS_USB = args.debug_ignore_usb
    DEBUG_LOGS = args.debug_logs

    if DEBUG_LOGS:
        MIN_LEVEL = logging.DEBUG
        os.environ["BLEAK_LOGGING"] = "True"
    else:
        MIN_LEVEL = logging.INFO
        os.environ["BLEAK_LOGGING"] = "False"

    FORMAT = "%(asctime)s %(levelname)s (%(module)s): %(message)s"
    logging.basicConfig(format=FORMAT, level=MIN_LEVEL)
    log_formatter = logging.Formatter("%(asctime)s %(levelname)s (%(module)s): %(message)s", "%H:%M:%S")
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(log_formatter)
    h.setLevel(MIN_LEVEL)

    logthr = runLogThread()

    wx_handler = wxLogHandler(lambda: logthr.frame)
    wx_handler.setFormatter(log_formatter)
    wx_handler.setLevel(MIN_LEVEL)
    wx_handler.addFilter(LevelFilter(MIN_LEVEL))
    logging.getLogger().addHandler(wx_handler)

    logger.addHandler(h)    
    logger = logging.getLogger(__name__)
    
    load_configuration()
 
    icon = TRAY_ICON
    hover_text = tray_label()

    menu_options = (('Run BaseStation Discovery', None, bs_discovery),
                    ('Open console log', None, consoleWin),
                    ('Version '+VERSION, None, do_nothing)
                    )
    
    with SysTrayIcon(icon, hover_text, menu_options, on_quit=on_quit_callback) as systray:
        bs_discovery(systray)        
        main_loop(systray)        