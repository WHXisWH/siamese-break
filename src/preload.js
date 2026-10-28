const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('catBreak', {
  done: () => ipcRenderer.send('cat:done')
});
