# pimax_bs_manager - Pimax HTC Base Station manager for Windows

Original code from:
https://github.com/TheMalkavien/lhbsv1_pimax

Thanks a lot to TheMalkavien for posting is work and all the previous contributors!

Added:
- Discovery of base stations
- System tray icon with status of Headset and Base stations via hover text
- Re-discovery of base stations

Command line switches:
 - "--debug_ignore_usb", "Disable the USB search for headset"

Limitations:
- Only the first 2 base stations status is displayed in the system tray hover text
- All the base stations in range are discovered and triggered on via wakeup

Requirements:
- HTC Base stations 1.0
- Python dependencies: on top of the original dependencies there's infi.systray for the Windows System Tray

Single executable available with ini and ico file in a ZIP file:
- Built with: pyinstaller --onefile Pimax_BSAW.py --hidden-import pkg_resources --hidden-import infi.systray --hidden-import bleak --add-binary "BleakUWPBridge.dll;BleakUWPBridge" --noconsole
- You need to copy BleakUWPBridge.dll in the script directory from %HOMEPATH%\Miniconda3\Lib\site-packages\bleak\backends\dotnet\ (in this case using Miniconda)

Name: pimax_bsaw.zip
Size: 11001414 bytes (10 MiB)
SHA256: E7B5BBC4CE049CF8DDA68C5A7BEF08A2EB5A0E7F75EC2DEE3E9E02D0AFDDDD24
