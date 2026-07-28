# 并发的语义基础

并发 bug 难以复现，是因为程序结果不只由输入决定，还由调度、内存顺序和事件时机决定。正确性不能靠“我跑了很多次都没错”，而要靠不变量、顺序关系和进度证明。

## 并发、并行与异步

- **并发**：多个活动的生命周期重叠，可以交错推进；
- **并行**：多个活动在同一时刻由不同执行资源推进；
- **异步**：发起操作与获得结果分离，发起者不必原地等待。

单线程事件循环具有并发和异步，却通常没有用户代码的多核并行；线程池可以并行执行同步函数；协程是否并行取决于 scheduler。

## 安全性与活性

### safety

“坏事永不发生”，例如：

- 余额总和不变；
- 队列不返回未入队对象；
- 已释放对象不再访问；
- 同一请求不会提交两次。

### liveness

“好事最终发生”，例如：

- 请求最终完成或取消；
- 持锁线程最终释放；
- runnable 任务最终获得 CPU。

无死锁不代表无饥饿；lock-free 不代表某个指定线程一定完成。

## race 的三种含义

### data race

由语言内存模型定义。C++ 中，两个没有 happens-before 的冲突访问，至少一个写且并非都为适当原子访问，即构成 data race，行为未定义。

### race condition

更广义的逻辑结果依赖时序。例如两个合法加锁操作先后不同导致“最后写入者胜出”，可能无 data race 仍有业务 race。

### benign race

这个词容易掩盖证明缺失。若某个竞争真的允许，应明确：

- 哪些结果都合法；
- 操作是否原子；
- 生命周期是否安全；
- 进度和可观测副作用是否可接受。

## 原子步骤与线性化点

线性一致对象要求每次操作看起来在调用与返回之间的某一瞬间生效，并尊重实时先后。这个瞬间称线性化点。

例如 CAS 入栈：

```text
read old head
new.next = old
CAS(head, old, new)  <- 成功 CAS 是候选线性化点
```

但 CAS 成功只解决 head 更新；旧节点何时可释放仍需独立内存回收协议。

并非所有并发对象都要求线性一致。分布式或统计计数可接受更弱语义，但必须把契约写清。

## happens-before 图

正确性可画成有向图：

```text
producer writes payload
   -> sequenced-before
release publish
   -> synchronizes-with
acquire observe
   -> sequenced-before
consumer reads payload
```

传递后，写 happens-before 读。详见[原子与内存模型](../architecture/atomics-memory-model.md)。锁、线程创建/join、channel send/receive 也可以建立边，具体以语言/库契约为准。

## 共享状态与所有权

并发设计的四种常见形状：

### immutable sharing

构造完成后发布只读对象。读路径简单，但发布本身需要同步，对象图也不能藏有可变后门。

### confined state

状态只属于一个线程/actor/event loop，其他参与者发送消息。减少 data race，却需要处理队列上限、消息顺序和 actor 崩溃。

### ownership transfer

发送者交出对象后不再访问，接收者成为唯一所有者。Rust 类型系统能静态表达许多转移；C++ 需通过 move-only 类型和协议维持。

### synchronized sharing

多个线程通过锁或原子共同访问。应让锁保护不变量而不只是单个字段，并明确锁顺序与阻塞边界。

## 交错如何破坏复合操作

`counter++` 是 read—modify—write：

```text
T1 read 0
T2 read 0
T1 write 1
T2 write 1
```

结果为 1。把 `counter` 换成原子能让单次 RMW 不丢更新，但若业务不变量涉及多个字段，仍需事务、锁或更强协议。

例如转账要求：

$$
A+B=\mathrm{constant}
$$

分别原子更新 A、B 会暴露中间状态。锁住整个转账不变量，或使用版本化快照/事务，才解决读者一致性。

## 死锁的必要条件

Coffman 四条件：

1. mutual exclusion.
2. hold and wait.
3. no preemption.
4. circular wait.

打破任一条件可防死锁。工程上最常见的是全局锁顺序：

```text
Lock(account[min_id])
Lock(account[max_id])
```

但回调、日志、allocator 和第三方库可能在看不见的地方拿锁。尽量不在持锁时调用未知代码。

wait-for graph 中任务到资源、资源到持有者形成环，是死锁证据；线程 dump 只是某时刻快照，需结合锁身份和时间线。

## 其他活性故障

- **starvation**：某参与者长期得不到资源；
- **livelock**：持续重试、状态变化，却不完成工作；
- **convoy**：慢持有者使一队线程串行唤醒；
- **priority inversion**：高优先级等低优先级资源；
- **thundering herd**：一次事件唤醒大量竞争者；
- **backpressure collapse**：生产速度长期超过消费，队列吞噬内存并放大超时重试。

## 有界队列是系统不变量

队列容量 $K$ 把过载转成显式选择：

- block producer；
- reject/drop；
- shed 低优先级；
- 合并同类工作；
- 把压力传播到上游。

无界队列只是把当前延迟问题延后为内存和更严重的尾延迟问题。Little 定律给出平均在途数：

$$
N=X L
$$

若消费吞吐已饱和，增加 $N$ 主要增加 $L$。

## 可取消性是一种控制流

取消可能发生在：

- 尚未启动；
- 正在等待；
- 持有锁或资源；
- 已发出不可撤销 I/O；
- 操作完成但结果尚未交付。

因此取消通常是协作式请求，而不是任意终止线程。操作需要定义安全点、幂等回滚、资源释放和“取消与完成同时发生”的胜者语义。

## 如何测试

### 确定性检查

- 单线程验证状态机；
- 模型检查小状态空间；
- 注入 yield、延迟和失败；
- 用虚拟时钟测试 timeout；
- 记录随机 seed 并可重放。

### 动态工具

- ThreadSanitizer 检测许多 data race；
- lockdep 检查 Linux 内核锁依赖；
- trace 观察排队、唤醒、迁移和取消；
- stress/soak 暴露资源泄漏与长尾。

工具会漏报或误报，也可能改变时序。通过 sanitizer 不是证明，发现报告却应先当真实问题调查。

## 常见失败模式

- “操作很短”就不加同步；
- 用 sleep 等待另一个线程到达某状态；
- 锁只保护写，不保护读；
- 原子化字段，却没保护跨字段不变量；
- 持锁调用阻塞 I/O 或未知回调；
- 任务 detach 后仍引用栈对象；
- 超时返回，却让底层工作继续产生副作用；
- 无界重试和无界队列叠加；
- 只测吞吐，不测公平、队长和取消延迟。

## 跨层连接

- 硬件与语言顺序见[原子与内存模型](../architecture/atomics-memory-model.md)；
- 阻塞与唤醒实现见[锁与条件变量](locks-condition-variables.md)；
- 调度饥饿与优先级见[操作系统调度](../os/scheduling.md)；
- 生命周期与取消进一步收束为[结构化并发](structured-concurrency.md)。

## Reference

- [Lamport, Time, Clocks, and the Ordering of Events in a Distributed System](https://doi.org/10.1145/359545.359563)
- [Herlihy and Wing, Linearizability: A Correctness Condition for Concurrent Objects](https://doi.org/10.1145/78969.78972)
- [Coffman, Elphick, and Shoshani, System Deadlocks](https://doi.org/10.1145/356586.356588)
- [ISO C++ working draft: multi-threaded executions and data races](https://eel.is/c++draft/intro.multithread)
- [The Open Group: Threads](https://pubs.opengroup.org/onlinepubs/9799919799/basedefs/pthread.h.html)
- [LLVM ThreadSanitizer](https://clang.llvm.org/docs/ThreadSanitizer.html)
