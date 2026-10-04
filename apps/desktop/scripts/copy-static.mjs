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

import { cp, mkdir, writeFile } from 'node:fs/promises';
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

// 渲染层是 ESM，但包根没有 "type": "module"（主进程是 CommonJS）。
// 放一个只声明 type 的 package.json，Node 就知道这些 .js 该怎么解析 ——
// 否则跑测试时会警告「检测到模块语法，按 ESM 重新解析」。
// Electron 通过 <script type="module"> 加载，不受这个文件影响。
await writeFile(join(target, 'package.json'), '{\n  "type": "module"\n}\n', 'utf-8');

console.log(`[build] 已拷贝 ${STATIC_FILES.join('、')} 到 dist/renderer/`);
