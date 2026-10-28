const cats = require('./src/cats.json');

const id = process.env.CAT_VARIANT || 'siamese';
const cat = cats[id];
if (!cat) throw new Error(`unknown CAT_VARIANT: ${id}`);

module.exports = {
  appId: cat.appId,
  productName: cat.productName,
  copyright: 'WHXisWH',
  extraMetadata: {
    name: cat.packageName,
    version: cat.version,
    catVariant: id
  },
  files: [
    'src/**/*',
    'package.json',
    `assets/cats/${id}/**/*`
  ],
  directories: {
    output: `dist/${id}`
  },
  win: {
    icon: `assets/cats/${id}/icon.ico`,
    artifactName: `${cat.productName}-${cat.version}-\${arch}-\${target}.\${ext}`
  },
  nsis: {
    oneClick: true,
    perMachine: false,
    runAfterFinish: true,
    createDesktopShortcut: false,
    createStartMenuShortcut: true,
    shortcutName: cat.displayName,
    artifactName: `${cat.productName}-Setup-${cat.version}.\${ext}`
  },
  portable: {
    artifactName: `${cat.productName}-Portable-${cat.version}.\${ext}`
  }
};
