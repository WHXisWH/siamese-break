const { app, BrowserWindow, Tray, Menu, nativeImage, screen, ipcMain, powerMonitor, dialog } = require('electron');
const path = require('path');
const fs = require('fs');

const catId = require('../package.json').catVariant || process.env.CAT_VARIANT || 'siamese';
const cat = require('./cats.json')[catId];
const catDir = path.join(__dirname, '..', 'assets', 'cats', catId);

const DEFAULTS = {
  intervalMinutes: 30,
  durationSeconds: 60,
  pauseMinutes: 60,
  compatMode: false,
  initialized: false
};

const settingsFile = path.join(app.getPath('userData'), 'settings.json');

function loadSettings() {
  try {
    return { ...DEFAULTS, ...JSON.parse(fs.readFileSync(settingsFile, 'utf8')) };
  } catch {
    return { ...DEFAULTS };
  }
}

function saveSettings() {
  try {
    fs.mkdirSync(path.dirname(settingsFile), { recursive: true });
    fs.writeFileSync(settingsFile, JSON.stringify(settings, null, 2));
  } catch {}
}

const settings = loadSettings();
const debugIntervalSeconds = Number(process.env.CAT_INTERVAL_SECONDS) || 0;
const durationSeconds = Number(process.env.CAT_DURATION_SECONDS) || settings.durationSeconds;

if (settings.compatMode) app.disableHardwareAcceleration();

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) app.quit();

let tray = null;
let catWindow = null;
let nextAt = 0;
let pausedUntil = 0;
let ticker = null;
let intervalWindow = null;

const INTERVAL_PRESETS = [15, 20, 30, 45, 60, 90, 120];
const MIN_INTERVAL = 1;
const MAX_INTERVAL = 480;

function intervalMs() {
  return debugIntervalSeconds ? debugIntervalSeconds * 1000 : settings.intervalMinutes * 60 * 1000;
}

function resetTimer() {
  pausedUntil = 0;
  nextAt = Date.now() + intervalMs();
  refreshTray();
}

function formatMinutes(minutes) {
  if (minutes % 60 === 0) return `${minutes / 60} 小时`;
  if (minutes > 60) return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟`;
  return `${minutes} 分钟`;
}

function setIntervalMinutes(minutes) {
  const value = Math.round(Number(minutes));
  if (!Number.isFinite(value) || value < MIN_INTERVAL || value > MAX_INTERVAL) return false;
  settings.intervalMinutes = value;
  saveSettings();
  if (!catWindow) resetTimer();
  refreshTray();
  return true;
}

function intervalMenu() {
  const current = settings.intervalMinutes;
  const isPreset = INTERVAL_PRESETS.includes(current);
  return [
    ...INTERVAL_PRESETS.map((minutes) => ({
      label: `每 ${formatMinutes(minutes)}`,
      type: 'radio',
      checked: minutes === current,
      click: () => setIntervalMinutes(minutes)
    })),
    { type: 'separator' },
    {
      label: isPreset ? '自定义…' : `自定义…（现在是每 ${formatMinutes(current)}）`,
      type: 'radio',
      checked: !isPreset,
      click: () => openIntervalWindow()
    }
  ];
}

function openIntervalWindow() {
  if (intervalWindow) {
    intervalWindow.focus();
    return;
  }
  intervalWindow = new BrowserWindow({
    width: 380,
    height: 230,
    resizable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    alwaysOnTop: true,
    title: `${cat.displayName} · 多久出现一次`,
    icon: path.join(catDir, 'icon.png'),
    show: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js') }
  });
  intervalWindow.setMenuBarVisibility(false);
  intervalWindow.loadFile(path.join(__dirname, 'interval.html'), {
    query: { current: String(settings.intervalMinutes), min: String(MIN_INTERVAL), max: String(MAX_INTERVAL) }
  });
  intervalWindow.once('ready-to-show', () => intervalWindow && intervalWindow.show());
  intervalWindow.on('closed', () => {
    intervalWindow = null;
    refreshTray();
  });
}

ipcMain.handle('settings:interval', (event, minutes) => {
  const ok = setIntervalMinutes(minutes);
  if (ok && intervalWindow) intervalWindow.close();
  return ok;
});

function pause() {
  pausedUntil = Date.now() + settings.pauseMinutes * 60 * 1000;
  nextAt = pausedUntil;
  refreshTray();
}

function formatClock(ts) {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function minutesLeft() {
  return Math.max(0, Math.ceil((nextAt - Date.now()) / 60000));
}

function loginItemOptions() {
  const exe = process.env.PORTABLE_EXECUTABLE_FILE;
  return exe ? { path: exe } : {};
}

function isOpenAtLogin() {
  return app.getLoginItemSettings(loginItemOptions()).openAtLogin;
}

function setOpenAtLogin(enabled) {
  app.setLoginItemSettings({ ...loginItemOptions(), openAtLogin: enabled });
}

function statusLabel() {
  if (catWindow) return '猫猫正在卖萌中…';
  if (pausedUntil > Date.now()) return `已暂停，${formatClock(pausedUntil)} 猫猫再来`;
  return `下一只猫猫：${formatClock(nextAt)}（还有 ${minutesLeft()} 分钟）`;
}

function refreshTray() {
  if (!tray) return;
  tray.setToolTip(`${cat.displayName}\n${statusLabel()}`);
  const paused = pausedUntil > Date.now();
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: statusLabel(), enabled: false },
    { type: 'separator' },
    { label: '现在就召唤猫猫', click: () => showCat() },
    paused
      ? { label: '取消暂停', click: () => resetTimer() }
      : { label: `暂停 ${settings.pauseMinutes / 60} 小时`, click: () => pause() },
    { type: 'separator' },
    { label: `多久出现一次（每 ${formatMinutes(settings.intervalMinutes)}）`, submenu: intervalMenu() },
    {
      label: '开机自动启动',
      type: 'checkbox',
      checked: isOpenAtLogin(),
      click: (item) => { setOpenAtLogin(item.checked); refreshTray(); }
    },
    {
      label: '兼容模式（猫猫背景变黑时勾选）',
      type: 'checkbox',
      checked: settings.compatMode,
      click: (item) => {
        settings.compatMode = item.checked;
        saveSettings();
        app.relaunch();
        app.exit(0);
      }
    },
    { type: 'separator' },
    { label: '退出', click: () => app.quit() }
  ]));
}

function createTray() {
  const icon = nativeImage.createFromPath(path.join(catDir, 'tray.png'));
  tray = new Tray(icon);
  tray.on('click', () => tray.popUpContextMenu());
  tray.on('double-click', () => showCat());
  refreshTray();
}

function showCat() {
  if (catWindow) return;
  const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const area = display.workArea;

  catWindow = new BrowserWindow({
    x: area.x,
    y: area.y,
    width: area.width,
    height: area.height,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    hasShadow: false,
    alwaysOnTop: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      backgroundThrottling: false
    }
  });

  catWindow.setAlwaysOnTop(true, 'screen-saver');
  catWindow.setVisibleOnAllWorkspaces(true);
  catWindow.setMenuBarVisibility(false);

  catWindow.loadFile(path.join(__dirname, 'overlay.html'), {
    query: {
      duration: String(durationSeconds),
      interval: String(settings.intervalMinutes),
      video: `../assets/cats/${catId}/cat.webm`,
      align: cat.align
    }
  });

  catWindow.once('ready-to-show', () => {
    if (!catWindow) return;
    catWindow.show();
    catWindow.focus();
  });

  const safety = setTimeout(() => {
    if (catWindow) catWindow.close();
  }, (durationSeconds + 10) * 1000);

  catWindow.on('closed', () => {
    clearTimeout(safety);
    catWindow = null;
    resetTimer();
  });

  refreshTray();
}

ipcMain.on('cat:done', (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (win) win.close();
});

function onBackToDesk() {
  if (!catWindow && pausedUntil <= Date.now()) resetTimer();
}

function tick() {
  if (!catWindow && Date.now() >= nextAt) {
    pausedUntil = 0;
    showCat();
  }
  refreshTray();
}

app.on('second-instance', () => showCat());

app.on('window-all-closed', () => {});

app.whenReady().then(() => {
  if (!gotLock) return;

  if (!settings.initialized) {
    settings.initialized = true;
    saveSettings();
    if (app.isPackaged) setOpenAtLogin(true);
  }

  createTray();
  resetTimer();
  ticker = setInterval(tick, debugIntervalSeconds ? 1000 : 15000);

  powerMonitor.on('resume', onBackToDesk);
  powerMonitor.on('unlock-screen', onBackToDesk);

  if (process.argv.includes('--cat-now')) showCat();
  if (process.argv.includes('--interval-settings')) openIntervalWindow();
});

app.on('before-quit', () => {
  if (ticker) clearInterval(ticker);
});

process.on('uncaughtException', (err) => {
  dialog.showErrorBox(`${cat.displayName}出错了`, String(err && err.stack || err));
});
