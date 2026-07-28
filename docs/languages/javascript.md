# JavaScript：ECMAScript 与宿主事件循环

JavaScript 异步模型常被压缩成“单线程事件循环”，这会混淆三套契约：ECMAScript 定义语言、execution context 与 Job；浏览器由 HTML Standard 定义 task 和 microtask 的调度；Node.js 又把 ECMAScript 接到 libuv。正确推理必须先指出宿主。

本文以 ECMAScript 2026 年度规范为稳定语言基准，以 WHATWG HTML Living Standard 在 2026-07-28 可核验版本描述浏览器宿主。引擎对象布局、JIT 层级和 GC 算法不是 ECMAScript 保证。

## 值、对象与属性 {#values-objects}

ECMAScript 值分为语言类型；Object 是属性集合并有内部 slots。变量绑定存在于 Environment Record，execution context 保存当前 Realm、词法环境和代码执行状态。

```javascript
const proto = {
  describe() { return `id=${this.id}`; }
};
const item = Object.create(proto);
Object.defineProperty(item, "id", {
  value: 7,
  writable: false,
  enumerable: true,
  configurable: false
});
console.log(item.describe());
```

属性访问的语义包含：

- own property descriptor；
- prototype chain；
- data property 与 accessor property；
- `[[Get]]`、`[[Set]]` 等内部方法；
- Proxy 对内部方法的拦截及其 invariant。

“对象就是哈希表”最多是某个阶段的实现类比。引擎可用 hidden class/shape、inline cache 和 elements backing store，但这些布局不是规范接口，改变对象形状是否变慢应在具体引擎版本测量。

### 闭包捕获的是绑定

```javascript
const fs = [];
for (let i = 0; i < 3; i++) fs.push(() => i);
console.log(fs.map(f => f())); // [0, 1, 2]
```

`let` 的循环语义可为每次迭代创建新的词法绑定；闭包观察绑定，不是把某个寄存器字节机械复制进去。`var` 的函数作用域会得到不同结果。

## execution context、Realm 与 Job {#execution-context}

一个 ECMAScript agent 在任一时刻至多有一个正在执行的 execution context；函数调用会压栈新的 context，generator/async 可挂起后恢复。Realm 提供一套全局对象和 intrinsic，因此跨 iframe/VM realm 的 `instanceof` 可能因构造器身份不同而失败。

Promise reaction 通过 Job 调度。ECMAScript 规定 Job 必须在没有其他运行 context 时执行，并运行到完成；具体何时排队和如何与 I/O、timer 交错，由宿主 hook 决定。

```javascript
console.log("sync-1");
Promise.resolve().then(() => console.log("job"));
console.log("sync-2");
// sync-1, sync-2, job
```

`then` handler 不会插入当前调用栈中间；它作为后续 Job 执行。这是 run-to-completion 的核心，也是长同步任务会延迟所有 Promise continuation 的原因。

## 浏览器：task 与 microtask {#browser-event-loop}

HTML event loop 选择一个 runnable task 执行；完成后，在规定的 microtask checkpoint 执行 microtask queue，随后可能渲染。Promise reaction 与 `queueMicrotask` 使用 microtask；timer、事件和许多 I/O callback 由不同 task source 排队。

```javascript
console.log("A");
setTimeout(() => console.log("timer"), 0);
queueMicrotask(() => console.log("microtask"));
Promise.resolve().then(() => console.log("promise"));
console.log("B");
// A, B, microtask, promise, timer
```

`setTimeout(..., 0)` 表示达到最小延迟后有资格排队，不保证立刻执行。task source 之间的选择和 timer clamp 也受宿主规则影响。

### microtask starvation

```javascript
function spin() {
  queueMicrotask(spin);
}
spin();
```

每个 microtask 又加入一个 microtask，checkpoint 可能长期无法清空，timer、输入与渲染被饿死。异步不代表公平；必须主动把无限工作切成有界批次，并在需要时让出到 task/render 边界。

## Promise 是结果组合，不是工作线程 {#promises}

Promise 表示未来 settlement，executor 在构造时同步调用：

```javascript
const p = new Promise(resolve => {
  console.log("executor");
  resolve(1);
});
p.then(x => console.log("then", x));
console.log("after");
```

顺序是 `executor`、`after`、`then 1`。`async` function 返回 Promise，`await` 把后续代码注册为恢复逻辑；它不会自动把前面的 CPU 工作移出当前 agent。

组合器表达不同故障协议：

- `Promise.all`：任一拒绝后返回的 Promise 拒绝，但其他底层工作不自动取消；
- `allSettled`：等待全部结果；
- `race`：采用第一个 settled；
- `any`：采用第一个 fulfilled，否则聚合拒绝。

取消必须由 API 另行支持，例如 `AbortSignal`。丢弃 Promise 不等于终止 fetch、worker 或设备操作。

```javascript
async function getJSON(url, signal) {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
```

deadline 应创建 controller、安排 abort，并在 `finally` 清理 timer；还要决定 abort 后是否能安全重试，以及响应体是否已部分消费。

## 共享内存与 Atomics {#shared-memory}

普通 JavaScript 对象不在 worker 间直接共享；结构化克隆或 transferable 通常转移/复制数据。`SharedArrayBuffer` 允许多个 agent 访问同一数据块，`Atomics` 提供原子操作与同步语义。

```javascript
const shared = new SharedArrayBuffer(Int32Array.BYTES_PER_ELEMENT);
const flag = new Int32Array(shared);
Atomics.store(flag, 0, 1);
Atomics.notify(flag, 0);
```

共享内存把程序带入真正的 memory model。复合不变量仍需协议；原子 flag 不能让旁边非共享对象跨 agent 可见，也不能替代消息生命周期。浏览器主线程对阻塞 `Atomics.wait` 有限制，应采用适合宿主的 wait API。

## 实现层：解释、特化与 JIT {#implementation}

现代引擎可采用解释器、baseline compiler、optimizing compiler 和 deoptimization。常见过程是：

```text
source -> parse -> bytecode/baseline
       -> profile feedback -> speculative optimized code
       -> guard failure -> deopt
```

这只是实现家族，不是规范。优化可能依赖：

- call site 的 receiver shape；
- 数值是否保持 small integer/double；
- property access 是否单态；
- array elements kind；
- escape analysis 与 allocation sinking。

微基准容易只测到热身、常量折叠或某一 guard。性能结论必须绑定 V8/SpiderMonkey/JavaScriptCore 版本、启动参数、宿主与工作集，并同时测冷启动和稳态。

## 错误与性能边界 {#performance-failures}

### 正确性

- 当前结论属于 ECMAScript，还是浏览器/Node 宿主？
- Promise 拒绝是否被观察，组合器失败后底层工作是否仍在运行？
- listener、timer、closure 是否维持大型对象可达？
- microtask 是否无界递归，阻塞渲染和 task？
- 共享内存是否使用 `Atomics` 建立顺序？
- 跨 Realm 是否错误依赖 `instanceof`？

### 性能

- 长 task 应按输入规模设预算并分批；
- 分配率与 retained heap 要分开，使用 heap snapshot 验证引用链；
- I/O 并发需要上限，否则连接、buffer 和 callback queue 会先饱和；
- JIT benchmark 要做热身、随机化顺序并防止 dead-code elimination；
- 浏览器关注 INP/long tasks，服务端关注 event-loop lag 与尾延迟。

## 继续阅读

- 浏览器之外的宿主实现：见 [Node.js](nodejs.md)。
- 类型检查如何叠加而不改变运行时：见 [TypeScript](typescript.md)。
- 事件循环与协程对照：见 [Python](python.md)。

## Reference

- [ECMAScript 2026 Language Specification](https://tc39.es/ecma262/2026/)
- [ECMAScript: Execution Contexts](https://tc39.es/ecma262/2026/multipage/executable-code-and-execution-contexts.html#sec-execution-contexts)
- [ECMAScript: Jobs](https://tc39.es/ecma262/2026/multipage/executable-code-and-execution-contexts.html#sec-jobs)
- [ECMAScript: Memory Model](https://tc39.es/ecma262/2026/multipage/memory-model.html)
- [WHATWG HTML: Event loops](https://html.spec.whatwg.org/multipage/webappapis.html#event-loops)
- [WHATWG HTML: Microtask queuing](https://html.spec.whatwg.org/multipage/timers-and-user-prompts.html#microtask-queuing)
- [WHATWG DOM: AbortController](https://dom.spec.whatwg.org/#interface-abortcontroller)
- [ECMAScript: Promise objects](https://tc39.es/ecma262/2026/multipage/control-abstraction-objects.html#sec-promise-objects)
