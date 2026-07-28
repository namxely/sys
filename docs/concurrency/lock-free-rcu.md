# 无锁结构与 RCU

无锁算法用原子操作和重试替代互斥等待，RCU 则把“从结构移除”和“真正回收”分开，让读多写少结构的读路径极轻。二者的难点都不只在更新，而在弱内存序、进度与对象生命周期。

## 进度保证

| 保证 | 含义 |
| --- | --- |
| obstruction-free | 单独运行足够久的操作会完成 |
| lock-free | 整个系统持续有某个操作完成 |
| wait-free | 每个操作在有界自身步骤内完成 |

lock-free 不保证公平：一个线程可反复 CAS 失败。它也不保证低延迟：cache line 争夺、重试和内存回收可造成长尾。

## CAS 循环的结构

```text
old = load(state)
do:
  new = transform(old)
while !CAS(state, old, new)
```

正确性问题：

- `transform` 是否可安全重复；
- CAS 成功是不是线性化点；
- 失败后 `old` 怎样更新；
- 内存序是否发布/获取其他对象；
- 状态是否有 ABA；
- 旧对象何时回收。

把 mutex 改成 CAS 只解决“谁提交新 head”，没有自动解决剩余五项。

## 一个 SPSC 有界环形队列

单生产者只写 `tail_`，单消费者只写 `head_`；release 发布槽位内容，acquire 读取对方索引后访问槽位。它不支持多生产者或多消费者。

```cpp
#include <array>
#include <atomic>
#include <cstddef>
#include <optional>
#include <utility>
template<class T, std::size_t N>
class SpscQueue {
    static_assert(N >= 2);
    alignas(64) std::array<std::optional<T>, N> slots_;
    alignas(64) std::atomic<std::size_t> head_{0};
    alignas(64) std::atomic<std::size_t> tail_{0};
public:
    bool push(T value) {
        auto tail = tail_.load(std::memory_order_relaxed);
        auto next = (tail + 1) % N;
        if (next == head_.load(std::memory_order_acquire)) return false;
        slots_[tail].emplace(std::move(value));
        tail_.store(next, std::memory_order_release);
        return true;
    }
    std::optional<T> pop() {
        auto head = head_.load(std::memory_order_relaxed);
        if (head == tail_.load(std::memory_order_acquire)) return std::nullopt;
        std::optional<T> value{std::move(*slots_[head])};
        slots_[head].reset();
        head_.store((head + 1) % N, std::memory_order_release);
        return value;
    }
};
```

`alignas(64)` 是示例对目标平台的布局假设，不是跨平台 cache line 查询；可替换为实现提供的 interference size。队列容量实际是 $N-1$，空槽用于区分满与空。

### 为什么它正确

- producer 写 slot sequenced-before release tail；
- consumer acquire tail 读到发布索引后，可见 slot 构造；
- consumer reset slot sequenced-before release head；
- producer acquire head 后才能复用 slot；
- 单生产/单消费确保同一方索引无 CAS 竞争。

若扩展到 MPMC，单纯给 head/tail 加 CAS 不够：多个生产者可能同时写同一槽，通常需要每槽序列号等协议。

## ABA

Treiber stack 的 head 从地址 A 变 B 又变回 A，慢线程 CAS 可能成功，却把“同地址的新对象”当旧对象。地址复用让位模式相同，不代表对象身份相同。

常见策略：

- tagged pointer：版本与地址一起 CAS，仍要处理版本回绕；
- hazard pointer：reader 发布自己可能访问的指针，reclaimer 扫描后回收；
- epoch-based reclamation：所有活动 reader 越过 epoch 后回收；
- RCU grace period；
- GC 或引用计数；
- 不复用/延迟复用地址。

## hazard pointer

典型读取循环：

```text
repeat:
  p = head.load()
  hazard[me].store(p)
until p == head.load()
use p
hazard[me].store(nullptr)
```

删除者先把节点从结构中移除，再放入 retired list；只有扫描不到任何 hazard 指向它时才释放。hazard store 与验证的内存序必须按算法证明，扫描成本和线程注册也是设计的一部分。

## epoch 回收

reader 进入临界区时宣布当前 epoch，离开时标记 inactive。节点在 epoch $e$ 退休，只有所有可能在 $e$ 前看到它的 reader 都进入 quiescent state 后才能释放。

优点是 reader 操作少，批量回收高效；缺点是一个长期停顿的 reader 可以阻止大量内存回收。线程退出、暂停、嵌套和动态注册都需处理。

## RCU 的三步

Linux RCU 的核心：

1. **publish/remove**：以 RCU 原语更新指针，使新 reader 不再看到旧节点；
2. **grace period**：等待所有可能持有旧引用的既有 reader 越过 quiescent state；
3. **reclaim**：释放旧节点。

```c
rcu_read_lock();
p = rcu_dereference(global_ptr);
use(p);
rcu_read_unlock();

old = rcu_replace_pointer(global_ptr, new, lockdep_is_held(&update_lock));
synchronize_rcu();
kfree(old);
```

这是 Linux 内核 API 片段，不是用户态 C/C++。实际更新还需遵守对象不变量、锁上下文与具体 RCU flavor。

## RCU 为什么读快

经典内核 RCU reader 可避免共享计数器写和 cache line 争夺；updater 付出复制、发布、等待 grace period 与延迟回收成本。适合：

- 读极多、写较少；
- reader 临界区短；
- reader 可接受旧但自洽版本；
- 内存允许短期保留多个版本。

不适合所有结构。若更新频繁、对象巨大或 reader 长期阻塞，复制与积压可能主导。

## QSBR、SRCU 与不同 flavor

RCU 如何识别 quiescent state 取决于环境：

- scheduler/内核状态可帮助经典 RCU；
- userspace QSBR 由线程主动报告；
- SRCU 允许不同睡眠语义；
- preemptible RCU 处理可抢占 reader。

不能把一个 flavor 的“read side 可做什么”套给另一个。特别是阻塞、线程迁移、NMI/IRQ 和实时内核边界要查对应文档。

## 内存序与依赖

`rcu_assign_pointer` 发布已初始化对象，`rcu_dereference` 获取并维护编译器/CPU 所需的依赖与顺序。普通 load/store 替代它们，可能在弱序机器或编译优化下失效。

Linux 内核内存模型与 C++ 模型不同；用户态 RCU 库应使用其公开 API，不从内核宏复制实现。

## 测量

对比锁与无锁时必须包含：

- 单线程基线；
- 不同 producer/consumer 数；
- CAS failure/retry；
- cache-to-cache 传输；
- 公平与每线程完成分布；
- p99 操作延迟；
- retired memory 峰值和回收停顿；
- reader 被抢占/暂停后的影响；
- 同 socket 与跨 NUMA。

高吞吐但回收内存无限增长不是可接受结果。

## 失败模式

- “用了 atomic”就宣称 lock-free；
- 算法 lock-free，allocator/回收路径却拿全局锁；
- CAS 正确但有 ABA；
- 节点移除后立即 `delete`；
- 用 relaxed 原子发布对象图；
- 长 reader 阻止 epoch/RCU 回收；
- 假定 RCU reader 可以在任意 flavor 中睡眠；
- 只测总吞吐，掩盖线程饥饿；
- 将 SPSC 算法直接用于 MPSC/MPMC。

## 跨层连接

- 原子顺序和 CAS 见[原子与内存模型](../architecture/atomics-memory-model.md)；
- cache line 迁移见[缓存一致性](../architecture/cache-coherence.md)；
- 与传统互斥对比见[锁与条件变量](locks-condition-variables.md)；
- detached reader 生命周期应由[结构化并发](structured-concurrency.md)收束。

## Reference

- [Herlihy, Wait-Free Synchronization](https://doi.org/10.1145/114005.102808)
- [Michael, Hazard Pointers: Safe Memory Reclamation for Lock-Free Objects](https://doi.org/10.1109/TPDS.2004.8)
- [Fraser, Practical Lock-Freedom](https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-579.pdf)
- [Linux Kernel Documentation: What is RCU?](https://www.kernel.org/doc/html/latest/RCU/whatisRCU.html)
- [Linux Kernel Documentation: RCU Requirements](https://www.kernel.org/doc/html/latest/RCU/Design/Requirements/Requirements.html)
- [Linux Kernel Documentation: RCU Handbook](https://www.kernel.org/doc/html/latest/RCU/index.html)
- [Userspace RCU Project](https://liburcu.org/)
- [ISO C++ working draft: lock-free property](https://eel.is/c++draft/atomics.lockfree)
