const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('catBreak', {
  done: () => ipcRenderer.send('cat:done'),
  setIntervalMinutes: (minutes) => ipcRenderer.invoke('settings:interval', minutes)
});
