# I/O、中断与 DMA

I/O 的核心不是某个系统调用，而是所有权在应用、内核、驱动和设备之间移动的状态机。数据可能通过 CPU copy 或 DMA 传输，完成可能通过轮询或中断报告，请求还会在多个软件和硬件队列中排队。

## 一条通用 I/O 路径

以存储读取为例：

```text
application
  -> system call / submission queue
  -> VFS and page cache
  -> filesystem
  -> block layer queue
  -> device driver
  -> DMA descriptors / device queue
  -> controller and media
  -> completion / interrupt
  -> wake task or completion queue
```

page cache 命中会短路后半段；direct I/O 可能绕过 page cache，但不会绕过文件系统、block layer 和设备队列。网络、GPU 和其他设备的层名不同，所有权—提交—完成模式相似。

## programmed I/O 与 DMA

### programmed I/O

CPU 通过 MMIO/port I/O 直接读写设备寄存器或数据窗口。适合控制寄存器和少量数据，大量搬运会消耗 CPU。

### DMA

驱动准备内存缓冲和 descriptor，把 DMA 地址交给设备；设备直接在内存与自身之间传输。CPU 仍负责：

- 分配和映射 DMA buffer；
- 正确同步 CPU/设备所有权；
- 提交 descriptor 与 doorbell；
- 处理完成和错误；
- 回收 buffer。

DMA 使用的是设备可见地址，不一定等于 CPU 物理地址，更不等于用户虚拟地址。IOMMU 可提供设备地址翻译和隔离。

## DMA 所有权状态机

```text
CPU-owned
  -- map/sync + publish descriptor -->
device-owned
  -- device completes + driver observes completion -->
CPU-owned
```

在 device-owned 阶段，CPU 不能随意访问 streaming DMA buffer；在非硬件一致平台，DMA API 还负责 cache maintenance。描述符内容必须先对设备可见，再敲 doorbell，顺序由 DMA/MMIO API 保证，不应手写普通指针加 C++ fence 替代。

## 中断：快速确认，推迟工作

设备完成后可触发中断。硬中断上下文通常：

1. 确认中断来源；
2. 屏蔽/ack 必要状态；
3. 记录完成或调度后半部；
4. 尽快返回。

后续工作可在 softirq、NAPI、线程化中断、tasklet/workqueue 等上下文处理。机制依内核子系统和版本；共同目标是缩短不可抢占/高优先级路径并允许批处理。

### interrupt moderation

每个包一次中断会在高吞吐时形成 interrupt storm。设备/驱动可按时间或完成数量聚合中断，减少 CPU 开销，却增加低负载延迟。自适应 moderation 在吞吐与延迟间动态选择。

## 轮询与中断

| 策略 | 空闲成本 | 活跃延迟 | 高负载吞吐 |
| --- | --- | --- | --- |
| 中断 | 低 | 有进入/调度开销 | 可能被中断风暴限制 |
| busy polling | 高 CPU/功耗 | 很低 | 避免频繁切换 |
| 混合 | 中等 | 可调 | 常用于 NAPI、io_uring 等 |

网络 NAPI 在收到中断后进入预算化 polling，清空一批包；队列耗尽后再恢复中断。这不是“中断或轮询”二选一，而是随负载切换。

## 阻塞、非阻塞、就绪与完成

- **blocking**：调用线程在无法推进时睡眠；
- **nonblocking**：操作暂时不能完成时返回 `EAGAIN`；
- **readiness**：`epoll/kqueue` 告诉程序“现在尝试操作可能推进”；
- **completion**：异步接口报告已提交操作完成。

readiness 事件后 `read` 仍可能因其他线程抢先消费而得到 `EAGAIN`；completion 也可能是短 I/O、取消或错误。两者都需要状态机和背压。

## 系统调用与批处理

每次系统调用有边界检查、上下文进入、对象查找等固定成本。`readv/writev`、批量收发、io_uring 提交/完成队列和设备多队列可以摊薄成本。批越大：

- 每项开销下降；
- queueing 与等待凑批的延迟上升；
- 错误和取消粒度变粗；
- buffer 生命周期更长。

最佳批量必须在实际到达率和 SLO 下测量。

## 健壮的非阻塞读取

下面函数适用于 POSIX 非阻塞 fd；它把 `EINTR` 当重试、`EAGAIN` 当“等待下一次 readiness”、0 当 EOF，并把调用契约错误与接收缓冲区已满分别报告：

```c
#include <errno.h>
#include <stddef.h>
#include <unistd.h>
enum read_result { READ_PROGRESS, READ_FULL, READ_WAIT, READ_EOF, READ_ERROR };
enum read_result drain_fd(int fd, char *buf, size_t cap, size_t *used) {
    if (!buf || !used || *used > cap) {
        errno = EINVAL;
        return READ_ERROR;
    }
    if (*used == cap) return READ_FULL;
    for (;;) {
        ssize_t n = read(fd, buf + *used, cap - *used);
        if (n > 0) {
            *used += (size_t)n;
            if (*used == cap) return READ_FULL;
            continue;
        }
        if (n == 0) return READ_EOF;
        if (errno == EINTR) continue;
        if (errno == EAGAIN || errno == EWOULDBLOCK) return READ_WAIT;
        return READ_ERROR;
    }
}
```

edge-triggered readiness 通常要求一直读到 `EAGAIN`；`READ_FULL` 则要求协议层先消费或扩容缓冲区，再继续 drain。level-triggered 会在条件仍成立时继续报告。协议层还要处理半包、消息边界、输出队列和连接关闭。

## queue depth 与 Little 定律

稳定设备队列中：

$$
N=X L
$$

为了把高延迟设备跑满，需要一定在途请求数；但超过饱和点后，吞吐不再增加，等待时间继续增加。测量应画：

$$
\text{queue depth}\rightarrow(\text{throughput},\text{p50/p99 latency})
$$

不同请求大小、读写比例、顺序性和设备内部 GC 会改变曲线。

## IOMMU、pinning 与 zero-copy

IOMMU 为设备提供独立地址空间，限制 DMA 范围并支持 scatter-gather。映射/取消映射和 IOTLB miss 有成本。

所谓 zero-copy 常只是减少某一层 CPU copy：

- `sendfile/splice` 在内核对象间传递 page 引用；
- registered buffer 避免每次 pin/map；
- userspace networking 让应用直接管理队列；
- GPU pinned memory 便于 DMA。

它们会增加 pin 住的内存、生命周期、NUMA、隔离和回收复杂度。应报告实际减少了哪一次 copy，而不是只贴标签。

## 怎样测量

- 应用：submit 到 completion 的分位延迟；
- 系统调用：次数、短 I/O、`EAGAIN`、取消；
- 调度：睡眠、唤醒、runqueue delay；
- IRQ：每 CPU 中断率、softirq 时间；
- block/network queue：深度、merge、drop、retransmit；
- DMA/IOMMU：mapping、IOTLB 与设备计数器；
- PSI I/O：任务因 I/O 等待造成的停顿。

Linux 示例：

```bash
cat /proc/interrupts
cat /proc/softirqs
cat /proc/pressure/io
perf trace -e irq:*,block:* -- sleep 10
```

全量 trace 开销可能很高，应限制事件、设备、CPU 和时间窗口。

## 失败模式

- 把 DMA 当“CPU 完全不参与”；
- 普通虚拟地址直接交设备；
- descriptor 未发布完就写 doorbell；
- readiness 事件只 read 一次，edge-triggered 下饿死；
- completion 成功却忽略短 I/O；
- 通过增加 queue depth 掩盖饱和，p99 失控；
- 中断全落在一个 CPU，与应用争用；
- zero-copy pin 住大量页，破坏回收与 NUMA；
- 只测设备服务时间，不测排队和任务唤醒。

## 跨层连接

- 文件 page cache 和持久化见[文件系统](filesystem.md)；
- buffer 页、pinning 与 IOMMU 映射连接[虚拟内存](virtual-memory.md)；
- DMA coherence 与 cache line 见[缓存一致性](../architecture/cache-coherence.md)；
- readiness/completion 的用户态组织见[异步 I/O 与事件循环](../concurrency/async-event-loop.md)。

## Reference

- [Linux Dynamic DMA Mapping Guide](https://www.kernel.org/doc/html/latest/core-api/dma-api-howto.html)
- [Linux DMA API](https://www.kernel.org/doc/html/latest/core-api/dma-api.html)
- [Linux Generic IRQ Layer](https://www.kernel.org/doc/html/latest/core-api/genericirq.html)
- [Linux NAPI](https://www.kernel.org/doc/html/latest/networking/napi.html)
- [Linux Multi-Queue Block IO Queueing Mechanism](https://www.kernel.org/doc/html/latest/block/blk-mq.html)
- [Linux io_uring](https://www.man7.org/linux/man-pages/man7/io_uring.7.html)
- [Linux epoll(7)](https://www.man7.org/linux/man-pages/man7/epoll.7.html)
- [Linux Kernel Documentation: PCI Bus Subsystem](https://www.kernel.org/doc/html/latest/PCI/index.html)
