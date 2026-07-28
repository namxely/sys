# 并发

并发描述多个活动在时间上重叠，平行执行只是其中一种实现。正确并发程序必须同时回答：谁拥有状态、哪些操作可以重叠、何时建立可见性、等待如何结束、失败与取消向哪里传播、资源何时回收。

## 阅读路径

1. [并发的语义基础](foundations.md)：安全性、活性、happens-before、线性化与所有权。
2. [锁与条件变量](locks-condition-variables.md)：互斥、等待谓词、futex、死锁与公平。
3. [协程](coroutines.md)：把暂停点编译成状态机，理解 stackful/stackless 与 scheduler 边界。
4. [异步 I/O 与事件循环](async-event-loop.md)：readiness、completion、背压和连接状态。
5. [无锁结构与 RCU](lock-free-rcu.md)：进度保证、CAS、ABA 与安全内存回收。
6. [结构化并发](structured-concurrency.md)：用任务树统一生命周期、取消、deadline 与错误。

## 六个正交维度

| 维度 | 典型选择 | 需要证明的事 |
| --- | --- | --- |
| 工作分解 | thread、task、actor、coroutine | 工作是否独立、粒度是否合适 |
| 状态共享 | immutable、message、shared memory | 谁可读写、何时转移所有权 |
| 同步 | lock、atomic、channel、barrier | 顺序边与不变量 |
| 等待 | block、park、poll、callback、await | 是否浪费 CPU、能否取消 |
| 调度 | OS、runtime、work stealing、event loop | 公平、局部性、过度订阅 |
| 生命周期 | detached、join、scope/task tree | 错误、取消与资源何时收束 |

不要把这些维度压缩成“同步还是异步”二分。协程可以在单线程事件循环上运行，也可在线程池间迁移；无锁数据结构仍可能被调度器长期饿死；消息传递实现内部仍可能使用共享内存和原子。

## 选择顺序

1. 先写共享状态不变量；
2. 能用不可变值和所有权转移，就减少共享可变状态；
3. 需要共享时先选最容易证明的互斥；
4. 明确等待能否阻塞 OS 线程；
5. 把取消、超时和关闭加入正常状态机；
6. 只有测到锁争用并证明语义后，才考虑无锁；
7. 用 trace 验证调度、队列、唤醒和尾延迟。

## Reference

- [ISO C++ working draft: concurrency support library](https://eel.is/c++draft/thread)
- [The Open Group: Threads](https://pubs.opengroup.org/onlinepubs/9799919799/basedefs/pthread.h.html)
- [Herlihy and Shavit, The Art of Multiprocessor Programming, 2nd Edition](https://www.elsevier.com/books/the-art-of-multiprocessor-programming/herlihy/978-0-12-415950-1)
- [Linux Kernel Locking](https://www.kernel.org/doc/html/latest/locking/)
