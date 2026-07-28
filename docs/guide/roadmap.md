# 学习路线

系统知识不是一条从“简单”到“复杂”的直线，而是一张围绕执行、存储、通信与协调展开的依赖图。下面给出一条主线和三条可按目标切换的支线。

## 主线：从一条指令到一次请求 {#main-route}

### 第一阶段：表示与执行

先建立不会频繁失效的底层模型：

1. [抽象、契约与性能](../foundations/abstractions-performance.md)
2. [数据表示与内存层次](../foundations/data-memory-hierarchy.md)
3. [ISA 与微架构](../architecture/isa-microarchitecture.md)
4. [流水线、ILP 与分支预测](../architecture/pipeline-ilp-branch.md)
5. [缓存与一致性](../architecture/cache-coherence.md)

退出条件不是能背流水线级数，而是能够解释：同一段源码为什么在不同数据布局、编译选项和核心拓扑下表现不同。

### 第二阶段：资源虚拟化

接着理解操作系统怎样把有限硬件变成稳定接口：

1. [进程与线程](../os/process-thread.md)
2. [调度](../os/scheduling.md)
3. [虚拟内存](../os/virtual-memory.md)
4. [I/O、中断与 DMA](../os/io-interrupt-dma.md)
5. [文件系统](../os/filesystem.md)

退出条件是能从一次系统调用画出用户态、内核、设备和返回路径，并区分阻塞时间、CPU 时间和设备服务时间。

### 第三阶段：并发与异步

并发部分按“正确性先于性能”的顺序学习：

1. [顺序、竞态与不变量](../concurrency/foundations.md)
2. [锁与条件变量](../concurrency/locks-condition-variables.md)
3. [原子操作与内存模型](../architecture/atomics-memory-model.md)
4. [协程](../concurrency/coroutines.md)
5. [异步与事件循环](../concurrency/async-event-loop.md)
6. [无锁算法与 RCU](../concurrency/lock-free-rcu.md)
7. [结构化并发](../concurrency/structured-concurrency.md)

退出条件是能为共享状态写出不变量、线性化点、取消路径和资源生命周期，而不仅是调用某个并发库。

### 第四阶段：通信与持久化

把单机状态扩展到网络和存储：

1. [分层与分组](../network/layers-packets.md)
2. [TCP、UDP 与 QUIC](../network/transport-tcp-udp-quic.md)
3. [拥塞控制](../network/congestion-control.md)
4. [Socket 与 I/O 模型](../network/sockets-io.md)
5. [SSD 与 NVMe](../storage/ssd-nvme.md)
6. [缓存、日志与崩溃一致性](../storage/caching-logging-consistency.md)

退出条件是能准确解释“发送成功”“写入成功”“提交成功”分别跨过了哪一个边界。

### 第五阶段：扩展与容错

最后研究工作拆分、通信和失败：

1. [Work、Span 与扩展定律](../parallel/performance-models.md)
2. [拓扑与通信](../parallel/topology-communication.md)
3. [时间、时钟与顺序](../distributed/time-order.md)
4. [复制与共识](../distributed/replication-consensus.md)
5. [事务与隔离](../distributed/transactions-isolation.md)
6. [可靠性与可观测性](../distributed/reliability-observability.md)

退出条件是能说清一个扩展方案减少了什么、增加了什么通信或协调成本，以及遇到部分失败时保留哪些保证。

## 三条目标支线 {#goal-routes}

### 系统程序员

优先顺序：

`C / C++ / Rust / Go → ABI 与链接 → 内存模型 → 虚拟内存 → I/O → 调试与剖析`

重点页面包括 [C](../languages/c.md)、[C++](../languages/cpp.md)、[Rust](../languages/rust.md)、[Go](../languages/go.md)、[WebAssembly](../languages/webassembly.md)、[链接、加载与 ABI](../tooling/linking-loading.md)和[性能剖析](../performance/profiling.md)。

### 后端与基础设施工程

优先顺序：

`运行时 → 并发 → Socket → TCP/QUIC → 存储 → 事务 → 可观测性`

重点不只是 API 使用，而是超时、重试、背压、幂等、队列和尾延迟的组合效应。

### 高性能与并行计算

优先顺序：

`缓存/NUMA → SIMD/SIMT → Work/Span → OpenMP → CUDA/MPI → 拓扑与集合通信`

每次优化都先写性能上界，再用 profiling 验证瓶颈是否真的位于计算、访存、同步或通信。

## 十二周实践节奏 {#twelve-weeks}

| 周 | 主题 | 可验证产出 |
| --- | --- | --- |
| 1 | 数据表示与汇编 | 对一个短函数解释对象布局、调用约定和反汇编 |
| 2 | 流水线与缓存 | 用基准展示局部性和分支可预测性的数量级差异 |
| 3 | 进程、线程与调度 | 追踪一次创建、阻塞、唤醒和上下文切换 |
| 4 | 虚拟内存 | 解释页表、TLB、缺页和写时复制 |
| 5 | 锁、原子与内存模型 | 为一个并发队列写出不变量和 happens-before |
| 6 | 协程与异步 I/O | 实现带取消、超时和有界背压的小型执行器 |
| 7 | IP、TCP 与 QUIC | 抓包解释握手、确认、重传和流量控制 |
| 8 | 文件系统与 SSD | 追踪一次写入直到持久化边界 |
| 9 | 性能测量 | 设计对照实验并生成可复现的 profiling 证据 |
| 10 | 并行计算 | 用 Work/Span 与实测加速比解释扩展瓶颈 |
| 11 | 复制、共识与事务 | 对故障时间线判断可见状态与恢复路径 |
| 12 | 全栈复盘 | 从一次慢请求完成跨层因果分析 |

## Reference

- [CMU 15-213: Introduction to Computer Systems](https://www.cs.cmu.edu/~213/)
- [MIT 6.1810: Operating System Engineering](https://pdos.csail.mit.edu/6.1810/2026/)
- [MIT 6.5840: Distributed Systems](https://pdos.csail.mit.edu/6.824/)
- [Berkeley CS 152: Computer Architecture and Engineering](https://inst.eecs.berkeley.edu/~cs152/)
- [Operating Systems: Three Easy Pieces](https://pages.cs.wisc.edu/~remzi/OSTEP/)
