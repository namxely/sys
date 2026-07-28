# 比较语言，而不是比较语法

选择语言的困难不在于“谁更快”，而在于把需求翻译成可验证的语义约束。延迟敏感服务、命令行工具、浏览器应用、嵌入式固件与数据分析脚本，即使实现同一个算法，也会因为生命周期、部署边界和故障容忍度而得到不同答案。

## 共同坐标 {#common-coordinates}

### 值、对象与身份

先分清三个问题：

- **值语义**回答复制后是否得到独立状态；
- **引用语义**回答多个名字是否能观察同一可变状态；
- **对象身份**回答两个内容相等的实体是否仍可区分。

C++ 与 Rust 允许把复合值直接放在栈帧、另一个对象或连续容器中；Go 的值也可内联，但逃逸分析可能把其存储移到堆上；Python 与 JavaScript 的大多数复合对象通过引用访问。不要把“语法看起来像赋值”直接等同于机器级复制。

### 生命周期与资源 {#lifetime-models}

| 模型 | 主要机制 | 强项 | 需要防守的边界 |
| --- | --- | --- | --- |
| 显式管理 | `malloc/free`、句柄关闭 | 控制直接 | 泄漏、悬垂、重复释放 |
| 作用域管理 | C++ RAII、Rust `Drop` | 释放路径可预测 | 循环所有权、异常/`panic`/进程终止边界 |
| 引用计数 | CPython 引用计数、`Arc`/`shared_ptr` | 通常及时回收 | 环、原子计数争用、析构抖动 |
| 追踪式 GC | Go、JavaScript、Python 循环 GC | 表达共享图自然 | 暂停、吞吐、堆增长与终结器不确定性 |

内存回收不等于资源回收。文件描述符、锁、事务和网络流通常需要确定性的 `close`、`defer`、`with`、`using` 或 RAII；把它们交给终结器会让资源峰值取决于 GC 时机。

### 类型系统是静态近似 {#type-systems}

类型系统证明的是一组被选中的性质，而不是“程序正确”。可以沿这些轴比较：

- 名义类型或结构类型；
- 静态或动态检查；
- 空值、异常与代数数据类型如何表示失败；
- 泛型是单态化、字典传递、类型擦除，还是仅用于检查；
- 可变别名是否受到约束；
- FFI 是否能维持布局、调用约定与所有权契约。

TypeScript 明确采用结构兼容并有意保留若干不完备处；Rust 用所有权和借用排除安全代码中的悬垂引用与数据竞争；C++ 给予优化器更强的未定义行为假设；Go 则以较小的规范表面配合运行时检查和 GC。它们解决的不是同一个证明问题。

## 从源码到机器 {#execution-pipeline}

“编译型”和“解释型”过于粗糙。更精确的路径是：

```text
source
  -> parse / type check
  -> language IR or bytecode
  -> optimization / specialization / JIT
  -> machine code
  -> ABI + loader + runtime
```

C++、Go 与 Rust 通常在部署前生成本地机器码；CPython 通常生成并解释字节码，同时可做自适应特化；现代 JavaScript 引擎同时使用解释器与多层 JIT；TypeScript 通常擦除类型后把 JavaScript 交给宿主。启动延迟、稳态吞吐、代码体积和可预测性由整条路径共同决定。

## 并发不是一种能力 {#concurrency-taxonomy}

至少区分：

- **并发结构**：任务如何创建、组合、取消和等待；
- **执行并行度**：同一时刻有多少核真正执行用户代码；
- **内存顺序**：写入何时能被其他执行单元观察；
- **阻塞模型**：阻塞调用占住协程、运行时线程还是 OS 线程；
- **背压**：生产者是否能感知消费者容量。

异步函数也可能执行 CPU 密集循环并阻塞事件循环；goroutine 很轻，但无界创建仍会积累栈、定时器和保留对象；线程安全容器也不能自动保证跨多步业务不变量。

对于稳定系统，优先建立结构化生命周期：

```text
request scope
├── deadline / cancellation
├── child tasks
├── bounded queues
└── cleanup joined before scope exits
```

这比争论“线程还是协程”更接近真正的可靠性问题。

## 成本模型 {#cost-model}

端到端时间可以粗略拆成：

$$
T = T_{\text{work}} + T_{\text{queue}} + T_{\text{sync}} + T_{\text{runtime}} + T_{\text{kernel}} + T_{\text{io}}
$$

语言主要影响前四项，但硬件、内核与负载形态可能占主导。选择时记录：

| 约束 | 应验证的量 |
| --- | --- |
| 尾延迟 | p50/p95/p99/p99.9，暂停与排队分解 |
| 吞吐 | 单核效率、扩展曲线、饱和点 |
| 内存 | 活跃集、峰值 RSS、分配率、碎片 |
| 启动 | 冷启动、模块加载、JIT 预热 |
| 交付 | 产物大小、动态依赖、目标平台 |
| 运维 | 栈回溯、profile、trace、崩溃转储可用性 |

任何跨语言基准都必须先固定算法、输入、正确性、并发度、热身、编译选项和资源上限；否则测到的常常是库选择或运行模式，而不是语言。

## 一个可执行的选择流程 {#decision-process}

1. 写出不可妥协的语义约束：实时性、内存安全、ABI、浏览器、生态协议。
2. 写出失败路径：取消、超时、部分写、OOM、panic/exception、进程退出。
3. 画出跨层关键路径：语言调用到运行时、系统调用、网络或设备。
4. 用生产形态的最小垂直切片测量，不先写全系统。
5. 把实现版本与测量环境写入结果；升级后重测。
6. 评估团队能否长期维护边界代码，而不只看首版开发速度。

### 常见误判

- “没有 GC 就没有暂停”：分页、调度、锁竞争和异常展开同样会暂停进度。
- “有 GC 就不会泄漏”：可达但无用的缓存、监听器和 goroutine 仍然泄漏。
- “async 就更快”：它主要改善等待期间的可复用性，不减少计算工作。
- “类型更多就更安全”：FFI、`unsafe`、断言、反射与运行时输入仍需验证。
- “零成本抽象没有成本”：含义是相对手写等价实现不额外付费，前提与代码生成仍要检查。

## 继续阅读

- 需要直面抽象机、对象表示与系统 ABI：从 [C](c.md) 开始，再进入 [C++](cpp.md) 或 [Rust](rust.md)。
- 需要理解托管运行时、JIT 与内存模型：进入 [Java 与 JVM](java-jvm.md)。
- 需要大量并发任务与运行时调度：进入 [Go](go.md)、[Python](python.md) 或 [Node.js](nodejs.md)。
- 需要理解浏览器/服务端 JavaScript：先读 [JavaScript](javascript.md)，再读 [TypeScript](typescript.md) 与 [Node.js](nodejs.md)。
- 需要可验证的跨语言低层目标与能力化宿主接口：进入 [WebAssembly](webassembly.md)。
- 需要验证代码生成与机器接口：进入[编译器流水线](../tooling/compiler-pipeline.md)和[链接、加载与 ABI](../tooling/linking-loading.md)。
- 需要做可靠比较：进入[基准设计](../performance/benchmarking.md)。

## Reference

- [ISO C++ working draft: object model and abstract machine](https://eel.is/c++draft/intro)
- [The Go Programming Language Specification](https://go.dev/ref/spec)
- [The Rust Reference](https://doc.rust-lang.org/reference/)
- [Python Language Reference: Data model](https://docs.python.org/3/reference/datamodel.html)
- [ECMAScript Language Specification](https://tc39.es/ecma262/)
- [TypeScript: Type Compatibility](https://www.typescriptlang.org/docs/handbook/type-compatibility)
- [Node.js: Event loop and worker pool](https://nodejs.org/en/learn/asynchronous-work/dont-block-the-event-loop)
