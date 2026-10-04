// SPDX-License-Identifier: GPL-3.0-only
//
// 极简 DOM 辅助。
//
// 桌面端没引框架 —— 页面不多，手写 DOM 够用，也省掉一层打包。
// 但 `document.createElement` 写起来太啰嗦，包一层。

type Child = Node | string | null | undefined;

export type Attrs = Record<string, string | number | boolean | EventListener | undefined>;

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Attrs = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === false) {
      continue;
    }
    if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'class') {
      node.className = String(value);
    } else if (value === true) {
      node.setAttribute(key, '');
    } else {
      node.setAttribute(key, String(value));
    }
  }
  append(node, children);
  return node;
}

export function append(parent: HTMLElement, children: Child[]): void {
  for (const child of children) {
    if (child === null || child === undefined) {
      continue;
    }
    parent.append(typeof child === 'string' ? document.createTextNode(child) : child);
  }
}

export function replace(container: HTMLElement, ...children: Child[]): void {
  container.replaceChildren();
  append(container, children);
}

/** 取元素，取不到就抛 —— 模板写错时早点炸，别留个 null 到处传。 */
export function requireElement<T extends HTMLElement>(selector: string): T {
  const found = document.querySelector<T>(selector);
  if (found === null) {
    throw new Error(`页面里找不到元素: ${selector}`);
  }
  return found;
}
