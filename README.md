# pimax_bs_manager - Pimax HTC Base Station manager for Windows

Original code from:
https://github.com/TheMalkavien/lhbsv1_pimax

Thanks a lot to TheMalkavien for posting is work and all the previous contributors!

Usage:
- Just run the executable or the Python script (tested on 3.7.3) 
- Status is only available on the hover text on the system tray icon (just move the mouse over it and you'll get HS and BS status)
- If you have Windows installed not in C: please check the location of the LightHouse DB json file in the .ini file
- Console log output with autoscroll and copy to clipboard available via system tray menu

New from the original script:
- Discovery of base stations
- System tray icon with status of Headset and Base stations via mouse hover text
- Console log output
- Re-discovery of base stations
- Issue of Standby command once the Headset is Off

Command line switches:
 - "--debug_ignore_usb", "Disable the USB search for headset"
 - "--debug_logs", "Enable DEBUG level logs"

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
- Name: pimax_bsaw_v1_3_1.zip
  - Size: 16410747 bytes (15 MiB)
  - SHA256: F78EF3DE7379BB632596CCF8041128AA3F13AFF2C4D2174EE07770EA5CA820AB

Support:
- None, but you can post in this Pimax forum thread for help: https://forum.pimaxvr.com/t/how-to-power-off-basestations-remotely/15205/109

# Changelog:

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
