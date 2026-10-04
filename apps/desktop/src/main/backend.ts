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
import { join } from 'node:path';

import { app } from 'electron';

const HOST = '127.0.0.1';
const PORT = 48721;
const HEALTH_TIMEOUT_MS = 20_000;
const HEALTH_POLL_MS = 300;

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

/** 解析要跑的命令。 */
function resolveCommand(): { command: string; args: string[]; cwd: string } {
  if (app.isPackaged) {
    const exe = join(process.resourcesPath, 'backend', 'mograb-api.exe');
    if (!existsSync(exe)) {
      throw new Error(`找不到后端程序：${exe}`);
    }
    return { command: exe, args: [], cwd: join(process.resourcesPath, 'backend') };
  }

  // 开发时从 dist/main/ 往上四层就是仓库根
  const repoRoot = join(__dirname, '..', '..', '..', '..');
  return {
    command: 'uv',
    args: ['run', '--project', repoRoot, 'mograb-api'],
    cwd: repoRoot,
  };
}

/**
 * 确保后端在跑。
 *
 * 如果端口上已经有一个（比如开发时手动 `mog server start` 过），就直接用它 ——
 * 重复拉起只会因为端口占用而失败。
 */
export async function startBackend(): Promise<void> {
  if (await isBackendReady()) {
    console.log('[backend] 已有实例在运行，直接使用');
    return;
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
