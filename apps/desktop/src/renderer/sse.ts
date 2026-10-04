// SPDX-License-Identifier: GPL-3.0-only
//
// Server-Sent Events 的读取端。
//
// 为什么不用浏览器内置的 EventSource：它不能设置请求头，而 API 的令牌只能走
// `Authorization`（放进查询串会出现在服务端访问日志里）。所以这里用 fetch
// 拿到流自己解析 —— 顺带把重连策略也拿回自己手里。
//
// 这个文件只做协议解析，不碰业务类型，也不依赖 DOM 之外的东西 ——
// 所以能用普通 Node 直接跑测试（见 test/sse.test.mjs）。

/** 一条 SSE 消息。 */
export interface SseMessage {
  /** `event:` 字段，缺省是 `message`。 */
  event: string;
  /** `data:` 字段，多行按规范用换行拼接。 */
  data: string;
}

/** 事件块之间的空行。sse_starlette 用 CRLF，规范也允许 LF。 */
const EVENT_SEPARATOR = /\r?\n\r?\n/;

/** 断线后多久重连。 */
const RECONNECT_DELAY_MS = 1000;

/**
 * 解析一个事件块。
 *
 * 返回 `null` 表示这个块没有 `data`（比如纯心跳注释），调用方应跳过。
 */
export function parseEventBlock(block: string): SseMessage | null {
  let event = 'message';
  const data: string[] = [];

  for (const line of block.split(/\r?\n/)) {
    // 空行是块分隔（上游已切掉）；冒号开头是注释 —— sse_starlette 的心跳走这里
    if (line === '' || line.startsWith(':')) {
      continue;
    }
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    // 规范：冒号后紧跟的一个空格是分隔符，不算内容
    if (value.startsWith(' ')) {
      value = value.slice(1);
    }

    if (field === 'event') {
      event = value;
    } else if (field === 'data') {
      data.push(value);
    }
  }

  if (data.length === 0) {
    return null;
  }
  return { event, data: data.join('\n') };
}

/**
 * 增量解码器。
 *
 * 网络分片不保证落在事件边界上，所以半块要留着和下一个分片拼起来 ——
 * 这是最容易写错的地方，单独成类是为了能直接喂分片测。
 */
export class SseDecoder {
  private buffer = '';

  /** 喂一段文本，返回这次能凑出的完整消息。 */
  push(chunk: string): SseMessage[] {
    this.buffer += chunk;

    const messages: SseMessage[] = [];
    for (;;) {
      const match = EVENT_SEPARATOR.exec(this.buffer);
      if (match === null) {
        break;
      }
      const block = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);

      const message = parseEventBlock(block);
      if (message !== null) {
        messages.push(message);
      }
    }
    return messages;
  }
}

export interface SubscribeOptions {
  url: string;
  init: RequestInit;
  onMessage: (message: SseMessage) => void;
  /** 连接中断时调用。4xx 不会再重连，其他情况会。 */
  onError?: (error: unknown) => void;
}

/** 事件流返回了非 2xx。 */
export class SseHttpError extends Error {
  constructor(readonly status: number) {
    super(`事件流返回 ${status}`);
    this.name = 'SseHttpError';
  }
}

/**
 * 订阅一个 SSE 端点，断线自动重连。
 *
 * 返回取消订阅的函数。
 *
 * **4xx 不重连。** 令牌不对、路由不存在这类问题重试多少次都一样，
 * 硬重连只会变成每秒一次的日志轰炸。5xx 和网络中断才值得重试。
 */
export function subscribe(options: SubscribeOptions): () => void {
  const controller = new AbortController();
  let stopped = false;

  const pump = async (): Promise<void> => {
    while (!stopped) {
      try {
        await consume(options, controller.signal);
      } catch (error) {
        if (stopped) {
          return;
        }
        options.onError?.(error);
        if (error instanceof SseHttpError && error.status < 500) {
          return;
        }
      }
      if (stopped) {
        return;
      }
      await sleep(RECONNECT_DELAY_MS, controller.signal);
    }
  };

  void pump();

  return () => {
    stopped = true;
    controller.abort();
  };
}

/** 建立连接并一直读到断开。 */
async function consume(options: SubscribeOptions, signal: AbortSignal): Promise<void> {
  const response = await fetch(options.url, { ...options.init, signal });
  if (!response.ok) {
    throw new SseHttpError(response.status);
  }
  if (response.body === null) {
    throw new Error('事件流响应没有可读的 body');
  }

  const reader = response.body.getReader();
  const textDecoder = new TextDecoder();
  const decoder = new SseDecoder();

  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      return;
    }
    // stream: true —— 多字节字符可能被切在两个分片之间
    for (const message of decoder.push(textDecoder.decode(value, { stream: true }))) {
      options.onMessage(message);
    }
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}
