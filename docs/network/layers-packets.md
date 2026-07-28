# 分层、分组与端到端路径

<a id="packet-life"></a>
## 一个字节如何穿过网络

应用交给 socket 的不是“网络包”，而是一段数据与传输语义。发送侧依次增加传输头、IP 头和链路头；网卡把帧编码成物理信号。路由器通常只处理到网络层：去掉入站链路头，检查 IP 头、递减 TTL/Hop Limit，查下一跳，再封装新的出站链路头。接收侧反向解封装，最终把数据交给对应 socket。

分层的价值是限制变化范围：以太网可以换成 Wi-Fi 而不改变 HTTP 语义，IPv4 可以与 IPv6 共存而不要求应用重写所有业务逻辑。但层不是性能隔离墙：TLS 记录大小会改变 TCP 分段，TCP 拥塞又会影响 HTTP 尾延迟。

| 单位 | 典型名字 | 是否保留应用消息边界 |
| --- | --- | --- |
| 应用层 | message / request | 由协议决定 |
| TCP | byte stream / segment | 否 |
| UDP | datagram | 是，但仍受最大报文与分片约束 |
| IP | packet | 是逐跳转发单位 |
| Ethernet | frame | 只在当前链路有效 |

<a id="delay-model"></a>
## 时延与带宽时延积

一跳时延可拆成：

$$
d=d_{\text{proc}}+d_{\text{queue}}+\frac{L}{R}+d_{\text{prop}}
$$

- $d_{\text{proc}}$：解析、校验、路由查找；
- $d_{\text{queue}}$：等待出端口，负载接近容量时高度波动；
- $L/R$：长度为 $L$ 比特的包在速率 $R$ 链路上的发送时间；
- $d_{\text{prop}}$：信号传播时间。

带宽时延积（BDP）是“管道中可同时飞行的数据”：

$$
\mathrm{BDP}=R\cdot RTT
$$

若发送窗口小于 BDP，链路无法被填满；若缓冲远大于 BDP，丢包可能减少，但排队时延会变得巨大，即 bufferbloat。

<a id="mtu"></a>
## MTU、分段与 PMTU

链路 MTU 限制一个 IP 包的大小。IPv4 路由器可以分片，但现代实现通常设置 DF 并依赖 Path MTU Discovery；IPv6 路由器不做途中分片，源主机依据 ICMPv6 Packet Too Big 调整。TCP 通过 MSS 尽量让每个 segment 加上 IP/TCP 头后不超过路径 MTU。

如果 ICMP 被错误过滤，PMTUD 会形成“握手成功、大包卡死”的黑洞。诊断时应比较：

```text
tracepath destination
ping -M do -s 1472 destination   # IPv4: 1472 payload + 28-byte headers = 1500
tcpdump -ni any 'icmp or icmp6'
```

不要把 TSO/GSO 下主机抓包看到的超大 segment 当成线上的巨型帧：分段可能在协议栈更晚处或网卡完成。接收侧 GRO/LRO 也会把多个包合并后再交给上层。

<a id="queues"></a>
## 队列、丢包与 Little 定律

稳定系统中，Little 定律给出：

$$
N=\lambda W
$$

平均在途请求数 $N$ 等于到达率 $\lambda$ 与平均停留时间 $W$ 的乘积。它不是容量规划的全部，却能快速识别矛盾：若服务声称 10 万请求/秒、平均延迟 20 ms，则平均至少有 2000 个请求处于系统内。

队列管理有三种不同目标：

- tail drop 简单，但可能产生全局同步和长队列；
- AQM 在缓冲耗尽前丢包或标记 ECN，以时延换反馈；
- 调度器在流或流量类别之间分配链路，解决隔离而不直接解决总容量。

## 失败模式与测量

| 现象 | 先验证 | 不充分的解释 |
| --- | --- | --- |
| 小包通、大包不通 | PMTU、ICMP、隧道开销 | “防火墙随机丢包” |
| 吞吐低但无丢包 | RTT、发送/接收窗口、单流 CPU | “带宽没买够” |
| P99 突升 | 队列、重传、GC/调度暂停 | 只看平均 RTT |
| 抓包校验和错误 | checksum offload 位置 | 立刻判断线上损坏 |
| 跳数偶尔变化 | ECMP 哈希、路由收敛 | 认为一定发生故障 |

抓包应记录观察点、接口、方向、snaplen、时间同步与 offload 配置。网络事实具有观察点依赖性：应用写入时间、内核发送时间、网卡出线时间并不相同。

## 沿路径继续

- [以太网、IP 与路由](ethernet-ip-routing.md)展开当前一跳的帧交付与跨网段转发。
- [TCP、UDP 与 QUIC](transport-tcp-udp-quic.md) 说明端点怎样在 IP 之上建立字节流、数据报或多流语义。
- [拥塞控制](congestion-control.md)把 BDP、队列和反馈闭环连接起来。

## Reference

- [RFC 1122: Requirements for Internet Hosts — Communication Layers](https://www.rfc-editor.org/rfc/rfc1122)
- [RFC 9293: Transmission Control Protocol](https://www.rfc-editor.org/rfc/rfc9293.html)
- [RFC 8200: Internet Protocol, Version 6](https://www.rfc-editor.org/rfc/rfc8200)
- [RFC 1191: Path MTU Discovery](https://www.rfc-editor.org/rfc/rfc1191)
- [RFC 8201: Path MTU Discovery for IPv6](https://www.rfc-editor.org/rfc/rfc8201)
- [RFC 7323: TCP Extensions for High Performance](https://www.rfc-editor.org/rfc/rfc7323)
- [Linux networking documentation](https://docs.kernel.org/networking/index.html)
- [Linux segmentation offloads documentation](https://docs.kernel.org/networking/segmentation-offloads.html)
