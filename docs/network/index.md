# 计算机网络

网络把“远端内存不可直接读写”转化为一组可组合的通信抽象。真正理解网络，不是背七层名词，而是沿着一段数据的生命线追问：应用写下的字节如何被分段、寻址、排队、重传、加密和重新组装；拥塞、丢包、乱序、路径变化与部分故障又如何改变这些动作。

## 学习路径

1. [分层、分组与端到端路径](layers-packets.md)：建立封装、MTU、时延和吞吐的统一坐标系。
2. [以太网、IP 与路由](ethernet-ip-routing.md)：理解一跳交付、跨网转发和控制平面。
3. [TCP、UDP 与 QUIC](transport-tcp-udp-quic.md)：比较可靠字节流、无连接报文和加密多路复用传输。
4. [拥塞控制](congestion-control.md)：从拥塞窗口、ACK 时钟走到 ECN、CUBIC 与 BBR。
5. [DNS、HTTP 与 TLS](dns-http-tls.md)：沿一次 HTTPS 请求串起命名、语义、缓存和安全。
6. [Socket 与 I/O 模型](sockets-io.md)：把协议语义落到阻塞、就绪通知和完成通知。
7. [数据中心网络与 RDMA](datacenter-rdma.md)：理解 Clos、多路径、incast、无损语义与内存注册。

## 一张统一地图

| 观察层次 | 核心对象 | 主要不变量 | 常见误判 |
| --- | --- | --- | --- |
| 应用 | 请求、响应、消息 | 幂等性、超时预算 | 把一次超时当成一次失败 |
| 传输 | 流、数据报、连接 | 顺序、可靠性、拥塞公平 | 把消息边界交给 TCP 保存 |
| 网络 | 数据包、地址、路径 | 逐跳转发、TTL/Hop Limit | 把“能路由”当成“必可达” |
| 链路 | 帧、MAC、队列 | 同一链路上的交付 | 把广播域扩展成全网 |
| 物理 | 比特、符号 | 带宽、误码、传播 | 只看标称速率，不看队列 |

性能分析始终从四项开始：

$$
T_{\text{response}}
=T_{\text{DNS}}+T_{\text{connect}}+T_{\text{request}}
+T_{\text{server}}+T_{\text{response}}
$$

其中每一项都可能包含排队、重传与握手。平均值不能代表尾延迟；链路利用率接近容量时，排队等待往往先于吞吐下降而恶化。

## 实践方法

- 用 `ping` 只验证 ICMP 回显路径，不据此断言 TCP、UDP 或应用可用。
- 用 `traceroute` 或 `tracepath` 观察跳数和 PMTU，但接受负载均衡与 ICMP 策略造成的不完整视图。
- 用 `ss -tin` 读取 RTT、拥塞窗口与重传状态；用 `tcpdump` 验证线上的事实。
- 将应用日志、主机指标、交换机队列和抓包时间轴对齐，避免单点证据推断全链路。
- 压测时同时报告请求大小、并发、连接复用、预热、丢包、P50/P99 与错误率。

## Reference

- [RFC 1122: Requirements for Internet Hosts — Communication Layers](https://www.rfc-editor.org/rfc/rfc1122)
- [RFC 8200: Internet Protocol, Version 6](https://www.rfc-editor.org/rfc/rfc8200)
- [Linux kernel networking documentation](https://docs.kernel.org/networking/index.html)
- [MIT 6.1810: Operating System Engineering](https://pdos.csail.mit.edu/6.1810/)
