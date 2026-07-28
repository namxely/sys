# TCP、UDP 与 QUIC

<a id="semantics"></a>
## 先选语义，再选协议

| 能力 | TCP | UDP | QUIC |
| --- | --- | --- | --- |
| 应用看到的单位 | 有序字节流 | 数据报 | 多个可靠流与不可靠 datagram 扩展 |
| 可靠与有序 | 全连接一个序列空间 | 不提供 | 每条流独立有序 |
| 握手与加密 | TCP 与 TLS 分离 | 无内建 | TLS 1.3 集成 |
| 多路复用丢包阻塞 | 所有上层流共享 TCP 顺序 | 应用决定 | 通常只阻塞受影响的 QUIC stream |
| 连接迁移 | 四元组变化即新连接 | 应用决定 | Connection ID 支持路径迁移 |

UDP 不是“不可靠 TCP”，而是最小的多路复用数据报服务。应用若需要可靠性、分片、重传、拥塞控制与防放大，必须自行设计或采用 QUIC 等已定义协议。

<a id="tcp"></a>
## TCP：序列空间上的可靠字节流

三次握手让双方同步初始序列号并确认双向可达。发送方给字节编号；接收方累计确认下一个期望字节。重传由 RTO 与快速重传触发，流量控制由接收窗口 `rwnd` 限制，拥塞控制由 `cwnd` 限制：

$$
\text{flight size}\le \min(\mathrm{rwnd},\mathrm{cwnd})
$$

TCP 不保存应用 `write()` 的边界。一次写可能被拆成多次读，多次写也可能被一次读合并。因此应用必须定义 framing，例如固定头部携带长度，并处理 partial read/write。

连接关闭也有方向：`shutdown(SHUT_WR)` 发送 FIN，只表示本端不再发送；对端仍可继续回包。RST 表示异常终止，未读数据与应用级处理状态不能据此推断。

<a id="udp"></a>
## UDP：保留边界的最小传输

UDP 每次发送对应一个数据报，接收缓冲区太小时其余部分会被截断。它不保证：

- 报文到达或只到达一次；
- 顺序；
- 速率公平；
- 路径 MTU 适配；
- 源地址真实性。

面向公网的 UDP 服务必须限制放大：在验证客户端地址前，响应字节数不应远大于请求；还应实现令牌、速率限制与拥塞反馈。

<a id="quic"></a>
## QUIC：用户态、加密、多流

QUIC 把传输状态置于 UDP 之上，并将 TLS 1.3 握手集成进连接建立。Packet Number 不因重传复用；可靠性以 frame 和 stream offset 表达。ACK 确认包，但丢失包中的可重传 frame 可以装入新包。

每条 stream 有独立偏移，因此一个流丢包通常不阻塞其他流的数据交付；连接级与流级 flow control 同时存在。Connection ID 解耦连接身份与 IP/端口四元组，使 NAT rebinding 和迁移成为协议内能力。

0-RTT 降低重连延迟，却可能被重放。只有可重放安全的操作才应接受 early data；“TLS 已加密”不等于“业务不会重复执行”。

<a id="timeouts"></a>
## 超时、重试与幂等

传输超时只说明客户端没有及时观察到成功，不能证明服务器未执行。安全重试需要业务级请求 ID 与幂等记录：

```text
client: create(request_id, payload)
server:
  if request_id already committed: return stored result
  validate -> commit result and request_id atomically -> reply
```

退避可用带抖动的指数策略：

$$
t_k\sim U(0,\min(t_{\max},t_0 2^k))
$$

总超时预算应覆盖排队、DNS、握手、重传与服务时间，并向下游传播取消；每层独立设置宽松超时会让尾部请求在系统内长期堆积。

## 失败模式与观测

- SYN 重传：可能是请求或回包路径、监听队列、防火墙问题。
- 大量 zero window：接收应用消费不及，不是网络带宽不足。
- QUIC 退回 TCP：检查 UDP 阻断、版本协商与 HTTP Alt-Svc，而非直接归因服务器。
- UDP 丢包：同时检查 socket receive buffer、NIC ring、内核 backlog 和链路队列。
- `TIME_WAIT`：保护旧报文与关闭可靠性；盲目缩短可能制造四元组复用错误。

## 继续连接

- [分层、分组与端到端路径](layers-packets.md)解释传输数据最终受 MTU、BDP 与队列怎样约束。
- [拥塞控制](congestion-control.md)深入 `cwnd`、丢包恢复、ECN 与 pacing。
- [Socket 与 I/O 模型](sockets-io.md)把 short read/write、半关闭与异步完成落到接口。
- [DNS、HTTP 与 TLS](dns-http-tls.md)展示传输选择如何进入一次 HTTPS 请求。

## Reference

- [RFC 9293: Transmission Control Protocol](https://www.rfc-editor.org/rfc/rfc9293)
- [RFC 768: User Datagram Protocol](https://www.rfc-editor.org/rfc/rfc768)
- [RFC 9000: QUIC — A UDP-Based Multiplexed and Secure Transport](https://www.rfc-editor.org/rfc/rfc9000)
- [RFC 9001: Using TLS to Secure QUIC](https://www.rfc-editor.org/rfc/rfc9001)
- [RFC 9002: QUIC Loss Detection and Congestion Control](https://www.rfc-editor.org/rfc/rfc9002)
- [RFC 9221: An Unreliable Datagram Extension to QUIC](https://www.rfc-editor.org/rfc/rfc9221)
