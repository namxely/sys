# 异步 I/O 与事件循环

事件循环把许多连接或操作的等待集中到少量线程：任务推进到不能继续时登记兴趣并返回；内核报告就绪或完成后，循环再次推进对应状态机。它擅长高并发等待，不会让单线程获得额外 CPU 算力。

## 同步、非阻塞与异步

三个维度不要混用：

- **同步接口**：调用返回时给出结果；
- **非阻塞 fd**：暂时不能推进时返回 `EAGAIN`；
- **异步提交**：提交操作后，结果稍后进入 completion。

`epoll`/`kqueue` 主要报告 readiness；IOCP、io_uring 等接口可报告 completion。readiness 后仍要执行 `read/write`，completion 则关联一次已提交操作，但也可能短完成、失败或取消。

## reactor 与 proactor

### reactor

```text
register interest -> wait readiness -> perform nonblocking I/O -> update interest
```

应用拥有每次 I/O 尝试和状态推进。

### proactor

```text
submit operation(buffer, length) -> wait completion -> consume result
```

内核/运行时拥有在途操作。buffer 在完成前必须保持有效，取消也必须等到“不会再访问 buffer”的明确状态。

实际运行时常混合两者，例如用 readiness 实现 socket、线程池实现文件 I/O，再统一为 future/promise。

## 连接是状态机

一个带背压的 TCP 连接至少有：

```text
ACCEPTED
  -> READING_HEADERS
  -> READING_BODY
  -> PROCESSING
  -> WRITING_RESPONSE
  -> KEEPALIVE or CLOSING
```

每个状态要记录：

- 已消费/待发送字节；
- 输入解析器进度；
- 输出 buffer 所有权；
- timer/deadline；
- peer half-close；
- 是否仍注册 readiness；
- 取消与错误最终归属。

TCP 是字节流，一次 `read` 不对应一个消息；一次 `write` 也可能只接受部分字节。

## level-triggered 与 edge-triggered

### level-triggered

只要条件仍成立就持续报告。代码更宽容，但若某 fd 一直可读/可写，可能重复唤醒。

### edge-triggered

只在状态从不可就绪变为就绪时报告。处理者通常必须循环到 `EAGAIN`，否则剩余数据可能不再产生新边沿。

无论哪种模式，多个线程同时处理同一 fd 都需明确所有权；否则一个线程在 readiness 后可能发现数据已被另一个消费。

## 输出背压

socket 可写几乎总是成立，不应永久订阅 `EPOLLOUT`。正确流程：

1. 有待发送数据时尝试 write；
2. 短写或 `EAGAIN` 后保存剩余 buffer；
3. 只有 buffer 非空时订阅 writable；
4. writable 到来继续 flush；
5. buffer 清空后取消 writable 兴趣；
6. 输出队列达到上限时停止读、拒绝或关闭。

若持续读取上游却让输出队列无限增长，事件循环只是把网络慢客户端变成内存故障。

## 一个完整的 epoll 驱动循环

下面的 Linux C11 示例把 `timerfd` 与 `eventfd` 放入同一个 epoll。工作线程通过 eventfd 唤醒循环；timerfd 提供单调时钟周期事件。它展示 readiness、计数 drain 和资源关闭，不是网络服务器。

```c
#define _GNU_SOURCE
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/epoll.h>
#include <sys/eventfd.h>
#include <sys/timerfd.h>
#include <unistd.h>
static int add(int ep, int fd) {
    struct epoll_event ev = {.events = EPOLLIN, .data.fd = fd};
    return epoll_ctl(ep, EPOLL_CTL_ADD, fd, &ev);
}
int main(void) {
    int ep = epoll_create1(EPOLL_CLOEXEC);
    int timer = timerfd_create(CLOCK_MONOTONIC, TFD_CLOEXEC | TFD_NONBLOCK);
    int wake = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
    if (ep < 0 || timer < 0 || wake < 0) { perror("create"); return 1; }
    struct itimerspec ts = {
        .it_interval = {.tv_sec = 1, .tv_nsec = 0},
        .it_value = {.tv_sec = 1, .tv_nsec = 0}
    };
    if (timerfd_settime(timer, 0, &ts, NULL) < 0 || add(ep, timer) < 0 || add(ep, wake) < 0) {
        perror("setup"); return 1;
    }
    struct epoll_event events[16];
    for (int ticks = 0; ticks < 5;) {
        int n;
        do n = epoll_wait(ep, events, 16, -1); while (n < 0 && errno == EINTR);
        if (n < 0) { perror("epoll_wait"); return 1; }
        for (int i = 0; i < n; ++i) {
            uint64_t count;
            int fd = events[i].data.fd;
            if (read(fd, &count, sizeof count) != sizeof count) continue;
            if (fd == timer) { ticks += (int)count; printf("ticks=%d\n", ticks); }
            else printf("wakeups=%llu\n", (unsigned long long)count);
        }
    }
    close(wake); close(timer); close(ep);
}
```

`eventfd` 写入值会累加，读取返回并清零；它可把跨线程通知合并。生产 loop 需要处理 fd 关闭/复用、注册失败、错误事件和公平预算。

## timer 与 deadline

每个请求一个独立内核 timer 可能昂贵。事件循环常用最小堆、timer wheel 或分层 wheel 管理 deadline：

- 最小堆：插入/删除 $O(\log n)$，最近 deadline 易取；
- timer wheel：接近 $O(1)$，精度和范围由层级决定；
- 批量过期：高效但可能形成同一时刻的取消风暴。

使用单调时钟计算 timeout。deadline 是绝对终点，跨层传递时应取更早者：

$$
D_\mathrm{child}=\min(D_\mathrm{parent},D_\mathrm{local})
$$

## 公平与预算

一个总有数据的 fd 若被无限 drain，会饿死其他连接。每轮限制：

- 每 fd 最大字节/消息；
- 每 callback 最大时间；
- 连续 completion 数；
- CPU 密集任务转移到受限 worker pool。

worker pool 也必须有界；若 event loop 无限制投递 CPU 工作，背压只是从 socket 转移到任务队列。

## callback、future 与 coroutine

三种表面可驱动同一状态机：

- callback 显式传 continuation；
- future/promise 把完成存入对象并组合；
- coroutine 把 continuation 和局部状态放入 frame。

coroutine 改善顺序代码可读性，却不消除状态、背压和生命周期。一次 `await write()` 仍可能短写、取消或在别的线程恢复，详见[协程](coroutines.md)。

## 取消竞态

completion 与 cancel 可同时到达。实现需要单一终态：

```text
PENDING --complete--> COMPLETED
PENDING --cancel----> CANCELLING --ack--> CANCELLED
```

若取消 API 只表示“已请求”，buffer 在取消调用返回后可能仍被内核使用。必须读取接口对同步取消、异步取消和 completion 交付的精确定义。

## 测量

- event-loop lag：timer 预期唤醒与实际处理的差；
- 每轮事件数、callback 时间和 runnable queue；
- 输入/输出 buffer 字节与高水位；
- `EAGAIN`、短 I/O、取消与超时；
- epoll/io_uring wakeup 与系统调用数；
- worker pool queue 和饱和度；
- p50/p99 连接与请求延迟。

用时间线判断延迟发生在内核等待、runqueue、loop 排队还是用户 callback。

## 失败模式

- blocking syscall 或 CPU 长任务卡住 loop；
- edge-triggered 没有 drain 到 `EAGAIN`；
- 永久订阅 writable 造成 busy loop；
- 关闭 fd 后旧事件命中新复用 fd；
- output buffer 无界；
- timer 使用 wall clock，时钟调整导致异常；
- timeout 返回但在途操作仍访问已释放 buffer；
- 每个事件处理到底，造成其他连接饥饿；
- 多 event loop 线程同时拥有同一连接状态。

## 跨层连接

- 内核 readiness/completion、IRQ 与队列见[I/O、中断与 DMA](../os/io-interrupt-dma.md)；
- coroutine frame 与 resume 见[协程](coroutines.md)；
- 有界队列与取消语义见[并发基础](foundations.md)；
- 父子 deadline 与错误传播见[结构化并发](structured-concurrency.md)。

## Reference

- [Linux epoll(7)](https://www.man7.org/linux/man-pages/man7/epoll.7.html)
- [Linux io_uring(7)](https://www.man7.org/linux/man-pages/man7/io_uring.7.html)
- [Linux eventfd(2)](https://www.man7.org/linux/man-pages/man2/eventfd.2.html)
- [Linux timerfd_create(2)](https://www.man7.org/linux/man-pages/man2/timerfd_create.2.html)
- [FreeBSD kqueue(2)](https://man.freebsd.org/cgi/man.cgi?kqueue)
- [Microsoft I/O Completion Ports](https://learn.microsoft.com/en-us/windows/win32/fileio/i-o-completion-ports)
- [libuv Design Overview](https://docs.libuv.org/en/v1.x/design.html)
- [Schmidt, Reactor: An Object Behavioral Pattern for Demultiplexing and Dispatching Handles for Synchronous Events](https://www.dre.vanderbilt.edu/~schmidt/PDF/reactor-siemens.pdf)
