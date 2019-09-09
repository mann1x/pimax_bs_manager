# pimax_bs_manager - Pimax HTC Base Station manager for Windows

Original code from:
https://github.com/TheMalkavien/lhbsv1_pimax

Thanks a lot to TheMalkavien for posting is work and all the previous contributors!

Usage:
- Just run the executable or the Python script (tested on 3.7, use it if you want to check the console output for errors) 
- Status is only available on the hover text on the system tray icon (just move the mouse over it and you'll get HS and BS status)
- If you have Windows installed not in C: please check the location of the LightHouse DB json file in the .ini file

New from the original script:
- Discovery of base stations
- System tray icon with status of Headset and Base stations via hover text
- Re-discovery of base stations

Command line switches:
 - "--debug_ignore_usb", "Disable the USB search for headset"

Limitations:
- Only the first 2 base stations status is displayed in the system tray hover text
- All the base stations in range are discovered and triggered on via wakeup
- Tested only on my HTC BS with latest firmware and on Windows 10

Requirements:
- HTC Base stations 1.0
- Python dependencies: on top of the original dependencies there's infi.systray for the Windows System Tray
- Bluetooth in Windows with BLE protocol (it does NOT use the Pimax or Vive Bluetooth controller)
- The Base stations must be paired in Windows (on Windows 10 you should get an Add Device popup for each BS)

Single executable available with ini and ico file in a ZIP file:
- Built with: pyinstaller --onefile Pimax_BSAW.py --hidden-import pkg_resources --hidden-import infi.systray --hidden-import bleak --add-binary "BleakUWPBridge.dll;BleakUWPBridge" --noconsole
- You need to copy BleakUWPBridge.dll in the script directory from %HOMEPATH%\Miniconda3\Lib\site-packages\bleak\backends\dotnet\ (in this case using Miniconda)
- Name: pimax_bsaw_v1_2.zip
  - Size: 11006346 bytes (10 MiB)
  - SHA256: ACFF3A3358E1487CFD67931D30513A935DC308D0535B8F1F0AA4500818E0655C

# Changelog:
- v1.2
  - Fix: Switch to using LightHouse DB json file from Pimax runtime folder 
  - New: version in system tray
  - New: BS status for Discovered, Wakeup, Pinging, Errors
- v1.1
  - Fix: HeadSet status not updated properly from On to Off
  - Executable: added icon
