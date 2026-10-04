// SPDX-License-Identifier: GPL-3.0-only
//
// 构建前置步骤：把不需要编译的静态资源搬进 dist/。
//
// HTML 和 CSS 不参与 tsc 编译，但 Electron 加载的是 dist/ 下的产物，
// 所以得拷一份过去。
//
// 这里**不改 package.json 的版本号**。试过让构建脚本把仓库根的 VERSION 写进去，
// 但那会让 package-lock.json 里的版本对不上，`npm ci` 有风险。
// 版本改由打包时通过 `--config.extraMetadata.version` 传；
// 界面上要显示版本就读后端 `/health` —— 那才是唯一来源。

import { cp, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const appRoot = join(here, '..');

const STATIC_FILES = ['index.html', 'styles.css'];

const target = join(appRoot, 'dist', 'renderer');
await mkdir(target, { recursive: true });
for (const name of STATIC_FILES) {
  await cp(join(appRoot, 'src', 'renderer', name), join(target, name));
}
console.log(`[build] 已拷贝 ${STATIC_FILES.join('、')} 到 dist/renderer/`);
