# Node.js：libuv、流与背压

Node.js 把 ECMAScript/V8、Node C++ bindings、libuv、操作系统 I/O 和一套 JavaScript API 组合成服务器运行时。它的高并发能力来自非阻塞 I/O 与少量线程复用等待，而不是“所有操作都在一个线程完成”。文件系统、DNS、加密、压缩与用户 JavaScript 可能走完全不同的执行路径。

本文以 Node.js 26.5.0 API 与 libuv 1.x 官方文档为实现观察点。事件循环阶段、线程池使用者和默认值属于版本相关实现/API 契约；依赖它们的容量规划应在部署版本核验。

## 一次异步调用跨过哪些层 {#cross-layer-path}

以 TCP read 为例，概念路径是：

```text
JavaScript callback / Promise
  -> Node binding
  -> libuv handle/request
  -> epoll | kqueue | IOCP | event ports
  -> readiness/completion
  -> libuv loop callback
  -> JavaScript execution
```

网络 socket 通常由 loop 所在线程使用平台 I/O 机制轮询。文件系统 API 在 libuv 1.x 默认常由全局 thread pool 执行阻塞系统调用；`getaddrinfo`、`getnameinfo` 与 `uv_queue_work` 也共享该 pool。因而“异步 API”只说明调用方不等待，不说明底层没有线程或阻塞。

libuv 1.x thread pool 默认 4 个线程，可在进程启动前用 `UV_THREADPOOL_SIZE` 调整，且跨 event loop 共享。盲目增大：

- 可能提高独立阻塞工作的吞吐；
- 也增加线程栈、调度与下游并发；
- 无法加速 event-loop 上的 CPU JavaScript；
- 可能把瓶颈推到磁盘、DNS 或远端服务。

## Node event loop {#event-loop}

Node 的循环有 timers、pending callbacks、poll、check、close callbacks 等阶段；`setImmediate` 与 timer 的相对次序取决于它们从何处被安排。Promise reaction 与 `queueMicrotask` 使用 V8 microtask 机制，`process.nextTick` 还有 Node 专属队列。

```javascript
import { readFile } from "node:fs";
readFile(import.meta.filename, () => {
  setTimeout(() => console.log("timer"), 0);
  setImmediate(() => console.log("immediate"));
  queueMicrotask(() => console.log("microtask"));
  process.nextTick(() => console.log("nextTick"));
});
```

不要把某次打印顺序当成全部上下文的保证。稳定推理应只依赖文档明确的队列语义，并避免用 phase 巧合实现业务同步。

### 公平性预算

事件循环以协作方式运行 callback。若一个 callback 的工作量随不受信输入无界增长，它会推迟所有其他连接：

```javascript
function parseBatch(items, budget = 1000) {
  const chunk = items.splice(0, budget);
  for (const item of chunk) processItem(item);
  if (items.length) setImmediate(() => parseBatch(items, budget));
}
```

分批只是一种策略；更重的 CPU 工作应进入 worker thread/process 或专门服务。需要连同序列化、数据复制/转移和任务队列一起测量。

## Worker pool 与 Worker Threads {#workers}

区分两种“worker”：

- libuv thread pool 执行特定 Node/libuv native work，线程不运行普通应用 JavaScript；
- `node:worker_threads` 创建可并行执行 JavaScript 的 V8 isolate/线程，可通过 message、transferable 或 `SharedArrayBuffer` 交换数据。

worker thread 适合 CPU-intensive JavaScript；对 I/O-intensive 工作，内建异步 I/O 通常更直接。生产系统应复用 worker pool，而不是每个请求创建线程，并设：

- 有界任务队列；
- admission control；
- 超时/取消协议；
- worker 崩溃和未处理异常策略；
- payload 复制与共享内存一致性预算。

## Stream 是资源与流量协议 {#streams}

Node classic stream 有 `Readable`、`Writable`、`Duplex`、`Transform` 四类。它们不只提供 chunk API，还维护 buffer、状态、错误和结束协议。

### 背压

`writable.write(chunk)` 返回 `false` 表示内部 buffer 达到阈值，生产者应停止并等待 `'drain'`：

```javascript
import { once } from "node:events";
async function writeAll(writable, chunks) {
  for await (const chunk of chunks) {
    if (!writable.write(chunk)) await once(writable, "drain");
  }
  writable.end();
}
```

实际代码还应统一处理 `'error'`、close 与 premature termination；优先使用 `stream.pipeline`/Promise API，因为它把背压和错误传播编排在一起。

背压的本质是：

$$
\lambda_{\text{producer}} \leq \mu_{\text{consumer}}
$$

若长期到达率高于服务率，任何有限 buffer 最终都会满。扩大 `highWaterMark` 只能吸收 burst，并以 RSS 与尾延迟为代价，不能修复容量缺口。

### flowing 与 paused

Readable 既有 flowing/paused 模式，又有更细的 `readableFlowing` 状态。混用 `'data'`、`'readable'`、`pipe`、async iterator 和 `resume` 容易丢数据或积累 buffer。选一种消费风格贯穿 pipeline，并对对象模式的 `highWaterMark` 单位保持敏感：对象模式计对象数，字节模式计容量。

## 生命周期、取消与错误 {#lifecycle}

Promise 丢弃不会关闭 socket，AbortSignal 也只有底层 API 实际接入时才有效。服务请求应形成显式 scope：

```javascript
async function withDeadline(fn, ms, parentSignal) {
  const timeoutSignal = AbortSignal.timeout(ms);
  const signal = parentSignal
    ? AbortSignal.any([parentSignal, timeoutSignal])
    : timeoutSignal;
  return fn(signal);
}
```

这段实现依赖 Node 20.3.0 起提供的 `AbortSignal.any`；`fn` 仍必须把 signal 继续传给 `fetch`、timer、stream 或其他可取消操作。取消是协议，不是 Promise 的固有行为：若底层忽略 signal，调用方停止等待并不会终止工作。还要把超时与上游取消分别映射为可诊断错误，并观察底层任务最终结束。

资源错误处理至少覆盖：

- stream `'error'` 与 Promise rejection；
- half-close、peer reset、partial write；
- server shutdown 时停止接收、等待 in-flight、到期强制终止；
- unhandled rejection/uncaught exception 的进程策略；
- fd、socket、timer、listener 和 native handle 的清理。

## Async context {#async-context}

`AsyncLocalStorage` 让 request-scoped store 沿 callback 与 Promise chain 传播，类似 thread-local storage，但作用域建立于异步资源关系：

```javascript
import { AsyncLocalStorage } from "node:async_hooks";
const store = new AsyncLocalStorage();
function log(message) {
  console.log(store.getStore()?.requestId, message);
}
store.run({ requestId: "r-7" }, () => {
  Promise.resolve().then(() => log("done"));
});
```

自定义 thenable、错误封装的 callback API 或 native addon 可能丢 context，需要 `AsyncResource` 显式关联。context 中避免放大型对象；只要异步资源仍活跃，store 可能保持其可达。

## 容量与观测 {#capacity-observability}

至少同时观察：

| 层 | 信号 |
| --- | --- |
| event loop | utilization、delay/lag、long callback |
| libuv pool | 排队等待、活跃任务、不同工作类型竞争 |
| streams | buffered bytes/objects、`write(false)`、drain 时间 |
| process | RSS、heap used、external/array buffer、fd |
| dependencies | socket pool、DNS、磁盘与远端尾延迟 |
| worker threads | queue depth、任务时间、复制字节、worker 重启 |

Node 提供 `perf_hooks`、diagnostics channel、inspector、process reports 与 trace events；工具的开销和可见范围不同。JavaScript heap 看不到全部 native/external memory，RSS 增长必须跨层解释。

## 常见故障 {#failure-modes}

- 在 callback/Promise continuation 中执行超线性工作；
- 大量 `process.nextTick` 或 microtask 造成 I/O starvation；
- 忽略 `write()` 返回值，输出 buffer 无界增长；
- libuv pool 被慢文件/DNS/crypto 占满，表面看成“event loop 慢”；
- 每请求创建 worker/thread/process；
- `Promise.race` 后不取消 losing operations；
- 把 sync API 放进请求关键路径；
- listener/timer/closure 持有 request graph，形成可达性泄漏；
- 只看 V8 heap，不看 `external`、Buffer、native addon 与 fd。

## 继续阅读

- 语言 Job 与浏览器 event loop：见 [JavaScript](javascript.md)。
- TypeScript 模块解析与运行时映射：见 [TypeScript](typescript.md)。
- 容量推导与排障闭环：见[容量与系统化排障](../performance/capacity-troubleshooting.md)。

## Reference

- [Node.js 26.5.0：Event loop and worker pool](https://nodejs.org/en/learn/asynchronous-work/dont-block-the-event-loop)
- [Node.js 26.5.0：Streams](https://nodejs.org/api/stream.html)
- [Node.js 26.5.0：Worker threads](https://nodejs.org/api/worker_threads.html)
- [Node.js 26.5.0：Asynchronous context tracking](https://nodejs.org/api/async_context.html)
- [Node.js 26.5.0：Performance measurement APIs](https://nodejs.org/api/perf_hooks.html)
- [libuv 1.x：Design overview](https://docs.libuv.org/en/v1.x/design.html)
- [libuv 1.x：Thread pool work scheduling](https://docs.libuv.org/en/v1.x/threadpool.html)
- [libuv 1.x：Event loop API](https://docs.libuv.org/en/v1.x/loop.html)
- [Node.js source：event loop integration](https://github.com/nodejs/node/tree/v26.5.0)
