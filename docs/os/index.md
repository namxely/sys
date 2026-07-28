# 操作系统

操作系统在有限、并发且会失败的硬件之上提供资源抽象：执行流被组织为进程和线程，内存被组织为受保护的虚拟地址空间，设备被组织为文件描述符、队列和完成事件。内核既要保持隔离与正确性，也要决定何时调度、回收、回写和批处理。

## 主题地图

| 主题 | 核心抽象 | 关键慢路径 |
| --- | --- | --- |
| [进程与线程](process-thread.md) | 地址空间、执行上下文、资源引用 | 创建、退出、上下文切换 |
| [调度](scheduling.md) | runnable entity、优先级、deadline | 抢占、负载均衡、迁移 |
| [虚拟内存](virtual-memory.md) | VMA、页、映射、回收 | page fault、reclaim、swap |
| [文件系统](filesystem.md) | pathname、inode、open file description | lookup、writeback、fsync |
| [I/O、中断与 DMA](io-interrupt-dma.md) | descriptor、queue、completion | 系统调用、IRQ、设备排队 |
| [隔离与容器](isolation-containers.md) | namespace、cgroup、capability、image | 创建、资源压力、逃逸边界 |

## 两条控制流

### 同步路径

程序执行系统调用或触发 fault，处理器保存用户态上下文并进入内核。内核可能立即完成，也可能把任务挂入等待队列，让调度器运行别的任务，事件完成后再唤醒。

### 异步路径

设备完成、定时器或跨核通知引发中断。内核通常在受限的硬中断上下文做最少工作，把可推迟工作交给 softirq、线程化中断、workqueue 或用户态事件循环。

这两条路径最终在等待队列、调度和资源生命周期处汇合。

## 内核态不是“无限权限的普通函数”

内核代码还受到上下文约束：

- 某些路径不能睡眠；
- page fault 可能递归进入内存管理；
- 中断可能打断普通内核路径；
- 锁顺序错误会冻结整机；
- 用户指针必须按平台接口访问；
- 设备和 CPU 内存顺序不同；
- 错误恢复要考虑资源只完成了一半。

因此理解 API 名称不够，还要理解调用上下文、所有权、可阻塞性和回滚路径。

## 观测入口

Linux 提供多层证据：

- `/proc` 与 `/sys`：状态快照和配置接口；
- tracepoint、ftrace、perf、eBPF：时间线与事件；
- PSI：CPU、内存和 I/O 压力；
- cgroup v2：分组资源使用与限制；
- PMU：核心与内存系统事件；
- 应用指标：最终延迟、吞吐和错误。

单一快照很难解释动态系统。把“谁在等什么、谁唤醒了谁、资源何时从谁转给谁”画成时间线，通常比堆叠平均值更接近根因。

## Reference

- [MIT 6.1810 Operating System Engineering](https://pdos.csail.mit.edu/6.1810/)
- [xv6: a simple, Unix-like teaching operating system](https://pdos.csail.mit.edu/6.1810/2025/xv6/book-riscv-rev5.pdf)
- [Linux Kernel Documentation](https://www.kernel.org/doc/html/latest/)
- [The Open Group Base Specifications, Issue 8](https://pubs.opengroup.org/onlinepubs/9799919799/)
