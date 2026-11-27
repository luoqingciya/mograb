// SPDX-License-Identifier: GPL-3.0-only
//
// 构建前置步骤：把不需要编译的静态资源搬进 dist/。
//
// HTML 和 CSS 不参与 tsc 编译，Tauri 从 frontendDist（../dist）加载页面，
// 所以将 index.html、styles.css 拷贝到 dist/ 根下，保证 ./renderer/main.js
// 与 ../shared/types.js 的相对路径一致。

import { cp, mkdir, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const appRoot = join(here, '..');

const STATIC_FILES = ['index.html', 'styles.css'];

const distRoot = join(appRoot, 'dist');
await mkdir(distRoot, { recursive: true });
for (const name of STATIC_FILES) {
  await cp(join(appRoot, 'src', 'renderer', name), join(distRoot, name));
}

// dist/ 下的 renderer 与 shared 都是 ESM，放一个只声明 type 的 package.json，
// Node 执行 test/*.test.mjs 时按 ESM 解析 dist/renderer/*.js，不依赖包根的声明。
await writeFile(join(distRoot, 'package.json'), '{\n  "type": "module"\n}\n', 'utf-8');

console.log(`[build] 已拷贝 ${STATIC_FILES.join('、')} 到 dist/`);
