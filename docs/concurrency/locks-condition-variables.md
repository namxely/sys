# 锁与条件变量

互斥锁把一段并发历史压缩成临界区的串行顺序；条件变量让线程在某个受锁保护的谓词为假时睡眠，并在状态可能变化时重新检查。它们的核心不是 API，而是不变量、等待谓词和唤醒协议。

## 锁保护不变量

不要只写“mutex 保护变量 x”，应写：

```text
mutex m protects:
- queue contents
- closed flag
- relationship: closed => no future push
- relationship: size <= capacity
```

所有读写这些状态并依赖其关系的路径都要遵守同一协议。把每个字段各配一把锁，可能使跨字段不变量无处原子地检查。

## mutex 的快慢路径

无争用 mutex 常通过用户态原子操作获得：

```text
unlocked --CAS--> locked
```

争用时需要把线程停放，Linux 用户态锁常以 futex 为机制：

```text
CAS fails -> mark/witness waiters -> futex_wait
unlock -> publish unlocked -> futex_wake
```

futex 只提供“当用户内存值仍等于期望时睡眠”和唤醒原语；mutex 的所有权、公平、递归、健壮性和优先级继承由库协议组织。

## spin 还是 park

自旋适合临界区极短、持有者正在其他核心运行且不会被抢占的场景。停放适合等待可能较长或 CPU 已过度订阅。混合锁先短暂自旋，再进入内核睡眠。

自旋成本：

$$
C_\mathrm{spin}=T_\mathrm{wait}\cdot \text{occupied CPU capacity}
$$

睡眠成本包括系统调用、调度和 cache 冷却。阈值依机器、负载和优先级，不应写成通用固定次数。

## 条件变量等待的是谓词

正确模式：

```cpp
std::unique_lock lock(m);
cv.wait(lock, [&] { return predicate(); });
// predicate is true while m remains held
```

必须循环检查，因为：

- 允许 spurious wakeup；
- 另一个线程可能先消费状态；
- notify 表示“状态可能改变”，不是资源所有权转移；
- timeout、关闭和取消也会改变退出条件。

修改共享状态时持锁，随后 notify。通知放在 unlock 前或后都可能正确，性能与精确协议不同；关键是等待者检查谓词和修改者建立同步。

## 一个有界、可关闭队列

下面是 C++20 完整实现。关闭后不再接受 push；消费者会排空剩余元素，随后 `pop` 返回 `nullopt`。

```cpp
#include <condition_variable>
#include <cstddef>
#include <deque>
#include <mutex>
#include <optional>
#include <utility>
template<class T>
class BoundedQueue {
    std::mutex m_;
    std::condition_variable not_empty_, not_full_;
    std::deque<T> q_;
    std::size_t cap_;
    bool closed_ = false;
public:
    explicit BoundedQueue(std::size_t cap) : cap_(cap) {}
    bool push(T value) {
        std::unique_lock lock(m_);
        not_full_.wait(lock, [&] { return q_.size() < cap_ || closed_; });
        if (closed_) return false;
        q_.push_back(std::move(value));
        lock.unlock();
        not_empty_.notify_one();
        return true;
    }
    std::optional<T> pop() {
        std::unique_lock lock(m_);
        not_empty_.wait(lock, [&] { return !q_.empty() || closed_; });
        if (q_.empty()) return std::nullopt;
        T value = std::move(q_.front());
        q_.pop_front();
        lock.unlock();
        not_full_.notify_one();
        return value;
    }
    void close() {
        std::lock_guard lock(m_);
        closed_ = true;
        not_empty_.notify_all();
        not_full_.notify_all();
    }
};
```

`cap` 必须大于 0，否则 push 永远等待；生产实现可在构造时拒绝 0。这里 notify 在 `close` 持锁时执行，正确但可能让唤醒线程短暂再次争锁；也可先改状态、解锁后通知。

## timeout 需要绝对 deadline

反复用相对超时：

```text
wait_for(100 ms)
spurious wake
wait_for(100 ms)
...
```

可能无限延长总等待。应先计算单调时钟的绝对 deadline，再用 `wait_until` 循环。系统 wall clock 调整不应改变 timeout，选择 API 时确认使用的 clock。

## 多把锁

若操作必须持有多把锁：

- 全局定义严格顺序；
- 或使用 `std::scoped_lock`/`std::lock` 的死锁避免算法；
- 不在持锁时调用未知回调；
- 记录条件变量 wait 会暂时释放哪把锁。

按对象地址排序只有在对象生命周期稳定、排序规则全局一致时才可靠；业务 ID 往往更清晰。

## 读写锁

读写锁允许多个读者或一个写者。它只在读临界区足够长、写较少且实现公平性适合时有益。代价包括：

- 状态更复杂；
- cache line 仍有读者计数流量；
- writer starvation 或 reader starvation；
- upgrade 容易死锁；
- 短读路径可能比普通 mutex 更贵。

不可变快照、copy-on-write 或 RCU 可能更适合极端读多场景，但有内存和回收成本。

## seqlock

writer 在写前后递增序列号；reader 读取版本、复制数据、再检查版本是否未变且为偶数，否则重试。reader 不阻塞 writer，适合小且可重试的读快照。

reader 不能安全追踪可能被释放的普通指针，也可能在持续写入下饥饿。Linux seqlock 有严格 API 和上下文规则，不应自行用两个原子拼出近似版本。

## 锁性能的真正来源

- 临界区串行比例；
- lock line 在核心间迁移；
- 持有者被抢占；
- convoy 与唤醒风暴；
- NUMA 距离；
- 临界区内 page fault、分配或 I/O；
- 公平策略与 handoff；
- 锁粒度导致的额外内存占用。

无争用纳秒值不能预测高争用尾延迟。

## 测量

至少记录：

- lock wait、hold time 分布；
- contention 次数与等待者数量；
- owner 是否在运行、睡眠或被抢占；
- critical section 的调用栈；
- futex wait/wake 与调度延迟；
- throughput、公平性和 p99；
- 同 socket/跨 socket 差异。

Linux 可用：

```bash
perf lock record -- ./program
perf lock report
strace -f -e futex ./program
```

工具支持依内核配置，`strace` 会明显扰动锁时序。应用层埋点应采样，避免每次锁操作都记录。

## 失败模式

- 用 `if` 而不是循环检查条件变量谓词；
- 状态不受同一 mutex 保护，产生丢失唤醒；
- notify 被误解为“一个资源已保留给被唤醒者”；
- 持锁执行阻塞 I/O、日志或用户回调；
- 析构 mutex/condition variable 时仍有等待者；
- 递归锁掩盖锁层次错误；
- 读写锁在写压力下饥饿；
- 通过加大线程池掩盖 lock convoy；
- 只优化 lock 指令，不缩短/分片临界区。

## 跨层连接

- mutex 的 acquire/release 顺序见[原子与内存模型](../architecture/atomics-memory-model.md)；
- futex 停放和唤醒进入[调度](../os/scheduling.md)；
- 若锁确为瓶颈，再比较[无锁结构与 RCU](lock-free-rcu.md)；
- 关闭、取消与任务生命周期见[结构化并发](structured-concurrency.md)。

## Reference

- [ISO C++ working draft: mutex requirements](https://eel.is/c++draft/thread.mutex)
- [ISO C++ working draft: condition variables](https://eel.is/c++draft/thread.condition)
- [The Open Group: pthread_mutex_lock](https://pubs.opengroup.org/onlinepubs/9799919799/functions/pthread_mutex_lock.html)
- [The Open Group: pthread_cond_wait](https://pubs.opengroup.org/onlinepubs/9799919799/functions/pthread_cond_wait.html)
- [Linux futex(2)](https://www.man7.org/linux/man-pages/man2/futex.2.html)
- [Linux Kernel Locking](https://www.kernel.org/doc/html/latest/locking/)
- [Mellor-Crummey and Scott, Algorithms for Scalable Synchronization on Shared-Memory Multiprocessors](https://doi.org/10.1145/103727.103729)
