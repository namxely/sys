# 拥塞控制

流量控制保护接收端，拥塞控制保护网络。发送方即使面对无限接收缓冲，也不能以任意速率向有限容量的路径注入数据；否则队列增长、丢包和重传会形成拥塞崩溃。

<a id="ack-clock"></a>
## ACK 时钟与窗口

在窗口式控制中，近似发送速率为：

$$
x\approx \frac{\mathrm{cwnd}}{RTT}
$$

ACK 返回释放在途额度并驱动新发送，形成 ACK clock。慢启动每收到 ACK 增长窗口，理想情况下每 RTT 近似翻倍；进入拥塞避免后增速减缓。丢包或 ECN 是容量不足的反馈，不应仅作为“传输错误”隐藏。

经典 AIMD 每个 RTT 加性增长，检测拥塞后乘性降低：

$$
W\leftarrow
\begin{cases}
W+\alpha,&\text{no congestion}\\
\beta W,&\text{congestion}
\end{cases}
\qquad 0<\beta<1
$$

<a id="loss-recovery"></a>
## 丢包检测与恢复

RTO 依据平滑 RTT 与偏差计算，并必须有最小值与指数退避。重复 ACK 或 SACK 能在超时前指出缺口；RACK 等现代机制更多利用发送时间判断丢失。错误的重传会浪费容量，过晚重传则放大尾延迟。

应用观测“重传率”时需要区分：

- 原始包确实丢失；
- ACK 丢失或乱序导致伪重传；
- TSO/GRO 使抓包统计与线上包不一致；
- 连接迁移或路径变化使 RTT 基线过时。

<a id="algorithms"></a>
## Reno、CUBIC、DCTCP 与 BBR

**Reno/NewReno** 用丢包作为拥塞信号，窗口增长与 RTT 强相关。**CUBIC** 让窗口围绕上次拥塞点按时间的三次函数增长，在高 BDP 路径上更积极，同时保留 TCP 友好区。

**DCTCP** 依赖 ECN：交换机在队列超过阈值时标记 CE，接收端回显，发送端估计被标记字节比例 $\alpha$：

$$
\alpha\leftarrow (1-g)\alpha+gF,\qquad
\mathrm{cwnd}\leftarrow \mathrm{cwnd}\left(1-\frac{\alpha}{2}\right)
$$

它用多比特程度反馈维持浅队列，适合受控数据中心；配置不一致会破坏其假设。

**BBR** 建模瓶颈带宽 $BtlBw$ 与最小传播 RTT $RTprop$，目标在途量接近：

$$
\mathrm{inflight}\approx BtlBw\cdot RTprop
$$

它主动改变 pacing gain 探测带宽与 RTT，而非简单等待丢包。模型误差、竞争协议和 policer 仍会影响公平与稳定性。

<a id="queue-management"></a>
## 队列管理、ECN 与 pacing

- pacing 把窗口内数据平滑到时间轴，减少微突发；
- AQM 依据排队时延或队列状态提前丢包/标记；
- ECN 在不丢包时传递拥塞，但端点和中间设备必须正确协作；
- fair queuing 隔离流，避免一个大流完全占据队列。

容量规划不能只盯吞吐。对交互请求，目标常是控制 $\text{queueing delay}$；对批处理，目标可能是稳定吃满瓶颈。两类流共用一个 FIFO 深队列时目标天然冲突。

## 实验与诊断

```text
ss -tin dst 203.0.113.10
tc -s qdisc show dev eth0
ip -s link show dev eth0
nstat -az | grep -E 'Retrans|ECN|Timeout'
```

可用 `tc netem` 在隔离环境注入固定 RTT、抖动、丢包和重排，再比较 goodput、P50/P99、重传与队列长度。报告必须注明拥塞算法、qdisc、buffer、连接数、流长、方向与预热；单流峰值不能代表公平性或生产尾延迟。

## 把反馈放回路径

- [TCP、UDP 与 QUIC](transport-tcp-udp-quic.md)说明不同传输如何承载可靠性与拥塞反馈。
- [分层、分组与端到端路径](layers-packets.md)提供 BDP、队列与 PMTU 的基础坐标。
- [数据中心网络与 RDMA](datacenter-rdma.md)展示 DCTCP、incast 与 PFC 在受控 fabric 中的取舍。
- [Socket 与 I/O 模型](sockets-io.md)连接 `cwnd`、可写事件和应用背压，避免把任一层单独优化。

## Reference

- [RFC 5681: TCP Congestion Control](https://www.rfc-editor.org/rfc/rfc5681)
- [RFC 9438: CUBIC for Fast and Long-Distance Networks](https://www.rfc-editor.org/rfc/rfc9438)
- [RFC 3168: Explicit Congestion Notification](https://www.rfc-editor.org/rfc/rfc3168)
- [Data Center TCP](https://www.microsoft.com/en-us/research/publication/data-center-tcp-dctcp/)
- [BBR: Congestion-Based Congestion Control](https://research.google/pubs/bbr-congestion-based-congestion-control/)
- [RFC 9002: QUIC Loss Detection and Congestion Control](https://www.rfc-editor.org/rfc/rfc9002)
- [Linux TCP sysctl documentation](https://docs.kernel.org/networking/ip-sysctl.html)
