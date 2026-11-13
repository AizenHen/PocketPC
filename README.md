# PocketPC v1

PocketPC is a Windows-to-phone screen viewer with optional mouse control. The browser and WebRTC paths are limited to your private Tailscale network. Every session needs the current 8-digit code and explicit approval in the Windows window before capture starts. Mouse control is disabled by default and is shown clearly in the Windows approval.

PocketPC has no keyboard, audio, clipboard, upload, download, or file access.

## Security design

- The Python web server binds only to `127.0.0.1`; it is not reachable directly from Wi-Fi or the public internet.
- Tailscale Serve supplies the private `https://...ts.net` address and WebSocket proxy. **Tailscale Funnel is never enabled.**
- WebRTC accepts and advertises only Tailscale `100.64.0.0/10` candidates. A minimal STUN responder bound only to the PC's Tailscale address lets Safari discover its own Tailscale address; it is not a relay and carries no pixels. Safari `.local` candidates are discarded unless they map to Tailscale.
- Adaptive quality uses Safari's WebRTC loss and latency reports to switch among Smooth (720p/20 FPS), Balanced (up to 900p/15 FPS), and Sharp (up to 1080p/12 FPS). You can also lock a preset manually. WebRTC receiver feedback can still lower bitrate when needed.
- Windows capture prefers DXGI Desktop Duplication for lower latency and verifies the DXGI output's exact desktop coordinates against the display approved on Windows before reading a frame. If DXGI is unavailable or cannot prove that match, PocketPC safely falls back to MSS.
- H.264 encoding automatically self-tests NVIDIA NVENC, Intel Quick Sync, and AMD AMF when those encoders are exposed by the bundled FFmpeg/PyAV build. A runtime failure falls back to the existing low-latency `libx264` encoder.
- The Windows **Connection Assistant** checks Tailscale, the private HTTPS route, WebRTC readiness, the active capture engine, video encoder, and approval policy without exposing those diagnostics as a network endpoint.
- Pinch and pan change only a validated crop inside the display already approved on Windows. Optional mouse events use the authenticated encrypted WSS control session inside Tailscale, are strictly allowlisted and rate-limited, and are revalidated by a temporary elevated mouse helper connected over an authenticated local named pipe. The helper has no network listener, stays restricted to the approved display, and exits when the approved session expires. Video remains encrypted WebRTC. Keyboard messages are rejected.
- Screen capture is created only after the local Windows user approves one selected display.
- Closing or backgrounding the phone app keeps the approved session available for automatic reconnection for at most five minutes. **STOP SHARING**, manual disconnect, or expiry ends capture and revokes access immediately. Pairing codes also expire after five minutes.
- Brief Wi-Fi, Tailscale, Safari, or WebRTC interruptions automatically rebuild the encrypted connection for the already-approved iPhone. A random resume credential rotates after every successful reconnect and expires after five minutes without live activity. **STOP SHARING**, manual disconnect, expiry, or restarting PocketPC revokes it immediately.
- Tailscale access controls still apply. Protect the tailnet account with MFA and remove devices you no longer own.

## Recommended install

1. Install and connect Tailscale on Windows first.
2. Close any older PocketPC window.
3. Run `release\PocketPC-Setup-1.7.0.exe` and approve the Windows administrator prompt.
4. Follow the guided Tailscale check. Setup verifies that Tailscale is installed, signed in, connected, and has a private address before continuing.
5. Choose the installation folder and whether to create a desktop shortcut.
6. Launch PocketPC from the desktop shortcut when setup finishes.

The installer creates normal desktop and Start Menu shortcuts, configures the private Tailscale Serve address, and adds two inbound UDP rules restricted to the installed `PocketPC.exe`, this PC's Tailscale address, and other Tailscale addresses. It never enables Tailscale Funnel and does not open the web server to Ethernet, Wi-Fi, or the public internet.

This locally built installer is not code-signed. Windows may identify the publisher as unknown. For distribution to other people, sign both executables with a trusted code-signing certificate rather than asking users to bypass security warnings.

## Requirements for source development

- Windows 11 with Python 3.11+ and Node.js 20+
- Tailscale installed and signed in on Windows
- Tailscale installed and signed in to the same tailnet on the iPhone
- MagicDNS and HTTPS enabled for the tailnet

## Source install (alternative)

Open ordinary PowerShell:

```powershell
cd C:\path\to\PocketPC
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\scripts\build-icon.py
.\scripts\install-desktop-shortcut.ps1
cd .\frontend
npm install
npm run build
cd ..
```

Then open **PowerShell as Administrator** and run the one-time private proxy setup:

```powershell
cd C:\path\to\PocketPC
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\setup-tailscale.ps1
```

The script configures Tailscale Serve and removes obsolete PocketPC firewall rules. The HTTPS server remains loopback-only and Tailscale Funnel is not enabled.

The browser uses UDP port `3478` on the Tailscale adapter only for WebRTC address discovery. The video itself uses WebRTC's encrypted DTLS-SRTP transport. The source setup does not open its HTTPS server or an unrestricted rule on Ethernet/Wi-Fi.

## Run

Double-click the **PocketPC** icon on the Windows desktop. It opens only the styled PocketPC control window—there is no PowerShell/Command Prompt window. The native title bar, window border, desktop icon, and taskbar icon use PocketPC's dark theme and branding.

Or run it manually in ordinary PowerShell:

```powershell
cd C:\path\to\PocketPC
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\start-pocketpc.ps1
```

Keep PocketPC running. Its window can be minimized to the Windows taskbar while sharing; the taskbar title says **SHARING DISPLAY**. Restore it at any time to use **STOP SHARING**. The Windows panel uses the same navy and mint styling as the iPhone viewer and displays the adaptive stream range.

Closing the Windows window now keeps PocketPC ready in the system tray. Use the tray menu to reopen it, stop sharing, or quit completely. The **Start PocketPC with Windows** checkbox is user-controlled and creates only a per-user startup entry; it never starts screen capture or bypasses approval.

## Test from iPhone

1. Open Tailscale on both devices and confirm both show connected.
2. Start PocketPC on Windows.
3. In PocketPC on the phone, optionally enable **Request mouse control**. Scan the Windows QR or type the displayed 8-digit code. The app decodes the QR locally and submits the current short-lived code. The code is stored in a URL fragment, which is removed immediately and is never sent in HTTPS request or proxy logs. Windows approval is still mandatory before capture begins.
4. Choose **Auto quality** for the recommended adaptive behavior, or select a fixed preset when pairing manually.
5. Confirm Windows requests approval but still says **NOT SHARING**.
6. Select the intended display and click the approval button. Its label explicitly lists mouse permission. When mouse control was requested, approve the Windows UAC prompt that starts the temporary elevated mouse helper.
7. Rotate the iPhone to landscape and verify only that display appears. PocketPC keeps the iPhone awake while viewing by default; this can be changed under **Settings**. The first successful connection shows a short gesture guide once.
   Tap **Full view** for PocketPC's browser-filling viewer. Its bottom controls stay hidden until you tap the screen, then hide again automatically. Pinch directly on the live screen to request a sharp server-side crop from 100% up to 2000%, drag with one finger to pan, and use **Reset zoom** to return to the complete display. PocketPC intentionally avoids Safari's native video fullscreen because that player limits zoom.
8. If mouse permission was approved, enter **Mouse** mode on the phone. Verify direct touch, tap-to-click, long-press right click, hold-and-drag, two-finger scrolling, and three-finger control reveal. Confirm that keyboard input and file transfer remain unavailable. Press **STOP SHARING** on Windows; video and the temporary helper should end immediately.
9. Briefly close and reopen the phone app: it should reconnect automatically within the five-minute approved window. Then disconnect manually or wait more than five minutes and verify that a fresh code and Windows approval are required.
10. Turn off Tailscale on the iPhone and reload Safari; PocketPC should be unreachable.

## Build the Windows installer

From ordinary PowerShell after completing the source install:

```powershell
cd C:\path\to\PocketPC
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
winget install --id JRSoftware.InnoSetup -e
.\scripts\build-windows.ps1
```

The result is `release\PocketPC-Setup-1.7.0.exe`. The installer provides a guided Tailscale connection check, an installation-folder page, and an optional desktop shortcut.

If you previously installed the old PocketPC CA on the iPhone, remove it in **Settings → General → VPN & Device Management**. It is not used by this version.

## Troubleshooting

```powershell
& "$env:ProgramFiles\Tailscale\tailscale.exe" status
& "$env:ProgramFiles\Tailscale\tailscale.exe" serve status
Get-NetFirewallRule -Name PocketPC-Installed-STUN,PocketPC-Installed-WebRTC -ErrorAction SilentlyContinue |
    Select-Object Name,Enabled,Profile,Direction,Action
```

For an installer deployment, the firewall command should show two enabled inbound allow rules; both are program-, Tailscale-address-, and tailnet-range-restricted. For a source deployment it may print nothing. If Safari cannot open the address, reconnect Tailscale on both devices. Installer users can reinstall to repeat configuration; source users can rerun `setup-tailscale.ps1` as Administrator. If the page opens but video does not, keep the iPhone Tailscale app connected, return to Safari, and pair again.

To disable the private web endpoint later:

```powershell
& "$env:ProgramFiles\Tailscale\tailscale.exe" serve reset
```

## Security reports

Please follow [SECURITY.md](SECURITY.md) and do not disclose vulnerability details in a public issue.

## License

PocketPC is available under the [MIT License](LICENSE).
