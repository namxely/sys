# 数据中心网络与 RDMA

数据中心把大量短流、突发 fan-in、存储复制和批量训练放在微秒到毫秒尺度的共享 fabric 中。公网设计中的“路径不可控”在这里变成“拓扑可控但竞争极强”，因此拓扑、队列、传输与应用必须共同设计。

<a id="clos"></a>
## Clos 与多路径

leaf-spine 是 Clos 网络的常见实现：服务器接 leaf，leaf 与所有 spine 相连。若上行不过度超卖，任意两台服务器之间拥有近似均匀的路径容量。ECMP 按流哈希选择等价路径，避免逐包乱序，但会产生哈希碰撞和 elephant 热点。

设每台 leaf 有 $n_d$ 个速率 $R_d$ 的下行口、$n_u$ 个速率 $R_u$ 的上行口，超卖比为：

$$
\rho=\frac{n_dR_d}{n_uR_u}
$$

$\rho=1$ 表示理论无超卖，但实际仍受 spine 故障、哈希、端口缓冲和流量矩阵影响。VLAN/VXLAN 解决租户隔离与地址扩展，underlay 提供 IP 可达，overlay 提供逻辑网络。

<a id="incast"></a>
## Incast、微突发与 DCTCP

查询同时向许多 worker 发出，响应在同一接收端口汇聚，会在一个 RTT 内形成 incast。平均利用率可能很低，瞬时队列却溢出。深缓冲减少丢包但增加 tail latency；浅缓冲配合 ECN 与 DCTCP 可更早反馈拥塞。

DCTCP 估计被 ECN 标记的字节比例并按程度收缩窗口，而不是每次拥塞都减半。它依赖一致的 ECN 阈值、端主机支持和受控 RTT；跨域路径不能盲目沿用同一参数。

<a id="rdma"></a>
## RDMA 的数据路径

RDMA 允许 NIC 在注册内存与远端注册内存之间直接搬运数据，减少内核数据路径、复制和 CPU 参与。常见操作：

- SEND/RECV：消息式，两端都参与缓冲区管理；
- RDMA READ：发起端从远端读取；
- RDMA WRITE：发起端写入远端；
- atomics：对特定大小远端值做原子更新。

基本对象包括 protection domain、memory region、completion queue 与 queue pair。内存注册建立地址转换与访问权限，代价不可忽略；key 失效、缓冲区生命周期和 completion 消费属于正确性边界。

one-sided 操作只保证 NIC 层面的完成语义，不自动等于应用事务提交。远端 CPU 何时观察到数据、持久介质何时落盘、元数据与 payload 如何原子关联，都需要更高层协议。

<a id="roce"></a>
## InfiniBand、RoCE 与拥塞

InfiniBand 定义完整 fabric；RoCE 把 RDMA 语义映射到 Ethernet，RoCEv2 可在 UDP/IP 上路由。传统 RoCE 部署常借助 PFC 构造近似无损网络，但 PFC 会传播暂停、造成 head-of-line blocking，极端时形成死锁。ECN/DCQCN 等端到端拥塞控制与合理缓冲、隔离和监控同样关键。

“零拷贝”也不是零成本：

$$
T=T_{\text{registration/amortized}}+T_{\text{doorbell}}
+T_{\text{DMA}}+T_{\text{network}}+T_{\text{completion}}
$$

小消息可能受 doorbell、PCIe 和 completion 支配；大消息更受带宽与 NUMA/PCIe 拓扑影响。

<a id="measurement"></a>
## 设计与测量

- 把 NIC 放在正确 NUMA 节点，固定线程并验证 PCIe 路径。
- 分别测 SEND/RECV、READ、WRITE 的单向延迟、双向带宽与队列深度曲线。
- 同时报告 message size、QP 数、batch、inline threshold、MTU、拥塞控制和 PFC/ECN 配置。
- 记录 switch queue/ECN/PFC counters、NIC retry/CQE error 和应用 pending work。
- 故障注入覆盖链路 flap、QP error、远端进程重启、key 失效、CQ 溢出与慢消费者。

数据中心排障必须跨层：训练 collective 卡顿既可能是 GPU 等待，也可能是 rail 映射、ECMP 热点、PFC 风暴或某个 rank 未推进。

## 跨层连接

- [拥塞控制](congestion-control.md)详细解释 DCTCP、ECN、pacing 与队列反馈。
- [以太网、IP 与路由](ethernet-ip-routing.md)提供 underlay、ECMP 与逐跳转发的基础。
- [拓扑与通信优化](../parallel/topology-communication.md)把 NIC、NUMA、PCIe、GPU link 和 rank placement 放进同一成本图。
- [MPI 与集合通信](../parallel/mpi-collectives.md)说明 collective 怎样把通信模式投射到 fabric。

## Reference

- [VL2: A Scalable and Flexible Data Center Network](https://www.microsoft.com/en-us/research/publication/vl2-a-scalable-and-flexible-data-center-network/)
- [Data Center TCP](https://www.microsoft.com/en-us/research/publication/data-center-tcp-dctcp/)
- [RFC 8257: Data Center TCP](https://www.rfc-editor.org/rfc/rfc8257)
- [InfiniBand and RoCE Architecture Overview](https://www.infinibandta.org/wp-content/uploads/2022/07/IBTA-Overview-of-IBTA-Volume-1-Release-1.6-2022-07-15.pdf)
- [RDMA over Converged Ethernet — NVIDIA documentation](https://networking-docs.nvidia.com/onyxum/3.10.4800/rdma-over-converged-ethernet-roce)
- [Linux kernel InfiniBand documentation](https://docs.kernel.org/infiniband/index.html)
- [NVIDIA GPUDirect RDMA documentation](https://docs.nvidia.com/cuda/gpudirect-rdma/)
