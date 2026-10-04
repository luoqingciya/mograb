// SPDX-License-Identifier: GPL-3.0-only
//
// 后端 sidecar 管理。
//
// Desktop 不是独立实现的下载器，它只是一个壳：真正的活由 mograb-api 干。
// 所以启动流程是「先确保 API Server 活着，再加载界面」（规划书 §34）。
//
// 打包后 API 是同目录下的 mograb-api.exe（electron-builder 放在 resources/backend/）；
// 开发时直接用仓库里的 uv 环境跑。

import { type ChildProcess, spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';

import { app } from 'electron';

const HOST = '127.0.0.1';
const PORT = 48721;
const HEALTH_TIMEOUT_MS = 20_000;
const HEALTH_POLL_MS = 300;
const TOKEN_TIMEOUT_MS = 5_000;

export const API_BASE_URL = `http://${HOST}:${PORT}/api/v1`;
export const HEALTH_URL = `http://${HOST}:${PORT}/health`;

let child: ChildProcess | null = null;

/** 后端是否已经就绪。 */
export async function isBackendReady(): Promise<boolean> {
  try {
    const response = await fetch(HEALTH_URL, {
      signal: AbortSignal.timeout(2000),
    });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * 后端的运行目录 —— 也就是它解析出的数据目录的父级。
 *
 * 后端的 ``data_dir()`` 规则是「冻结时跟可执行文件、开发时跟 cwd」，
 * 而这里 spawn 时的 cwd 正好就是这两种情况下的运行目录。
 */
function backendRunDir(): string {
  if (app.isPackaged) {
    return join(process.resourcesPath, 'backend');
  }
  // 开发时从 dist/main/ 往上四层就是仓库根
  return join(__dirname, '..', '..', '..', '..');
}

/** 解析要跑的命令。 */
function resolveCommand(): { command: string; args: string[]; cwd: string } {
  const cwd = backendRunDir();

  if (app.isPackaged) {
    const exe = join(cwd, 'mograb-api.exe');
    if (!existsSync(exe)) {
      throw new Error(`找不到后端程序：${exe}`);
    }
    return { command: exe, args: [], cwd };
  }

  return {
    command: 'uv',
    args: ['run', '--project', cwd, 'mograb-api'],
    cwd,
  };
}

/**
 * 读后端的 API 令牌。
 *
 * 令牌由后端启动时生成在 ``<数据目录>/token``。这里不自己生成 ——
 * 生成规则只有一份（在 mograb.config.token 里），两处各写一份迟早会走样。
 *
 * 之所以要轮询：端口打开和令牌写盘之间理论上可能有窗口，虽然 ``run()``
 * 里已经把生成提到 bind 之前，多等几毫秒换一个确定的失败信息是划算的。
 */
async function readToken(): Promise<string> {
  const path = join(backendRunDir(), 'data', 'token');
  const deadline = Date.now() + TOKEN_TIMEOUT_MS;

  for (;;) {
    try {
      const token = (await readFile(path, 'utf-8')).trim();
      if (token !== '') {
        return token;
      }
    } catch {
      // 还没写出来，下面继续等
    }
    if (Date.now() >= deadline) {
      throw new Error(`读不到 API 令牌：${path}。删掉它重启即可重新生成。`);
    }
    await new Promise((resolve) => setTimeout(resolve, HEALTH_POLL_MS));
  }
}

/**
 * 确保后端在跑，返回它暴露的接口信息。
 *
 * 如果端口上已经有一个（比如开发时手动 `mog server start` 过），就直接用它 ——
 * 重复拉起只会因为端口占用而失败。
 */
export async function startBackend(): Promise<BackendInfo> {
  if (await isBackendReady()) {
    console.log('[backend] 已有实例在运行，直接使用');
    return { baseUrl: API_BASE_URL, token: await readToken() };
  }

  const { command, args, cwd } = resolveCommand();
  console.log(`[backend] 启动：${command} ${args.join(' ')}`);

  child = spawn(command, args, {
    cwd,
    env: { ...process.env, MOGRAB_SERVER__HOST: HOST, MOGRAB_SERVER__PORT: String(PORT) },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });

  child.stdout?.on('data', (chunk: Buffer) => {
    process.stdout.write(`[backend] ${chunk.toString()}`);
  });
  child.stderr?.on('data', (chunk: Buffer) => {
    process.stderr.write(`[backend] ${chunk.toString()}`);
  });
  child.on('exit', (code) => {
    console.log(`[backend] 进程退出，code=${code}`);
    child = null;
  });

  await waitForHealth();
  return { baseUrl: API_BASE_URL, token: await readToken() };
}

export interface BackendInfo {
  baseUrl: string;
  token: string;
}

/** 轮询健康检查直到就绪或超时。 */
async function waitForHealth(): Promise<void> {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (await isBackendReady()) {
      console.log('[backend] 就绪');
      return;
    }
    if (child === null) {
      throw new Error('后端进程启动后立刻退出了，看上面的日志');
    }
    await new Promise((resolve) => setTimeout(resolve, HEALTH_POLL_MS));
  }
  throw new Error(`等待后端就绪超时（${HEALTH_TIMEOUT_MS}ms）`);
}

/** 关掉我们自己拉起来的后端。外部已有的实例不动。 */
export function stopBackend(): void {
  if (child === null) {
    return;
  }
  console.log('[backend] 停止');
  child.kill();
  child = null;
}
