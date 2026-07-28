# 以太网、IP 与路由

<a id="same-link"></a>
## 同一链路：MAC、帧与邻居发现

以太网帧用源、目的 MAC 地址在一个二层域中交付。交换机从入帧源地址学习“MAC → 端口”，目的未知时泛洪；表项老化后必须重新学习。VLAN 用 802.1Q 标签把同一物理网络切成多个逻辑广播域。

主机发送 IP 包前先判断目的地址是否在本地前缀：

- 同网段：解析目标主机的链路地址；
- 异网段：解析默认网关的链路地址，IP 目的地址仍是远端主机。

IPv4 用 ARP；IPv6 Neighbor Discovery 基于 ICMPv6，并承担路由器发现、前缀发现和邻居可达性检测。MAC 只负责当前一跳，因此每过一个路由器链路头都可能变化。

<a id="ip-forwarding"></a>
## IP：尽力而为的逐跳转发

IP 提供无连接、尽力而为的数据报服务，不承诺交付、顺序、唯一性或固定路径。路由器处理包时：

1. 校验头部与目的地址；
2. 递减 TTL/Hop Limit，耗尽则丢弃并通常返回 ICMP；
3. 对路由表做最长前缀匹配；
4. 选择下一跳与出接口；
5. 解析链路邻居并入队发送。

最长前缀匹配选择最具体的路由。例如 `10.1.2.0/24` 胜过 `10.1.0.0/16`。默认路由 `0.0.0.0/0` 或 `::/0` 仅在没有更具体项时生效。

IPv4 头校验和只保护头部；IPv6 删除了该字段，把完整性更多交给链路层和传输层。NAT 修改地址或端口并维护状态，它节省地址并形成运维边界，但不是端到端安全协议。

<a id="routing-control"></a>
## 路由控制平面

转发平面回答“这个包下一跳去哪”；控制平面回答“路由表为何有这条项”。

| 协议 | 范围 | 核心状态 | 选路直觉 |
| --- | --- | --- | --- |
| OSPF | 一个自治系统内部 | 链路状态数据库 | Dijkstra 最短路径 |
| BGP | 自治系统之间 | 路径属性与策略 | 先策略，后路径 |
| ECMP | 转发机制 | 多个等价下一跳 | 通常按流哈希 |

链路状态路由中，每台路由器泛洪本地邻接并独立计算最短路径。若边权为 $w(u,v)$，则：

$$
d(v)=\min_{(u,v)\in E}\{d(u)+w(u,v)\}
$$

BGP 传播的是可达前缀及 AS_PATH、LOCAL_PREF、MED 等属性。它不是全局最短路算法；商业关系、出口策略和稳定性常优先于跳数。

<a id="routing-failures"></a>
## 收敛、环路与黑洞

- 二层环路会复制广播帧；生成树或受控 fabric 用拓扑约束避免环路。
- 路由收敛期间，不同设备可能看到不一致的下一跳，形成瞬时环路或黑洞。
- ECMP 通常按五元组哈希；单流不会自动吃满所有路径，路径碰撞会造成热点。
- MTU、ACL、策略路由、反向路径过滤和 NAT 状态都可能让“路由存在”但业务不可达。
- BGP 路由泄漏和错误宣告属于策略正确性问题，不是数据平面重传能解决的问题。

## 测量与实践

```text
ip -br address
ip route get 203.0.113.10
ip neigh show
bridge fdb show
tracepath 203.0.113.10
tcpdump -eni eth0 'arp or icmp6'
```

诊断顺序应保持因果性：接口与地址 → 本地路由选择 → 邻居解析 → 出入方向抓包 → 对端反向路径。只在一端看到 SYN 发出，不能证明中间网络丢弃；也可能是对端或回程问题。

## 从一跳走向端到端

- [分层、分组与端到端路径](layers-packets.md)给出封装、MTU 与逐跳观察点的全景。
- [TCP、UDP 与 QUIC](transport-tcp-udp-quic.md) 说明路径变化最终如何影响端到端传输状态。
- [数据中心网络与 RDMA](datacenter-rdma.md) 把 ECMP、Clos 与受控 fabric 中的队列问题进一步展开。

## Reference

- [IEEE 802.3 Ethernet Working Group](https://www.ieee802.org/3/)
- [IEEE 802.1Q Bridged Networks](https://1.ieee802.org/tsn/802-1q/)
- [RFC 826: An Ethernet Address Resolution Protocol](https://www.rfc-editor.org/rfc/rfc826)
- [RFC 4861: Neighbor Discovery for IPv6](https://www.rfc-editor.org/rfc/rfc4861)
- [RFC 8200: Internet Protocol, Version 6](https://www.rfc-editor.org/rfc/rfc8200)
- [RFC 2328: OSPF Version 2](https://www.rfc-editor.org/rfc/rfc2328)
- [RFC 4271: A Border Gateway Protocol 4](https://www.rfc-editor.org/rfc/rfc4271)
