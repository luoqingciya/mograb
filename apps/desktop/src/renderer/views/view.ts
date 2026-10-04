// SPDX-License-Identifier: GPL-3.0-only
//
// 视图的统一形状。
//
// 每个视图自己管自己的订阅和清理 —— 切换页面时 main.ts 只管调 dispose()，
// 不用知道里面订了什么。

export interface View {
  readonly element: HTMLElement;
  /** 离开这个视图时调用，用来退订、停定时器。 */
  dispose(): void;
}
