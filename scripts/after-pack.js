// electron-builder afterPack hook: drop Chromium files FreqEnforcer never uses.
//
// dxcompiler.dll + dxil.dll (~27 MB) are the DirectX shader compiler for
// WebGPU (Dawn's D3D12 backend). The app draws with Canvas 2D only; WebGL /
// ANGLE use d3dcompiler_47.dll, which stays.
const fs = require('fs');
const path = require('path');

const UNUSED = ['dxcompiler.dll', 'dxil.dll'];

exports.default = async function afterPack(context) {
  for (const name of UNUSED) {
    const file = path.join(context.appOutDir, name);
    if (fs.existsSync(file)) {
      fs.unlinkSync(file);
      console.log(`  • afterPack: removed ${name}`);
    }
  }
};
