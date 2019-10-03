# pimax_bs_manager - Pimax HTC Base Station manager for Windows

Original code from:
https://github.com/TheMalkavien/lhbsv1_pimax

Thanks a lot to TheMalkavien for posting is work and all the previous contributors!

Usage:
- Just run the executable or the Python script (tested on 3.7.4) 
- Status console via system tray menu, log output and status display with autoscroll
- Status is available on the hover text on the system tray icon (just move the mouse over it and you'll get HS and BS status)
- Basestation mode "Auto" defaults to Ping, "Idle" execute last command and idles
- The status panel windows includes th following buttons:
  - Copy to clipboard: will copy the logs in the window to your clipboard
  - Headset Debug: the Headset connection will be forced on
  - BS Switch mode: change behavior from Auto to Idle and vice versa
  - BS Standby: send a Standby/Off sequence to the Basestations
  - BS Wakeup: send a Wakeup/Ping sequence to the Basestations
  - Run BS discovery: run again the Basestations Discovery
  - Close: hide the window, pause the dashboard updates
- If you have Windows installed not in C: please check the location of the LightHouse DB json file in the .ini file

New from the original script:
- Discovery of base stations
- Status console with status display, log output, copy log o clipboard
- System tray icon with status of Headset and Base stations via mouse hover text
- Re-discovery of base stations
- Issue of Standby command once the Headset is Off

Command line switches:
- "--debug_ignore_usb", "Disable the USB search for headset"
- "--debug_logs", "Enable DEBUG level logs"
- "--version", show version  number in a toast notification

Limitations:
- Tested only on my HTC BS with latest firmware and on Windows 10

Requirements:
- HTC Base stations 1.0
- Python dependencies: on top of the original dependencies there's infi.systray for the Windows System Tray
- Bluetooth in Windows with BLE protocol (it does NOT use the Pimax or Vive Bluetooth controller)
- The Base stations must be paired in Windows (on Windows 10 you should get an Add Device popup for each BS)

Single executable available with ini and ico file in a ZIP file:
- Built with: pyinstaller --onefile Pimax_BSAW.py --hidden-import pkg_resources --hidden-import infi.systray --hidden-import bleak --add-binary "BleakUWPBridge.dll;BleakUWPBridge" --icon=pimax.ico --version-file pimax_bsaw_version_info.txt --noconsole
- You need to copy BleakUWPBridge.dll in the script directory from %HOMEPATH%\Miniconda3\Lib\site-packages\bleak\backends\dotnet\ (in this case using Miniconda)

Support:
- None, but you can post in this Pimax forum thread for help: https://forum.pimaxvr.com/t/how-to-power-off-basestations-remotely/15205/109

Todo:
- Support for Valve BS v2, preliminary code in, still not working
- Support for other Headsets  

# Changelog:
- v1.5.1
    - New: Dump USB HID in logs if run with debug_logs flag
    - Fix: small fixes for the dashboard
- v1.5.0
    - New: added "--version" switch to display version number in a toast notification
    - New: (almost) complete code refactoring
    - New: Classes for main and Base Stations to avoid use of global vars and de-duplication
    - New: Discovery runs in its own thread, retries 20 times until all BS are found
    - New: console log window is now renamed as status panel, includes now status information
    - New: improved console log window with colored levels
    - New: hints in logs for troubleshooting if too many connection errors are logged over a short period
    - New: Basestation mode "Auto" defaults to Ping, "Idle" execute last command and idles
    - New: The status panel windows includes buttons to send Wakeup, Standby, Change mode, Run Discovery, switch Headset to Debug mode
    - Fix: standby is sent when headset switches off and at exit program
    - Fix: improved error messages management
    - Fix: many more fixes thanks to refactoring
    - Note: added some code the manage the Valve BS v2, still not working
 - v1.4.0
    - Fix: bleak python library used properly
- v1.3.1
    - Fix: Console log window centered on screen 
    - New: Exceptions handling for main thread with Windows 10 toast notifications
- v1.3
    - Fix: Too many small fixes and enhancements to list 
    - New: Console log output with autoscroll and copy to clipboard
    - New: DEBUG log level can be enable via command line switch
    - New: Separate threads for BS loops
    - New: Proper logging output
    - New: Standby command issued to BS when HS is On>Off
    - New: BS Timeout configurable in .ini
    - New: Added version info to executable
- v1.2
    - Fix: Switch to using LightHouse DB json file from Pimax runtime folder 
    - New: version in system tray
    - New: BS status for Discovered, Wakeup, Pinging, Errors
- v1.1
    - Fix: HeadSet status not updated properly from On to Off
    - Executable: added icon
