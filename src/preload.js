const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('siamese', {
  done: () => ipcRenderer.send('cat:done')
});
