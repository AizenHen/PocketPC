import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import jsQR from 'jsqr';
import './style.css';

type Phase = 'idle' | 'checking' | 'pending' | 'connecting' | 'live';
type QualityPreset = 'auto' | 'smooth' | 'balanced' | 'sharp';
type Language = 'en' | 'he';
const BACKGROUND_GRACE_MS = 5 * 60 * 1000;
const MAX_ZOOM = 20;
const HE_MESSAGES: Record<string, string> = {
  'Your Windows screen, securely within reach.': 'מסך ה-Windows שלך, קרוב ובאופן מאובטח.',
  'PocketPC QR recognized · connecting…': 'קוד ה-QR של PocketPC זוהה · מתחבר…',
  'Camera scanning is unavailable. Enter the Windows code manually.': 'סריקת המצלמה אינה זמינה. הזן את הקוד מ-Windows ידנית.',
  'The camera could not start. Allow camera access, then try again.': 'לא ניתן להפעיל את המצלמה. אפשר גישה למצלמה ונסה שוב.',
  'Camera access was not allowed. Enable it for PocketPC or enter the code manually.': 'הגישה למצלמה לא אושרה. אפשר אותה ל-PocketPC או הזן את הקוד ידנית.',
  'Returned within five minutes · restoring live view…': 'חזרת בתוך חמש דקות · משחזר תצוגה חיה…',
  'Secure QR recognized · connecting to your PC…': 'קוד QR מאובטח זוהה · מתחבר למחשב…',
  'Encrypted live view · approved on Windows': 'תצוגה חיה מוצפנת · אושרה ב-Windows',
  'Encrypted view + mouse · approved on Windows': 'צפייה ושליטת עכבר מוצפנות · אושרו ב-Windows',
  'Live view paused · return within five minutes to resume.': 'התצוגה הושהתה · ניתן לחזור בתוך חמש דקות.',
  'Open the private Tailscale HTTPS address shown on Windows.': 'פתח את כתובת ה-HTTPS הפרטית של Tailscale שמוצגת ב-Windows.',
  'Checking PocketPC and the private Tailscale route…': 'בודק את PocketPC ואת נתיב Tailscale הפרטי…',
  'Windows is already handling another request. Stop it there, then retry.': 'Windows כבר מטפל בבקשה אחרת. עצור אותה ונסה שוב.',
  'PocketPC did not answer the connection check. Confirm Tailscale and the Windows app are running.': 'PocketPC לא הגיב לבדיקת החיבור. ודא ש-Tailscale והיישום ב-Windows פועלים.',
  'Connection verified · waiting for explicit approval on Windows…': 'החיבור אומת · ממתין לאישור מפורש ב-Windows…',
  'Windows approved. Establishing encrypted video…': 'Windows אישר. יוצר וידאו מוצפן…',
  'Restoring the approved encrypted session…': 'משחזר את ההפעלה המוצפנת שאושרה…',
  'Approved session found · rebuilding encrypted video…': 'נמצאה הפעלה מאושרת · בונה מחדש וידאו מוצפן…',
  'Tap once more to start your screen.': 'הקש שוב כדי להפעיל את המסך.',
};

type ViewTransform = { scale: number; x: number; y: number };
type WakeLockHandle = { released: boolean; release: () => Promise<void> };
type Gesture = {
  kind: 'pan' | 'pinch'; startX: number; startY: number;
  startScale: number; startTranslateX: number; startTranslateY: number;
  startDistance?: number; elementCenterX?: number; elementCenterY?: number;
};
type MouseGesture = {
  kind: 'track' | 'scroll' | 'controls'; lastX: number; lastY: number;
  startX: number; startY: number; started: number; moved: boolean;
  held?: boolean; dragging?: boolean;
};

function App() {
  const [language, setLanguage] = useState<Language>(() => {
    try { return localStorage.getItem('pocketpc-language') === 'he' ? 'he' : 'en'; } catch { return 'en'; }
  });
  const [code, setCode] = useState('');
  const [phase, setPhase] = useState<Phase>('idle');
  const [message, setMessage] = useState('Your Windows screen, securely within reach.');
  const [playBlocked, setPlayBlocked] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [focusView, setFocusView] = useState(false);
  const [controlsVisible, setControlsVisible] = useState(false);
  const [quality, setQuality] = useState<QualityPreset>('auto');
  const [activeQuality, setActiveQuality] = useState('balanced');
  const [scannerOpen, setScannerOpen] = useState(false);
  const [manualPairing, setManualPairing] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showGestureGuide, setShowGestureGuide] = useState(false);
  const [requestMouse, setRequestMouse] = useState(() => {
    try { return localStorage.getItem('pocketpc-request-mouse') === 'true'; } catch { return false; }
  });
  const [mouseAllowed, setMouseAllowed] = useState(false);
  const [mouseMode, setMouseMode] = useState(false);
  const [keepAwake, setKeepAwake] = useState(() => {
    try { return localStorage.getItem('pocketpc-keep-awake') !== 'false'; } catch { return true; }
  });
  const video = useRef<HTMLVideoElement>(null);
  const socket = useRef<WebSocket | null>(null);
  const peer = useRef<RTCPeerConnection | null>(null);
  const heartbeat = useRef<ReturnType<typeof setInterval> | null>(null);
  const deadline = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backgroundDeadline = useRef<ReturnType<typeof setTimeout> | null>(null);
  const controlsDeadline = useRef<ReturnType<typeof setTimeout> | null>(null);
  const qualityMonitor = useRef<ReturnType<typeof setInterval> | null>(null);
  const qualityRef = useRef<QualityPreset>('auto');
  const activeQualityRef = useRef('balanced');
  const autoPairStarted = useRef(false);
  const scannerVideo = useRef<HTMLVideoElement>(null);
  const scannerCanvas = useRef<HTMLCanvasElement>(null);
  const scannerStream = useRef<MediaStream | null>(null);
  const scannerFrame = useRef<number | null>(null);
  const resumeToken = useRef<string | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempt = useRef(0);
  const wakeLock = useRef<WakeLockHandle | null>(null);
  const mounted = useRef(true);
  const viewTransform = useRef<ViewTransform>({ scale: 1, x: 0, y: 0 });
  const gesture = useRef<Gesture | null>(null);
  const mouseGesture = useRef<MouseGesture | null>(null);
  const holdTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const magnifier = useRef<HTMLDivElement>(null);
  const magnifierCanvas = useRef<HTMLCanvasElement>(null);
  const lastViewSent = useRef(0);
  const isHebrew = language === 'he';
  const tr = (english: string, hebrew: string) => isHebrew ? hebrew : english;
  const localizedMessage = isHebrew ? (HE_MESSAGES[message] ?? message) : message;

  function changeLanguage(next: Language) {
    setLanguage(next);
    try { localStorage.setItem('pocketpc-language', next); } catch { /* unavailable */ }
  }

  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dir = isHebrew ? 'rtl' : 'ltr';
  }, [language, isHebrew]);

  function saveResumeToken(token: string | null) {
    resumeToken.current = token;
    try {
      if (token) sessionStorage.setItem('pocketpc-resume', token);
      else sessionStorage.removeItem('pocketpc-resume');
    } catch {
      // The in-memory credential still supports reconnection for this run.
    }
  }

  function changeQuality(next: QualityPreset) {
    qualityRef.current = next;
    setQuality(next);
    try { localStorage.setItem('pocketpc-quality', next); } catch { /* unavailable */ }
    const preset = next === 'auto' ? 'balanced' : next;
    activeQualityRef.current = preset;
    setActiveQuality(preset);
    if (socket.current?.readyState === WebSocket.OPEN && phase === 'live') {
      socket.current.send(JSON.stringify({ type: 'quality', preset }));
    }
  }

  function dismissGestureGuide() {
    setShowGestureGuide(false);
    try { localStorage.setItem('pocketpc-gesture-guide', 'seen'); } catch { /* unavailable */ }
  }

  function stopScanner() {
    if (scannerFrame.current !== null) cancelAnimationFrame(scannerFrame.current);
    scannerFrame.current = null;
    scannerStream.current?.getTracks().forEach(track => track.stop());
    scannerStream.current = null;
    if (scannerVideo.current) scannerVideo.current.srcObject = null;
    if (mounted.current) setScannerOpen(false);
  }

  function scanCameraFrame() {
    const camera = scannerVideo.current;
    const canvas = scannerCanvas.current;
    if (!camera || !canvas || !scannerStream.current) return;
    if (camera.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && camera.videoWidth && camera.videoHeight) {
      const maxWidth = 720;
      const scale = Math.min(1, maxWidth / camera.videoWidth);
      canvas.width = Math.round(camera.videoWidth * scale);
      canvas.height = Math.round(camera.videoHeight * scale);
      const context = canvas.getContext('2d', { willReadFrequently: true });
      if (context) {
        context.drawImage(camera, 0, 0, canvas.width, canvas.height);
        const image = context.getImageData(0, 0, canvas.width, canvas.height);
        const result = jsQR(image.data, image.width, image.height, { inversionAttempts: 'dontInvert' });
        if (result) {
          try {
            const target = new URL(result.data);
            const match = /^#pair=(\d{8})$/.exec(target.hash);
            if (target.origin === location.origin && target.pathname === '/' && match) {
              const pairingCode = match[1];
              stopScanner();
              setCode(pairingCode);
              setMessage('PocketPC QR recognized · connecting…');
              void connectWithCode(pairingCode);
              return;
            }
          } catch {
            // Ignore unrelated QR codes and keep looking for this PocketPC.
          }
        }
      }
    }
    scannerFrame.current = requestAnimationFrame(scanCameraFrame);
  }

  async function startScanner() {
    if (phase !== 'idle' || scannerStream.current) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setMessage('Camera scanning is unavailable. Enter the Windows code manually.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }
      });
      scannerStream.current = stream;
      setScannerOpen(true);
      requestAnimationFrame(async () => {
        const camera = scannerVideo.current;
        if (!camera || scannerStream.current !== stream) { stopScanner(); return; }
        camera.srcObject = stream;
        try {
          await camera.play();
          scannerFrame.current = requestAnimationFrame(scanCameraFrame);
        } catch {
          stopScanner();
          setMessage('The camera could not start. Allow camera access, then try again.');
        }
      });
    } catch {
      stopScanner();
      setMessage('Camera access was not allowed. Enable it for PocketPC or enter the code manually.');
    }
  }

  function sendServerView(view: ViewTransform, force = false) {
    const ws = socket.current;
    const element = video.current;
    if (!element || !ws || ws.readyState !== WebSocket.OPEN) return;
    const now = performance.now();
    if (!force && now - lastViewSent.current < 50) return;
    const rect = element.parentElement?.getBoundingClientRect() ?? element.getBoundingClientRect();
    const x = Math.min(1 - .5 / view.scale, Math.max(.5 / view.scale, .5 - view.x / (rect.width * view.scale)));
    const y = Math.min(1 - .5 / view.scale, Math.max(.5 / view.scale, .5 - view.y / (rect.height * view.scale)));
    ws.send(JSON.stringify({ type: 'view', zoom: view.scale, x, y }));
    lastViewSent.current = now;
  }

  function applyView(next: ViewTransform) {
    const element = video.current;
    if (!element) return;
    const scale = Math.min(MAX_ZOOM, Math.max(1, next.scale));
    const rect = element.parentElement?.getBoundingClientRect() ?? element.getBoundingClientRect();
    const maxX = Math.max(0, rect.width * (scale - 1) / 2);
    const maxY = Math.max(0, rect.height * (scale - 1) / 2);
    const x = scale === 1 ? 0 : Math.min(maxX, Math.max(-maxX, next.x));
    const y = scale === 1 ? 0 : Math.min(maxY, Math.max(-maxY, next.y));
    viewTransform.current = { scale, x, y };
    sendServerView(viewTransform.current);
    if (mounted.current) setZoom(scale);
  }

  function resetZoom() {
    gesture.current = null;
    applyView({ scale: 1, x: 0, y: 0 });
    sendServerView({ scale: 1, x: 0, y: 0 }, true);
  }

  function sendMouse(event: Record<string, string | number>) {
    const ws = socket.current;
    if (!mouseAllowed || !mouseMode || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: 'mouse', event }));
  }

  function videoPoint(clientX: number, clientY: number) {
    const element = video.current;
    if (!element || !element.videoWidth || !element.videoHeight) return null;
    const rect = element.getBoundingClientRect();
    const sourceRatio = element.videoWidth / element.videoHeight;
    const boxRatio = rect.width / rect.height;
    const width = boxRatio > sourceRatio ? rect.height * sourceRatio : rect.width;
    const height = boxRatio > sourceRatio ? rect.height : rect.width / sourceRatio;
    const left = rect.left + (rect.width - width) / 2;
    const top = rect.top + (rect.height - height) / 2;
    if (clientX < left || clientX > left + width || clientY < top || clientY > top + height) return null;
    return {
      x: Math.min(1, Math.max(0, (clientX - left) / width)),
      y: Math.min(1, Math.max(0, (clientY - top) / height)),
      width, height
    };
  }

  function pointAtScreen(clientX: number, clientY: number) {
    const point = videoPoint(clientX, clientY);
    if (!point) return false;
    sendMouse({ type: 'position', x: point.x, y: point.y });
    return true;
  }

  function showPrecision(clientX: number, clientY: number) {
    const element = video.current;
    const point = videoPoint(clientX, clientY);
    const host = magnifier.current;
    const canvas = magnifierCanvas.current;
    if (!element || !point || !host || !canvas) return;
    const size = 120;
    const cropWidth = Math.max(18, 42 * element.videoWidth / point.width);
    const cropHeight = Math.max(18, 42 * element.videoHeight / point.height);
    const sourceX = point.x * element.videoWidth;
    const sourceY = point.y * element.videoHeight;
    const sx = Math.max(0, Math.min(element.videoWidth - cropWidth, sourceX - cropWidth / 2));
    const sy = Math.max(0, Math.min(element.videoHeight - cropHeight, sourceY - cropHeight / 2));
    canvas.width = size; canvas.height = size;
    canvas.getContext('2d')?.drawImage(element, sx, sy, cropWidth, cropHeight, 0, 0, size, size);
    host.style.left = `${Math.max(8, Math.min(window.innerWidth - size - 8, clientX - size / 2))}px`;
    host.style.top = `${clientY > size + 36 ? clientY - size - 28 : clientY + 28}px`;
    host.style.display = 'block';
  }

  function hidePrecision() {
    if (magnifier.current) magnifier.current.style.display = 'none';
  }

  function clearHoldTimer() {
    if (holdTimer.current) clearTimeout(holdTimer.current);
    holdTimer.current = null;
  }

  function touchStart(event: React.TouchEvent<HTMLDivElement>) {
    if (phase !== 'live') return;
    if (mouseMode) {
      event.preventDefault();
      clearHoldTimer();
      if (mouseGesture.current?.dragging) sendMouse({ type: 'button', button: 'left', action: 'up' });
      hidePrecision();
      if (event.touches.length === 3) {
        const x = (event.touches[0].clientX + event.touches[1].clientX + event.touches[2].clientX) / 3;
        const y = (event.touches[0].clientY + event.touches[1].clientY + event.touches[2].clientY) / 3;
        mouseGesture.current = { kind: 'controls', lastX: x, lastY: y, startX: x, startY: y, started: performance.now(), moved: false };
      } else if (event.touches.length === 1) {
        const touch = event.touches[0];
        pointAtScreen(touch.clientX, touch.clientY);
        showPrecision(touch.clientX, touch.clientY);
        mouseGesture.current = {
          kind: 'track', lastX: touch.clientX, lastY: touch.clientY,
          startX: touch.clientX, startY: touch.clientY, started: performance.now(), moved: false
        };
        holdTimer.current = setTimeout(() => {
          const active = mouseGesture.current;
          if (active?.kind === 'track' && !active.moved) {
            active.held = true;
            navigator.vibrate?.(18);
          }
        }, 420);
      } else if (event.touches.length === 2) {
        const y = (event.touches[0].clientY + event.touches[1].clientY) / 2;
        mouseGesture.current = { kind: 'scroll', lastX: 0, lastY: y, startX: 0, startY: y, started: performance.now(), moved: false };
      }
      return;
    }
    if (event.touches.length === 2) {
      const [a, b] = [event.touches[0], event.touches[1]];
      const rect = event.currentTarget.getBoundingClientRect();
      gesture.current = {
        kind: 'pinch', startX: (a.clientX + b.clientX) / 2, startY: (a.clientY + b.clientY) / 2,
        startDistance: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY),
        startScale: viewTransform.current.scale,
        startTranslateX: viewTransform.current.x, startTranslateY: viewTransform.current.y,
        elementCenterX: rect.left + rect.width / 2, elementCenterY: rect.top + rect.height / 2
      };
    } else if (event.touches.length === 1 && viewTransform.current.scale > 1) {
      const touch = event.touches[0];
      gesture.current = {
        kind: 'pan', startX: touch.clientX, startY: touch.clientY,
        startScale: viewTransform.current.scale,
        startTranslateX: viewTransform.current.x, startTranslateY: viewTransform.current.y
      };
    }
  }

  function touchMove(event: React.TouchEvent<HTMLDivElement>) {
    if (mouseMode) {
      const activeMouse = mouseGesture.current;
      if (!activeMouse) return;
      event.preventDefault();
      if (activeMouse.kind === 'track' && event.touches.length === 1) {
        const touch = event.touches[0];
        activeMouse.lastX = touch.clientX; activeMouse.lastY = touch.clientY;
        if (Math.hypot(touch.clientX - activeMouse.startX, touch.clientY - activeMouse.startY) >= 8) {
          activeMouse.moved = true;
          if (activeMouse.held && !activeMouse.dragging) {
            activeMouse.dragging = true;
            sendMouse({ type: 'button', button: 'left', action: 'down' });
          }
        }
        pointAtScreen(touch.clientX, touch.clientY);
        showPrecision(touch.clientX, touch.clientY);
      } else if (activeMouse.kind === 'scroll' && event.touches.length === 2) {
        const y = (event.touches[0].clientY + event.touches[1].clientY) / 2;
        const delta = y - activeMouse.lastY;
        if (Math.abs(delta) >= 12) {
          activeMouse.moved = true;
          activeMouse.lastY = y;
          sendMouse({ type: 'scroll', dy: delta > 0 ? 1 : -1 });
        }
      } else if (activeMouse.kind === 'controls' && event.touches.length === 3) {
        const x = (event.touches[0].clientX + event.touches[1].clientX + event.touches[2].clientX) / 3;
        const y = (event.touches[0].clientY + event.touches[1].clientY + event.touches[2].clientY) / 3;
        if (Math.hypot(x - activeMouse.startX, y - activeMouse.startY) >= 12) activeMouse.moved = true;
      }
      return;
    }
    const active = gesture.current;
    if (!active) return;
    event.preventDefault();
    if (active.kind === 'pinch' && event.touches.length === 2 && active.startDistance) {
      const [a, b] = [event.touches[0], event.touches[1]];
      const centerX = (a.clientX + b.clientX) / 2;
      const centerY = (a.clientY + b.clientY) / 2;
      const ratio = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) / active.startDistance;
      const scale = Math.min(MAX_ZOOM, Math.max(1, active.startScale * ratio));
      const actualRatio = scale / active.startScale;
      applyView({
        scale,
        x: active.startTranslateX + (centerX - active.startX) +
          (1 - actualRatio) * (active.startX - active.elementCenterX! - active.startTranslateX),
        y: active.startTranslateY + (centerY - active.startY) +
          (1 - actualRatio) * (active.startY - active.elementCenterY! - active.startTranslateY)
      });
    } else if (active.kind === 'pan' && event.touches.length === 1) {
      const touch = event.touches[0];
      applyView({
        scale: active.startScale,
        x: active.startTranslateX + touch.clientX - active.startX,
        y: active.startTranslateY + touch.clientY - active.startY
      });
    }
  }

  function touchEnd() {
    if (mouseMode) {
      const activeMouse = mouseGesture.current;
      clearHoldTimer();
      hidePrecision();
      if (activeMouse?.dragging) {
        sendMouse({ type: 'button', button: 'left', action: 'up' });
      } else if (activeMouse && !activeMouse.moved) {
        if (activeMouse.kind === 'controls' && performance.now() - activeMouse.started < 500) revealFullViewControls();
        else if (activeMouse.kind === 'scroll' && performance.now() - activeMouse.started < 500) sendMouse({ type: 'click', button: 'right' });
        else if (activeMouse.kind === 'track') {
          sendMouse({ type: 'click', button: activeMouse.held ? 'right' : 'left' });
        }
      }
      mouseGesture.current = null;
      return;
    }
    sendServerView(viewTransform.current, true);
    gesture.current = null;
  }

  function touchCancel() {
    clearHoldTimer();
    hidePrecision();
    if (mouseGesture.current?.dragging) sendMouse({ type: 'button', button: 'left', action: 'up' });
    mouseGesture.current = null;
    gesture.current = null;
  }

  function teardownConnection() {
    touchCancel();
    const ws = socket.current;
    socket.current = null;
    if (ws) { ws.onclose = null; ws.onerror = null; ws.onmessage = null; ws.close(); }
    peer.current?.close();
    peer.current = null;
    if (heartbeat.current) clearInterval(heartbeat.current);
    if (deadline.current) clearTimeout(deadline.current);
    if (backgroundDeadline.current) clearTimeout(backgroundDeadline.current);
    if (controlsDeadline.current) clearTimeout(controlsDeadline.current);
    if (qualityMonitor.current) clearInterval(qualityMonitor.current);
    backgroundDeadline.current = null;
    controlsDeadline.current = null;
    qualityMonitor.current = null;
    if (video.current) { video.current.pause(); video.current.srcObject = null; }
    resetZoom();
  }

  function cleanup(text?: string, preserveResume = false) {
    teardownConnection();
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    reconnectTimer.current = null;
    reconnectAttempt.current = 0;
    if (!preserveResume) saveResumeToken(null);
    if (mounted.current) {
      setPhase('idle'); setPlayBlocked(false); setFocusView(false); setControlsVisible(false);
      setMouseAllowed(false); setMouseMode(false);
      if (text) setMessage(text);
    }
    document.body.style.overflow = '';
  }

  useEffect(() => {
    mounted.current = true;
    try {
      const savedQuality = localStorage.getItem('pocketpc-quality') as QualityPreset | null;
      if (savedQuality && ['auto', 'smooth', 'balanced', 'sharp'].includes(savedQuality)) changeQuality(savedQuality);
    } catch { /* unavailable */ }
    try { resumeToken.current = sessionStorage.getItem('pocketpc-resume'); } catch { /* unavailable */ }
    if (resumeToken.current && !location.hash) {
      scheduleReconnect('Restoring your approved PocketPC session…');
    }
    const visibility = () => {
      if (document.hidden) {
        if (!socket.current && !resumeToken.current) return;
        if (backgroundDeadline.current) clearTimeout(backgroundDeadline.current);
        backgroundDeadline.current = setTimeout(
          () => {
            if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type: 'stop' }));
            cleanup('The five-minute background limit ended sharing. Pair again to reconnect.');
          },
          BACKGROUND_GRACE_MS
        );
      } else {
        if (backgroundDeadline.current) clearTimeout(backgroundDeadline.current);
        backgroundDeadline.current = null;
        if (socket.current?.readyState === WebSocket.OPEN) {
          socket.current.send(JSON.stringify({ type: 'ping' }));
          setMessage('Returned within five minutes · restoring live view…');
          video.current?.play().catch(() => setPlayBlocked(true));
        } else if (resumeToken.current) {
          scheduleReconnect('Returned to PocketPC · restoring the approved session…');
        }
      }
    };
    document.addEventListener('visibilitychange', visibility);
    return () => {
      stopScanner(); mounted.current = false; cleanup(undefined, true);
      document.removeEventListener('visibilitychange', visibility);
    };
  }, []);

  useEffect(() => {
    const match = /^#pair=(\d{8})$/.exec(location.hash);
    if (!match || autoPairStarted.current) return;
    autoPairStarted.current = true;
    const pairingCode = match[1];
    history.replaceState(null, '', `${location.pathname}${location.search}`);
    setCode(pairingCode);
    setMessage('Secure QR recognized · connecting to your PC…');
    void connectWithCode(pairingCode);
  }, []);

  useEffect(() => {
    document.body.style.overflow = focusView ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [focusView]);

  useEffect(() => {
    const wakeNavigator = navigator as Navigator & { wakeLock?: { request: (kind: 'screen') => Promise<WakeLockHandle> } };
    async function acquireWakeLock() {
      if (phase !== 'live' || !keepAwake || document.hidden || !wakeNavigator.wakeLock || wakeLock.current) return;
      try {
        const lock = await wakeNavigator.wakeLock.request('screen');
        wakeLock.current = lock;
      } catch {
        // iOS may temporarily refuse while the web app is backgrounded.
      }
    }
    const visibility = () => {
      if (!document.hidden) void acquireWakeLock();
    };
    if (phase === 'live' && keepAwake) void acquireWakeLock();
    document.addEventListener('visibilitychange', visibility);
    return () => {
      document.removeEventListener('visibilitychange', visibility);
      const lock = wakeLock.current;
      wakeLock.current = null;
      if (lock && !lock.released) void lock.release();
    };
  }, [phase, keepAwake]);

  useEffect(() => {
    try { localStorage.setItem('pocketpc-keep-awake', String(keepAwake)); } catch { /* unavailable */ }
  }, [keepAwake]);

  useEffect(() => {
    try { localStorage.setItem('pocketpc-request-mouse', String(requestMouse)); } catch { /* unavailable */ }
  }, [requestMouse]);

  function startQualityMonitor(pc: RTCPeerConnection, ws: WebSocket) {
    if (qualityMonitor.current) clearInterval(qualityMonitor.current);
    let previousReceived = 0;
    let previousLost = 0;
    qualityMonitor.current = setInterval(async () => {
      if (qualityRef.current !== 'auto' || ws.readyState !== WebSocket.OPEN) return;
      try {
        const stats = await pc.getStats();
        let received = 0, lost = 0, rtt = 0;
        stats.forEach(report => {
          if (report.type === 'inbound-rtp' && report.kind === 'video') {
            received += report.packetsReceived ?? 0;
            lost += report.packetsLost ?? 0;
          }
          if (report.type === 'candidate-pair' && (report.nominated || report.selected)) {
            rtt = report.currentRoundTripTime ?? rtt;
          }
        });
        const receivedDelta = Math.max(0, received - previousReceived);
        const lostDelta = Math.max(0, lost - previousLost);
        previousReceived = received; previousLost = lost;
        const loss = lostDelta / Math.max(1, receivedDelta + lostDelta);
        const next = loss > .04 || rtt > .25 ? 'smooth' : loss < .01 && rtt > 0 && rtt < .09 ? 'sharp' : 'balanced';
        if (activeQualityRef.current !== next) {
          activeQualityRef.current = next;
          ws.send(JSON.stringify({ type: 'quality', preset: next }));
          setActiveQuality(next);
        }
      } catch {
        // Keep the last safe preset when Safari temporarily withholds stats.
      }
    }, 5000);
  }

  async function negotiate(ws: WebSocket, allowMouse: boolean) {
    // This private STUN endpoint reports Safari's Tailscale address. It is
    // bound to the Windows Tailscale adapter and is not a public relay.
    const pc = new RTCPeerConnection({
      iceServers: [{ urls: `stun:${location.hostname}:3478` }],
      bundlePolicy: 'max-bundle'
    });
    peer.current = pc;
    const transceiver = pc.addTransceiver('video', { direction: 'recvonly' });
    const codecs = RTCRtpReceiver.getCapabilities?.('video')?.codecs.filter(c => c.mimeType.toLowerCase() === 'video/h264');
    if (codecs?.length && transceiver.setCodecPreferences) transceiver.setCodecPreferences(codecs);
    pc.ontrack = async event => {
      if (!video.current || socket.current !== ws) return;
      video.current.srcObject = new MediaStream([event.track]);
      try { await video.current.play(); } catch { setPlayBlocked(true); }
    };
    pc.onconnectionstatechange = () => {
      if (socket.current !== ws) return;
      if (pc.connectionState === 'connected') {
        if (deadline.current) clearTimeout(deadline.current);
        reconnectAttempt.current = 0;
        setPhase('live');
        setMessage(allowMouse ? 'Encrypted view + mouse · approved on Windows' : 'Encrypted live view · approved on Windows');
        try {
          if (localStorage.getItem('pocketpc-gesture-guide') !== 'seen') setShowGestureGuide(true);
        } catch { setShowGestureGuide(true); }
        startQualityMonitor(pc, ws);
      } else if (pc.connectionState === 'disconnected') {
        setMessage('Live view paused · return within five minutes to resume.');
      } else if (['failed', 'closed'].includes(pc.connectionState)) {
        if (resumeToken.current) scheduleReconnect('Connection interrupted · reconnecting automatically…');
        else cleanup('Connection ended. Check Tailscale on both devices and pair again.');
      }
    };
    await pc.setLocalDescription(await pc.createOffer());
    if (pc.iceGatheringState !== 'complete') {
      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => { pc.removeEventListener('icegatheringstatechange', check); reject(new Error('ICE gathering timed out')); }, 12000);
        const check = () => {
          if (pc.iceGatheringState === 'complete') {
            clearTimeout(timeout); pc.removeEventListener('icegatheringstatechange', check); resolve();
          }
        };
        pc.addEventListener('icegatheringstatechange', check); check();
      });
    }
    if (socket.current !== ws || ws.readyState !== WebSocket.OPEN) return;
    // Keep UDP host/mDNS candidates plus the private Tailscale server-reflexive
    // candidate. Windows validates that the usable address is in 100.64/10.
    const sdp = pc.localDescription!.sdp.split('\r\n').filter(line => {
      if (!line.startsWith('a=candidate:')) return true;
      const fields = line.split(' ');
      return fields[2]?.toLowerCase() === 'udp' && ['host', 'srflx'].includes(fields[7]) && !fields[4]?.includes(':');
    }).join('\r\n');
    ws.send(JSON.stringify({ type: 'offer', sdp }));
  }

  async function connectWithCode(pairingCode: string) {
    if (!window.isSecureContext || location.protocol !== 'https:') {
      setMessage('Open the private Tailscale HTTPS address shown on Windows.'); return;
    }
    if (!/^\d{8}$/.test(pairingCode) || socket.current) return;
    setPhase('checking'); setMessage('Checking PocketPC and the private Tailscale route…');
    const controller = new AbortController();
    const healthTimeout = setTimeout(() => controller.abort(), 6000);
    try {
      const response = await fetch('/health', { cache: 'no-store', signal: controller.signal });
      const health = await response.json();
      if (!response.ok || health.status !== 'ready') throw new Error('PocketPC is not ready');
      if (health.session === 'busy') {
        setPhase('idle'); setMessage('Windows is already handling another request. Stop it there, then retry.'); return;
      }
    } catch {
      setPhase('idle'); setMessage('PocketPC did not answer the connection check. Confirm Tailscale and the Windows app are running.'); return;
    } finally {
      clearTimeout(healthTimeout);
    }
    setPhase('pending'); setMessage('Connection verified · waiting for explicit approval on Windows…');
    const ws = new WebSocket(`wss://${location.host}/ws`);
    socket.current = ws;
    deadline.current = setTimeout(() => cleanup('Connection timed out. Reload once, then retry with the current Windows code.'), 70000);
    ws.onopen = () => { ws.send(JSON.stringify({ type: 'pair', code: pairingCode, quality: qualityRef.current, mouseControl: requestMouse })); setCode(''); };
    ws.onerror = () => cleanup('Unable to connect. Check PocketPC and Tailscale on both devices.');
    ws.onclose = () => {
      if (resumeToken.current) scheduleReconnect('Connection interrupted · reconnecting automatically…');
      else cleanup('Windows ended sharing or the connection was lost. Pair again to reconnect.');
    };
    ws.onmessage = async event => {
      if (socket.current !== ws) return;
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'error') { cleanup(data.message); return; }
        if (data.type === 'mouse-disabled' || data.type === 'input-disabled') { setMouseAllowed(false); setMouseMode(false); setMessage(data.message); return; }
        if (data.type === 'approved') {
          if (typeof data.resumeToken === 'string') saveResumeToken(data.resumeToken);
          const approvedMouse = data.mouseControl === true;
          setMouseAllowed(approvedMouse);
          setPhase('connecting'); setMessage('Windows approved. Establishing encrypted video…');
          await negotiate(ws, approvedMouse);
        } else if (data.type === 'answer') {
          await peer.current?.setRemoteDescription({ type: 'answer', sdp: data.sdp });
          heartbeat.current = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
          }, 5000);
        }
      } catch {
        if (socket.current === ws) {
          if (resumeToken.current) scheduleReconnect('Video interrupted · reconnecting automatically…');
          else cleanup('Video negotiation failed. Check Windows, then pair again.');
        }
      }
    };
  }

  function scheduleReconnect(text: string) {
    if (!resumeToken.current) { cleanup('The reconnect period ended. Pair again from Windows.'); return; }
    teardownConnection();
    if (mounted.current) { setPhase('checking'); setMessage(text); }
    if (document.hidden || reconnectTimer.current) return;
    const delay = Math.min(1000 * 2 ** reconnectAttempt.current, 10000);
    reconnectAttempt.current += 1;
    reconnectTimer.current = setTimeout(() => {
      reconnectTimer.current = null;
      void resumeApprovedSession();
    }, delay);
  }

  async function resumeApprovedSession() {
    const token = resumeToken.current;
    if (!token || socket.current || document.hidden) return;
    try {
      const response = await fetch('/health', { cache: 'no-store', signal: AbortSignal.timeout(6000) });
      const health = await response.json();
      if (!response.ok || health.status !== 'ready' || health.session === 'busy') throw new Error('not ready');
    } catch {
      scheduleReconnect('Waiting for PocketPC and Tailscale · retrying automatically…');
      return;
    }
    const ws = new WebSocket(`wss://${location.host}/ws`);
    socket.current = ws;
    setPhase('connecting'); setMessage('Restoring the approved encrypted session…');
    deadline.current = setTimeout(() => {
      if (socket.current === ws) scheduleReconnect('Reconnect timed out · trying again…');
    }, 35000);
    ws.onopen = () => ws.send(JSON.stringify({ type: 'resume', token, quality: qualityRef.current }));
    ws.onerror = () => { if (socket.current === ws) scheduleReconnect('Private route unavailable · retrying automatically…'); };
    ws.onclose = () => { if (socket.current === ws) scheduleReconnect('Connection interrupted · retrying automatically…'); };
    ws.onmessage = async event => {
      if (socket.current !== ws) return;
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'resume-expired' || data.type === 'error') {
          cleanup(data.message || 'The reconnect period ended. Pair again.');
          return;
        }
        if (data.type === 'mouse-disabled' || data.type === 'input-disabled') { setMouseAllowed(false); setMouseMode(false); setMessage(data.message); return; }
        if (data.type === 'resumed') {
          if (typeof data.resumeToken !== 'string') throw new Error('missing resume token');
          saveResumeToken(data.resumeToken);
          const approvedMouse = data.mouseControl === true;
          setMouseAllowed(approvedMouse);
          setMessage('Approved session found · rebuilding encrypted video…');
          await negotiate(ws, approvedMouse);
        } else if (data.type === 'answer') {
          await peer.current?.setRemoteDescription({ type: 'answer', sdp: data.sdp });
          heartbeat.current = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
          }, 5000);
        }
      } catch {
        if (socket.current === ws) scheduleReconnect('Reconnect was interrupted · trying again…');
      }
    };
  }

  function disconnect() {
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type: 'stop' }));
    cleanup('Disconnected. Windows must approve the next session.');
  }

  function connect(event: React.FormEvent) {
    event.preventDefault();
    void connectWithCode(code);
  }

  function toggleFocusView() {
    if (controlsDeadline.current) clearTimeout(controlsDeadline.current);
    controlsDeadline.current = null;
    setControlsVisible(false);
    setFocusView(current => !current);
    requestAnimationFrame(() => resetZoom());
  }

  function revealFullViewControls() {
    if (!focusView) return;
    setControlsVisible(true);
    if (controlsDeadline.current) clearTimeout(controlsDeadline.current);
    controlsDeadline.current = setTimeout(() => {
      setControlsVisible(false);
      controlsDeadline.current = null;
    }, 3500);
  }

  const friendlyState = phase === 'live' ? `${tr('Connected', 'מחובר')} · ${activeQuality}` :
    phase === 'checking' ? tr('Reconnecting…', 'מתחבר מחדש…') : phase === 'pending' ? tr('Waiting for approval', 'ממתין לאישור') :
      phase === 'connecting' ? tr('Connecting securely…', 'מתחבר באופן מאובטח…') : tr('Private by default', 'פרטי כברירת מחדל');

  return <main className={`${phase === 'live' ? 'app viewing' : 'app'}${focusView ? ' focus-view' : ''}${controlsVisible ? ' controls-visible' : ''}${mouseMode ? ' mouse-mode' : ''}`}>
    <header>
      <a className="brand" href="/" aria-label="PocketPC home"><img className="brand-logo" src="/assets/pocketpc-icon.png" alt="" />Pocket<span>PC</span></a>
      <div className="header-actions"><span className="badge">TAILSCALE ONLY</span><button className="settings-button" type="button" onClick={() => setSettingsOpen(true)} aria-label={tr('Open PocketPC settings', 'פתיחת הגדרות PocketPC')}>{tr('Settings', 'הגדרות')}</button></div>
    </header>
    <section className="intro"><p className="eyebrow">WINDOWS → PHONE</p><h1>{isHebrew ? <>המחשב שלך,<br />קרוב מתמיד.</> : <>Your PC,<br />right within reach.</>}</h1><p className="subtitle">{tr('Private screen viewing that starts only when you approve.', 'צפייה פרטית במסך שמתחילה רק לאחר האישור שלך.')}</p></section>
    <section className="workspace" aria-label={tr('Screen viewer', 'מציג המסך')}>
      <div className="screen" onClick={() => { if (!mouseMode) revealFullViewControls(); }} onDoubleClick={() => { if (!mouseMode) zoom === 1 ? applyView({ scale: 2, x: 0, y: 0 }) : resetZoom(); }} onTouchStart={touchStart} onTouchMove={touchMove} onTouchEnd={touchEnd} onTouchCancel={touchCancel}>
        <video ref={video} autoPlay muted playsInline aria-label="Approved Windows display" />
        {phase !== 'live' && <div className="placeholder"><span className="monitor-icon" aria-hidden="true">▣</span><h2>{phase === 'idle' ? tr('Ready when you are', 'מוכן כשתהיה מוכן') : phase === 'checking' ? tr('Finding your PC', 'מחפש את המחשב שלך') : phase === 'pending' ? tr('Approve on Windows', 'יש לאשר ב-Windows') : tr('Opening your screen', 'פותח את המסך שלך')}</h2><p>{phase === 'idle' ? tr('Connect below. Your screen stays private until Windows approves.', 'התחבר למטה. המסך נשאר פרטי עד לאישור ב-Windows.') : phase === 'checking' ? tr('PocketPC is restoring the private connection.', 'PocketPC משחזר את החיבור הפרטי.') : tr('Nothing is shared until the Windows approval is accepted.', 'דבר אינו משותף עד לאישור ב-Windows.')}</p></div>}
        {playBlocked && <button className="play" onClick={async () => { try { await video.current?.play(); setPlayBlocked(false); } catch { setMessage('Tap once more to start your screen.'); } }}>{tr('Tap to show your screen', 'הקש להצגת המסך')}</button>}
        {showGestureGuide && phase === 'live' && !mouseMode && <div className="gesture-guide"><strong>{tr('Move around naturally', 'נווט בחופשיות')}</strong><span>{tr('Pinch to zoom · drag to move · double-tap to reset', 'צביטה לזום · גרירה להזזה · הקשה כפולה לאיפוס')}</span><button type="button" onClick={dismissGestureGuide}>{tr('Got it', 'הבנתי')}</button></div>}
      </div>
      <div className="viewer-bar">
        <span><i className={phase === 'live' ? 'dot live' : 'dot'} />{friendlyState}{phase === 'live' && zoom !== 1 ? ` · ${Math.round(zoom * 100)}%` : ''}</span>
        <div className="viewer-actions">{mouseAllowed && <button className={`quiet mouse-toggle${mouseMode ? ' active' : ''}`} disabled={phase !== 'live'} onClick={() => { resetZoom(); setMouseMode(current => !current); }}>{mouseMode ? tr('Exit mouse', 'יציאה מעכבר') : tr('Mouse', 'עכבר')}</button>}<button className="quiet" disabled={phase !== 'live' || zoom === 1 || mouseMode} onClick={resetZoom}>{tr('Reset view', 'איפוס תצוגה')}</button><button className="quiet" disabled={phase !== 'live'} onClick={toggleFocusView}>{focusView ? tr('Exit full view', 'יציאה ממסך מלא') : tr('Full view', 'מסך מלא')}</button></div>
      </div>
    </section>
    <div className="precision-magnifier" ref={magnifier} aria-hidden="true"><canvas ref={magnifierCanvas} /><i /></div>
    <section className="pairing">
      {phase === 'idle' ? <div className="friendly-pairing">
        <div><strong>{tr('Connect to your Windows PC', 'התחבר למחשב Windows שלך')}</strong><p>{tr('Use the camera for the quickest, safest connection.', 'השתמש במצלמה לחיבור המהיר והבטוח ביותר.')}</p></div>
        <button className="primary-connect" type="button" onClick={() => void startScanner()}><span className="scan-symbol" aria-hidden="true">▣</span> {tr('Scan PC QR', 'סריקת QR מהמחשב')}</button>
        <button className="manual-toggle" type="button" onClick={() => setManualPairing(current => !current)}>{manualPairing ? tr('Hide pairing code', 'הסתרת קוד צימוד') : tr('Enter code instead', 'הזנת קוד במקום')}</button>
        <label className="mouse-request"><input type="checkbox" checked={requestMouse} onChange={event => setRequestMouse(event.target.checked)} /><span><strong>{tr('Request mouse control', 'בקשת שליטה בעכבר')}</strong>{tr('Windows must approve it separately for this session.', 'Windows חייב לאשר זאת בנפרד להפעלה הזאת.')}</span></label>
        {manualPairing && <form className="manual-form" onSubmit={connect}><label className="sr-only" htmlFor="code">{tr('Eight-digit pairing code', 'קוד צימוד בן שמונה ספרות')}</label><div className="input-row"><input id="code" type="text" dir="ltr" inputMode="numeric" autoComplete="off" pattern="[0-9]{8}" maxLength={8} placeholder="00000000" value={code} onChange={event => setCode(event.target.value.replace(/\D/g, ''))} required /><button type="submit" disabled={code.length !== 8}>{tr('Connect', 'התחברות')} <span aria-hidden="true">→</span></button></div></form>}
      </div> : <div className="session-row"><div><strong>{phase === 'live' ? tr('Your screen is connected', 'המסך שלך מחובר') : phase === 'checking' ? tr('Restoring your screen', 'משחזר את המסך שלך') : phase === 'pending' ? tr('Approve this request on Windows', 'יש לאשר את הבקשה ב-Windows') : tr('Opening your screen securely', 'פותח את המסך באופן מאובטח')}</strong><p>{phase === 'live' ? tr('Tap Full view for a distraction-free display.', 'הקש על מסך מלא לתצוגה ללא הסחות.') : tr('Screen content remains private until Windows approves.', 'תוכן המסך נשאר פרטי עד לאישור ב-Windows.')}</p></div><div className="session-actions"><button className="disconnect" onClick={disconnect}>{tr('Disconnect', 'ניתוק')}</button></div></div>}
      <p className="status" role="status" aria-live="polite">{localizedMessage}</p>
    </section>
    {scannerOpen && <div className="scanner-modal" role="dialog" aria-modal="true" aria-label={tr('Scan PocketPC QR code', 'סריקת קוד QR של PocketPC')}><div className="scanner-card"><div className="scanner-copy"><strong>{tr('Scan the QR on Windows', 'סרוק את קוד ה-QR שב-Windows')}</strong><span>{tr('Point your phone at the PocketPC window. Connection starts automatically.', 'כוון את הטלפון לחלון PocketPC. החיבור יתחיל אוטומטית.')}</span></div><div className="scanner-view"><video ref={scannerVideo} muted playsInline aria-label={tr('QR scanner camera', 'מצלמת סריקת QR')} /><div className="scanner-guide" aria-hidden="true" /></div><canvas ref={scannerCanvas} hidden /><button type="button" onClick={stopScanner}>{tr('Cancel', 'ביטול')}</button></div></div>}
    {settingsOpen && <div className="settings-modal" role="dialog" aria-modal="true" aria-label={tr('PocketPC settings', 'הגדרות PocketPC')}><div className="settings-card"><div className="settings-heading"><div><strong>{tr('Settings', 'הגדרות')}</strong><span>{tr('Simple defaults that you can change anytime.', 'הגדרות פשוטות שניתן לשנות בכל עת.')}</span></div><button type="button" onClick={() => setSettingsOpen(false)} aria-label={tr('Close settings', 'סגירת הגדרות')}>×</button></div><label className="setting-select"><span>{tr('Language', 'שפה')}</span><select value={language} onChange={event => changeLanguage(event.target.value as Language)}><option value="en">English</option><option value="he">עברית</option></select></label><label className="setting-row"><div><strong>{tr('Keep phone awake', 'השארת הטלפון פעיל')}</strong><span>{tr('Prevent the screen from sleeping while connected.', 'מונע מהמסך להיכבות בזמן החיבור.')}</span></div><input type="checkbox" checked={keepAwake} onChange={event => setKeepAwake(event.target.checked)} /></label><label className="setting-select"><span>{tr('Screen quality', 'איכות המסך')}</span><select value={quality} onChange={event => changeQuality(event.target.value as QualityPreset)}><option value="auto">{tr('Automatic — recommended', 'אוטומטי — מומלץ')}</option><option value="smooth">{tr('Smooth', 'חלק')} · 720p</option><option value="balanced">{tr('Balanced', 'מאוזן')} · 900p</option><option value="sharp">{tr('Sharp', 'חד')} · 1080p</option></select></label><div className="setting-note"><strong>{tr('Automatic reconnection', 'חיבור מחדש אוטומטי')}</strong><span>{tr('PocketPC restores an approved session for up to five minutes after a brief interruption.', 'PocketPC משחזר חיבור מאושר עד חמש דקות לאחר הפרעה קצרה.')}</span></div><button className="settings-done" type="button" onClick={() => setSettingsOpen(false)}>{tr('Done', 'סיום')}</button></div></div>}
    <footer><span>{tr('◈ Encrypted with WebRTC + Tailscale', '◈ מוצפן באמצעות WebRTC ו-Tailscale')}</span><span>{tr('Mouse control is optional · Windows approval required', 'שליטה בעכבר אופציונלית · נדרש אישור ב-Windows')}</span></footer>
  </main>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
