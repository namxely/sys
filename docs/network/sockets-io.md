# Socket 与 I/O 模型

Socket 是内核网络端点的文件描述符接口。协议保证并不会自动变成正确的应用：短读写、背压、取消、半关闭、描述符泄漏和事件竞态都必须显式处理。

<a id="socket-lifecycle"></a>
## 生命周期与队列

TCP 服务端通常执行：

```text
socket -> setsockopt -> bind -> listen -> accept4
                                         |
                                     recv/send
                                         |
                                  shutdown/close
```

`listen(backlog)` 与 SYN 队列、已完成连接队列相关，但不是跨平台精确容量承诺。Linux 上 `accept4(..., SOCK_NONBLOCK | SOCK_CLOEXEC)` 可原子设置标志，避免另一次 `fcntl` 的竞态。

TCP 是字节流。正确的 length-prefix 读取循环必须保留剩余量，并让“读满、暂不可读、对端关闭、错误、取消”成为互不混淆的状态：

```c
enum read_state { READ_DONE, READ_WOULD_BLOCK, READ_EOF, READ_ERROR, READ_CANCELLED };
struct read_result { enum read_state state; size_t transferred; int error; };
struct read_result read_until_full(int fd, void *buf, size_t n, size_t *off,
                                   const _Atomic bool *stop) {
    while (*off < n) {
        if (atomic_load(stop))
            return (struct read_result){READ_CANCELLED, *off, ECANCELED};
        ssize_t r = recv(fd, (char *)buf + *off, n - *off, 0);
        if (r > 0) { *off += (size_t)r; continue; }
        if (r == 0) return (struct read_result){READ_EOF, *off, 0};
        if (errno == EINTR) continue;
        if (errno == EAGAIN || errno == EWOULDBLOCK)
            return (struct read_result){READ_WOULD_BLOCK, *off, 0};
        return (struct read_result){READ_ERROR, *off, errno};
    }
    return (struct read_result){READ_DONE, *off, 0};
}
```

`off` 由上层连接状态机跨 readiness 事件保留。`READ_EOF` 且 `transferred < n` 表示帧被截断，不能当作完整消息；`READ_WOULD_BLOCK` 只表示本轮需要暂停，不能当作连接失败或 EOF。

<a id="io-models"></a>
## 阻塞、就绪与完成

| 模型 | 内核告知什么 | 适合场景 | 关键代价 |
| --- | --- | --- | --- |
| blocking + thread | 调用完成 | 连接数有限、逻辑直观 | 栈、调度、取消 |
| `select`/`poll` | 哪些 fd 可能就绪 | 小规模、可移植 | 每轮扫描 |
| `epoll` | 就绪事件集合 | Linux 大量连接 | 状态机与事件语义 |
| `io_uring` | 提交/完成队列 | 批处理、异步文件与网络 | 生命周期、取消与顺序 |

“就绪”不保证下一次调用一定完成全部数据：另一个线程可能先消费，错误/EOF 也以 readiness 呈现。level-triggered 会持续报告未消费状态；edge-triggered 通常要求循环读到 `EAGAIN`，否则可能永久漏掉剩余数据。

`io_uring` 的 SQE 描述请求，CQE 描述完成。用户缓冲区在完成前必须保持有效；一个 stream socket 上并发多个 send 或多个 recv 可能重排，必须用单写者、链接请求或明确顺序机制。

<a id="backpressure"></a>
## 背压与有界状态

如果生产速率 $\lambda$ 长期大于消费速率 $\mu$，任何无限队列最终都会耗尽内存。服务端应给每连接与全局出站队列设上限：

```text
on_response(bytes):
  if conn.pending + len(bytes) > conn.high_water:
      pause_read(conn)
      reject_or_cancel_excess_work()
  enqueue(bytes)

on_writable:
  flush_until_EAGAIN()
  if conn.pending < conn.low_water:
      resume_read(conn)
```

高低水位形成迟滞，避免频繁启停。背压要沿依赖链传播：仅停止 socket 读取但继续从数据库拉取结果，内存仍会增长。

<a id="cancellation"></a>
## 取消、超时与资源所有权

- 使用单调时钟表达 deadline，避免墙钟校准导致超时倒退。
- 取消是状态转换，不等于线程或内核 I/O 已立刻停止；完成事件仍可能到达。
- fd 数字关闭后可被复用，异步回调应携带 generation/token，不能只比较整数 fd。
- 每个连接明确唯一 owner，或对共享状态使用同步；事件循环并不自动消除跨线程竞态。
- `SIGPIPE` 可通过 `MSG_NOSIGNAL` 等方式处理；发送成功也只表示数据进入本机协议栈。

## 测量与排障

同时观测 accept rate、活动连接、收发队列字节、事件循环延迟、每连接 pending bytes、`EAGAIN`、重传与 fd 上限。`strace` 适合验证 syscall 语义，`perf`/eBPF 用于定位调度和内核热点，但插桩本身会改变高频路径。

```text
ss -lntp
ss -tinm
cat /proc/net/sockstat
cat /proc/<pid>/limits
```

## 从接口回到协议

- [TCP、UDP 与 QUIC](transport-tcp-udp-quic.md)定义字节流、数据报与多流传输真正提供的边界。
- [DNS、HTTP 与 TLS](dns-http-tls.md)展示这些 I/O 状态怎样进入一次完整请求的握手、复用与超时预算。
- [拥塞控制](congestion-control.md)解释 socket 可写并不等于路径没有排队或拥塞。
- [可靠性与可观测性](../distributed/reliability-observability.md)把取消、重试和指标放回端到端故障模型。

## Reference

- [socket(7) — Linux manual page](https://man7.org/linux/man-pages/man7/socket.7.html)
- [accept(2) — Linux manual page](https://man7.org/linux/man-pages/man2/accept.2.html)
- [recv(2) — Linux manual page](https://man7.org/linux/man-pages/man2/recv.2.html)
- [send(2) — Linux manual page](https://man7.org/linux/man-pages/man2/send.2.html)
- [epoll(7) — Linux manual page](https://man7.org/linux/man-pages/man7/epoll.7.html)
- [io_uring(7) — Linux manual page](https://man7.org/linux/man-pages/man7/io_uring.7.html)
- [Linux io_uring zero-copy receive documentation](https://docs.kernel.org/networking/iou-zcrx.html)
