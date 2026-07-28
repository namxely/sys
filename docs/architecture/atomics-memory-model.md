# 原子与内存模型

多核机器、编译器和语言运行时都可能重排独立操作。内存模型不要求所有线程看见一个全局程序顺序，而是定义哪些观察结果允许出现，以及同步操作怎样建立跨线程的 happens-before。

## 为什么“最终会写入内存”不够

```cpp
int data = 0;
bool ready = false;
// thread A: data = 42; ready = true;
// thread B: if (ready) use(data);
```

在 C++ 中，这里对 `ready` 和 `data` 的并发非原子访问构成 data race，程序行为未定义。问题不只是 cache 没刷新：编译器可以重排、合并或删除访问，CPU 也有 store buffer、speculation 和弱排序规则。

正确同步必须同时约束：

1. 编译器变换；
2. ISA 可见顺序；
3. cache coherence 下的传播；
4. 对象生命周期和访问原子性。

## 三种关系

### sequenced-before

同一线程内由语言规则给出的顺序。

### synchronizes-with

特定原子、锁或线程生命周期操作之间的跨线程边。例如 release store 被 acquire load 读到。

### happens-before

由 sequenced-before 与 synchronizes-with 的传递闭包构成。若两个冲突的非原子访问没有 happens-before 且至少一个是写，就发生 data race。

内存模型首先是正确性图，而不是“插几条 fence”的清单。

## 原子性与顺序是两件事

`std::atomic<T>` 防止该对象的单次原子操作被撕裂，并为它提供 modification order。内存序决定它与周围操作建立多强的顺序。

| C++ 内存序 | 核心用途 | 不提供什么 |
| --- | --- | --- |
| `relaxed` | 原子计数、唯一编号 | 跨对象同步 |
| `release` store | 发布此前写入 | 约束之后操作 |
| `acquire` load | 获取发布前写入 | 单独发布自己的此前操作 |
| `acq_rel` RMW | 同时获取与发布 | 全局单一顺序 |
| `seq_cst` | 加入全局 SC 顺序 | 自动修复非原子 data race |

## release/acquire 发布

```cpp
#include <atomic>
#include <cassert>
#include <thread>
int payload;
std::atomic<bool> ready{false};
int main() {
    std::thread producer([] {
        payload = 42;
        ready.store(true, std::memory_order_release);
    });
    std::thread consumer([] {
        while (!ready.load(std::memory_order_acquire)) {}
        assert(payload == 42);
    });
    producer.join();
    consumer.join();
}
```

consumer 的 acquire load 读到 producer release store 的值，建立 synchronizes-with；`payload=42` 因而 happens-before `payload` 的读取。把两端都改成 relaxed 会失去这条跨对象边。

## release sequence 与 RMW

多个线程可通过原子 read-modify-write 延续同一修改序列。它对于引用计数、队列和信号量很重要，但规则细致且随语言标准表述演化。实现算法时应证明每次 acquire 究竟读取哪个 release 或其 release sequence，而不是说“这里有原子所以可见”。

## fence 的配对对象

fence 本身不神奇地同步所有线程。它要通过某个原子对象的读写关系连接：

```text
thread A: ordinary writes -> release fence -> atomic store
thread B: atomic load -> acquire fence -> ordinary reads
```

load 必须读取对应 store 或其修改序列中的值，才能建立所需关系。多数应用代码优先把 acquire/release 直接放在原子操作上，更易审计。

## litmus test: store buffering

初始 `x=y=0`：

```text
Thread 0          Thread 1
x = 1             y = 1
r0 = y            r1 = x
```

若全是 relaxed 原子，`r0=0, r1=0` 在 C++ 模型中允许，弱排序硬件可直接出现，x86 也可因 store buffer 允许 Store→Load 重排而出现。coherence 只要求每个单独地址的写顺序，不禁止这个跨地址结果。

使用 seq_cst 原子会把操作纳入单一总顺序，排除两边都读到 0 的结果。具体 fence 指令由编译器针对 ISA 选择。

## compare-exchange 循环

CAS 会在失败时更新 `expected`，并可能发生 spurious failure（weak 版本）。正确的原子最大值：

```cpp
#include <atomic>
void update_max(std::atomic<int>& x, int v) {
    int old = x.load(std::memory_order_relaxed);
    while (old < v && !x.compare_exchange_weak(
        old, v, std::memory_order_relaxed, std::memory_order_relaxed)) {}
}
```

这里操作只维护 `x` 的数值不变量，不发布其他数据，因此 relaxed 足够。若新值同时发布一个对象图，就需要重新证明生命周期和 acquire/release 关系。

## ABA 与内存回收

CAS 只比较位模式。若指针从 A 变 B 又回到地址 A，CAS 可能无法发现对象已经被删除并复用，这就是 ABA。解决方向包括：

- 指针附带版本标签；
- hazard pointer 阻止被观察对象回收；
- epoch-based reclamation 延迟回收；
- RCU grace period；
- 带锁管理生命周期。

无锁更新算法和安全回收是两个独立证明。节点从结构移除，不代表其他线程已不再持有指针。

## 编译器、ISA 与内核

C++ 内存序不是机器指令的别名。编译器会根据目标 ISA 映射：

- x86 TSO 下许多 acquire load/release store 可用普通 load/store；
- Arm/RISC-V 等较弱模型可用带 acquire/release 语义的指令或 barrier；
- seq_cst RMW/fence 通常需要更强排序；
- 编译器还需阻止不允许的源级重排。

Linux 内核有自己的内存模型和 `READ_ONCE`、`smp_load_acquire`、`smp_store_release` 等原语，不能把 C++ `std::atomic` 规则逐字套进内核代码。设备 MMIO 又有不同 barrier 与 accessor。

## 锁怎样提供顺序

mutex unlock 是 release，随后成功 lock 是 acquire；临界区内普通访问因此被同步。条件变量还需共享谓词和 mutex，避免丢失唤醒，参见[锁与条件变量](../concurrency/locks-condition-variables.md)。

线程创建使创建前的相关状态对新线程可见；成功 `join` 使被 join 线程完成前的操作 happens-before join 返回后的操作。具体关系以语言标准为准。

## 证明方法

对每个无锁结构写出：

1. 线性化点；
2. 每个共享对象的 modification order；
3. 发布与获取边；
4. 哪些读取允许看见旧值；
5. 节点何时不再可达、何时真正回收；
6. 进度保证：blocking、lock-free、wait-free；
7. 弱内存模型和编译器下仍成立的理由。

然后用模型检查或 litmus 工具寻找反例。压力测试能发现 bug，但运行十亿次也不能证明不存在某个允许而罕见的执行。

## 测量顺序成本

内存序成本依 ISA 和操作类型。原子 RMW 即使用 relaxed，也可能因 cache line 独占而昂贵；seq_cst store 在某些 ISA 上增加屏障；无争用 mutex 可能只走用户态 CAS，争用时进入内核停放。

实验至少拆分：

- 单线程指令成本；
- 多线程只读；
- 多线程同一原子 RMW；
- 分片原子；
- 同 socket 与跨 socket；
- acquire/release 与 seq_cst；
- 吞吐和公平性、p99 等待时间。

不要以“汇编中没有 fence”断言 acquire 免费：它仍约束编译器，并且 cache miss/所有权成本可能主导。

## 常见失败模式

- 把 `volatile` 当原子或 fence；
- 认为 x86 上普通 data race 安全；
- CAS 成功后立即回收节点；
- acquire load 没有读取 release 链，却声称已同步；
- 用 relaxed 引用计数，却遗漏从 1 降到 0 的生命周期顺序；
- seq_cst 原子与非原子 data race 混用；
- 把 CPU barrier、compiler barrier、I/O barrier、cache maintenance 混为一谈；
- 只在强内存序机器压力测试。

## 跨层连接

- cache line 的所有权流量见 [缓存一致性](cache-coherence.md)；
- ISA fence 和原子只是语言模型实现，见 [ISA 与微架构](isa-microarchitecture.md)；
- 基础术语进入 [并发语义](../concurrency/foundations.md)；
- 无锁回收与 RCU 见 [无锁结构与 RCU](../concurrency/lock-free-rcu.md)。

## Reference

- [ISO C++ working draft: memory model](https://eel.is/c++draft/intro.multithread)
- [ISO C++ working draft: atomics](https://eel.is/c++draft/atomics)
- [Boehm and Adve, Foundations of the C++ Concurrency Memory Model](https://doi.org/10.1145/1375581.1375591)
- [Arm A-profile Architecture: Memory Model](https://developer.arm.com/Architectures/Memory%20Model%20Tool)
- [RISC-V Unprivileged ISA: RVWMO Memory Consistency Model](https://docs.riscv.org/reference/isa/unpriv/rvwmo.html)
- [Intel 64 Architecture Memory Ordering](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
- [Linux Kernel Memory Model](https://www.kernel.org/doc/html/latest/dev-tools/lkmm/index.html)
- [Linux Kernel Memory Barriers](https://www.kernel.org/doc/html/latest/core-api/wrappers/memory-barriers.html)
