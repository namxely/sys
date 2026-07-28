# 缓存与一致性

私有缓存让核心以低延迟访问热点数据，却产生一个矛盾：多个缓存可以持有同一物理地址的副本，写入后谁拥有最新值？缓存一致性协议解决单个地址副本的传播与串行化问题；它不自动提供程序所需的跨地址顺序。

## 先区分三个概念

- **cache consistency/coherence**：对同一位置的写入形成所有观察者认可的顺序，写入最终传播。
- **memory consistency model**：不同位置的 load/store 允许怎样排序。
- **language memory model**：哪些程序无数据竞争，哪些同步建立 happens-before。

因此“机器有 MESI，所以普通变量跨线程可见”是错误推论。C++ 中并发非原子读写仍可能构成 data race 和未定义行为。

## cache line 是协议粒度

处理器通常按 line 填充、驱逐和追踪一致性。即使线程 A 写 `x`、线程 B 写旁边的 `y`，只要二者在同一 line，协议仍会来回转移整条 line 的写权限，这就是 false sharing。

line 大小和层次包含关系依处理器而变；软件应通过平台接口或测量确认，不把常见的 64 B 当成跨架构保证。

## 目录与监听

### snooping

共享总线或广播互连上，各缓存监听一致性事务。设计直观，但广播流量随核心数增长。

### directory

目录记录哪些缓存可能持有 line，把请求定向到相关节点。它更可扩展，但需要目录存储、路由和并发事务状态。

现代系统可混合使用分层 snoop filter、目录与片上网络。MESI 是理解状态转换的模型，不应据此断言某款芯片的完整协议。

## MESI 状态机

常见抽象状态：

- **M, Modified**：本缓存持有唯一且已修改副本；
- **E, Exclusive**：唯一、干净副本；
- **S, Shared**：可能有多个干净副本；
- **I, Invalid**：不可使用。

核心读取 I 状态 line 时发起读请求，得到 S 或 E；写 S line 时必须先获得独占权限，使其他副本失效；M line 被其他核心读取时，拥有者需提供或回写新数据。

一个简化转换：

```text
CPU load miss: I --GetS--> S/E
CPU store hit: E --------> M
CPU store:     S --GetM--> M, invalidate sharers
remote GetS:  M ---------> S, supply data
remote GetM:  S/E/M -----> I, transfer ownership
```

真实协议还要处理瞬态状态、竞争请求、重试、写回缓冲和非一致性设备。

## store buffer 与 invalidate queue

若每次 store 都等独占权限到达，核心会频繁停顿。store buffer 允许本核心先继续执行，协议在后台完成；invalidate queue 也可延迟处理失效。这些优化会让其他核心观察到与程序顺序不同的跨地址次序，因此 ISA 需要定义 fence 与原子语义。

本核心通常通过 store-to-load forwarding 读到自己尚未传播的 store。于是“我刚写后马上读到了”不能证明其他核心已看到。

## false sharing 实验

下面的 C++20 程序比较相邻原子计数器和 cache-line 隔离计数器。它只测目标实现；`std::hardware_destructive_interference_size` 是实现建议值。

```cpp
#include <atomic>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <new>
#include <thread>
struct Packed { std::atomic<std::uint64_t> x{0}, y{0}; };
struct alignas(std::hardware_destructive_interference_size) Cell {
    std::atomic<std::uint64_t> v{0};
};
struct Split { Cell x, y; };
template<class X, class Y>
double run(X x, Y y) {
    constexpr std::uint64_t n = 20'000'000;
    auto t0 = std::chrono::steady_clock::now();
    std::jthread a([&] { for (std::uint64_t i = 0; i < n; ++i) x().fetch_add(1, std::memory_order_relaxed); });
    std::jthread b([&] { for (std::uint64_t i = 0; i < n; ++i) y().fetch_add(1, std::memory_order_relaxed); });
    a.join(); b.join();
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
}
int main() {
    Packed p;
    Split s;
    std::cout << run([&]() -> auto& { return p.x; }, [&]() -> auto& { return p.y; }) << '\n';
    std::cout << run([&]() -> auto& { return s.x.v; }, [&]() -> auto& { return s.y.v; }) << '\n';
}
```

测量时绑定两个线程到不同物理核心，并分别测试同 socket、跨 socket、SMT sibling。否则调度迁移可能淹没一致性成本。`relaxed` 仍保证每个计数器修改的原子性，只是不额外建立跨对象顺序。

## 一致性流量的性能形状

### 真共享

多个核心确实读写同一状态，例如全局队列 head。原子 RMW 会串行争夺 line，吞吐最终由所有权转移延迟限制。将计数分片、批量合并或改变所有权模型常比更换原子内存序更有效。

### false sharing

逻辑独立数据共享物理 line。对齐/填充、按线程分区或改变布局可缓解；但填充会增加容量与 TLB 成本。

### 只读共享

初始化后只读的数据可在多个缓存中保持 Shared，扩展性通常良好。发布过程仍需正确同步，不能依赖“之后不再写”弥补初始化 data race。

## NUMA 与一致性

NUMA 系统既要进行 cache coherence，也有不同内存节点延迟。一次远端访问可能因：

- 数据物理页在远端；
- line 当前由远端核心持有 Modified；
- 线程迁移后工作集仍留在旧节点；
- 目录或互连拥塞。

`numactl --hardware`、线程/内存绑定和 uncore 计数器可帮助区分。仅看 LLC miss 无法判断数据来自本地 DRAM、远端 cache 还是远端 DRAM。

## DMA 与非 CPU 代理

设备 DMA 是否与 CPU cache 完全硬件一致，取决于平台互连和 DMA API。Linux 驱动必须使用平台 DMA mapping 接口表达所有权和同步；把普通虚拟地址直接交给设备或手工假设 cache flush 规则都不可移植。

一致性也不意味着设备操作与 CPU 普通 load/store 自动按程序所需排序。MMIO 和 DMA 还涉及设备内存属性、I/O barrier 与完成协议，参见 [I/O、中断与 DMA](../os/io-interrupt-dma.md)。

## 如何诊断

1. 用源代码和 profile 找高频共享写；
2. 记录对象地址与 cache line 映射；
3. 固定线程到物理核心，改变核心距离；
4. 比较单线程、同核、同 socket、跨 socket；
5. 使用目标 CPU 的 HITM、snoop 或 cache-to-cache 事件；
6. 尝试分片或 padding 作为因果对照；
7. 检查容量、TLB 和内存占用是否回归。

工具事件名称和可解释性依平台。Linux `perf c2c` 在部分硬件上能帮助定位 cache-to-cache 共享，但不保证所有处理器都提供足够信息。

## 失败模式

- 把 coherence 当 sequential consistency；
- 用 `volatile` 修复线程可见性；
- 对齐对象却让动态数组元素仍共享 line；
- 只 padding 字段，忽略分配器把多个对象放在同一 line；
- 原子 RMW 使用更弱内存序后期待消除所有权争夺；
- 看到 LLC miss 就断言访问 DRAM；
- 忽略 SMT、NUMA、设备和 I/O coherence；
- 使用未文档化 cache flush 指令处理持久化，却没有持久化域模型。

## 跨层连接

- line 填充与数据布局来自 [内存层次](../foundations/data-memory-hierarchy.md)；
- fence 和原子语义参见 [原子与内存模型](atomics-memory-model.md)；
- 线程放置由 [CPU](cpu.md) 与 [操作系统调度](../os/scheduling.md) 共同决定；
- [锁、条件变量](../concurrency/locks-condition-variables.md) 和 [无锁/RCU](../concurrency/lock-free-rcu.md) 都要支付不同形状的一致性成本。

## Reference

- [Papamarcos and Patel, A Low-Overhead Coherence Solution for Multiprocessors with Private Cache Memories](https://doi.org/10.1145/800015.808204)
- [Sorin, Hill, and Wood, A Primer on Memory Consistency and Cache Coherence](https://pages.cs.wisc.edu/~markhill/papers/primer2020_2nd_edition.pdf)
- [Intel 64 and IA-32 Architectures Optimization Reference Manual](https://www.intel.com/content/www/us/en/developer/articles/technical/intel64-and-ia32-architectures-optimization.html)
- [Arm Neoverse CMN-700 Technical Reference Manual](https://developer.arm.com/documentation/101408/latest/)
- [Linux perf c2c manual](https://www.man7.org/linux/man-pages/man1/perf-c2c.1.html)
- [Linux Dynamic DMA Mapping Guide](https://www.kernel.org/doc/html/latest/core-api/dma-api-howto.html)
