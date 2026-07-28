# 时间、因果与全序

<a id="physical-time"></a>
## 物理钟为何不等于事实顺序

节点时钟由振荡器推进，会产生 drift；NTP/PTP 只能在网络延迟和硬件误差下估计偏移。时钟可能被 step 或 slew 校准，墙钟时间可跳变。超时应使用 monotonic clock；审计时间戳则要保留同步状态和不确定性。

即使两个事件时间戳分别为 10:00:00.100 和 10:00:00.101，若误差各为 ±5 ms，也不能断言前者真实更早。物理时间接口最好表达区间：

$$
TT.now()=[t_{\mathrm{earliest}},t_{\mathrm{latest}}]
$$

Spanner 的 TrueTime 用显式不确定区间与 commit wait 支持外部一致性；这依赖受控时钟基础设施，不是普通 `now()` 的自然性质。

<a id="happened-before"></a>
## Happened-Before

Lamport 定义 $a\rightarrow b$：

1. 同一进程中 $a$ 先于 $b$；
2. $a$ 是发送、$b$ 是对应接收；
3. 关系传递。

若既非 $a\rightarrow b$ 也非 $b\rightarrow a$，两事件并发。因果偏序比墙钟更接近系统可知事实。

<a id="lamport-clock"></a>
## Lamport Clock

每个进程维护整数 $C$：

```text
before local/send event: C := C + 1
send message with C
on receive timestamp t: C := max(C, t) + 1
```

保证：

$$
a\rightarrow b\implies C(a)<C(b)
$$

逆命题不成立：$C(a)<C(b)$ 不能证明因果。用 `(C, process_id)` 可构造确定全序，但这个全序包含人为打破的并发关系。

<a id="vector-clock"></a>
## Vector Clock

$N$ 个进程各维护长度 $N$ 向量。本地事件递增自己的分量；发送携带向量；接收逐分量取 max 后递增自身。定义：

$$
V(a)<V(b)
\iff
\left(\forall i,\ V_i(a)\le V_i(b)\right)
\land
\left(\exists j,\ V_j(a)<V_j(b)\right)
$$

则 $a\rightarrow b$ 当且仅当 $V(a)<V(b)$。两个向量不可比较表示并发。代价是元数据随参与者增长；动态大规模系统会用 version vector、dotted version vector 或按对象裁剪。

<a id="hlc"></a>
## Hybrid Logical Clock

HLC 组合物理部分 $l$ 与逻辑计数 $c$，在保持因果单调的同时让时间接近物理钟。它适合按时间范围查询和 MVCC timestamp，但不会神奇消除 clock uncertainty。若上层契约依赖“时间戳与物理时间相差不超过某界”或据此承诺外部一致性，时钟超出该界时才必须拒绝、隔离或降级；HLC 的因果单调性质本身不等于这类物理时间承诺。

<a id="ordering-services"></a>
## 从偏序到日志全序

状态机复制常需要所有副本对命令采用相同 total order。逻辑时钟只能标记/排序事件，不能在故障下让节点就某个唯一顺序达成协议；后者需要[复制与共识](replication-consensus.md)。

按时间戳排序还需处理：

- 相同时间戳 tie-break；
- 晚到但时间更小的消息；
- 成员和时钟状态变化；
- 已向外输出结果后是否允许重排。

## 实践与失败注入

- 超时、租约和重试用 monotonic deadline；持久化 deadline 时保存剩余策略而非裸 monotonic 值。
- 日志同时记录 wall time、monotonic duration、node/trace ID 与 clock-sync health。
- 注入 clock step、drift、NTP 不可达、消息延迟和重排。
- 用 history checker 验证对外一致性，而非按本机日志行号猜全序。
- 租约必须把最大时钟偏差和暂停纳入安全证明；GC pause 可能让旧 leader 醒来后误以为租约仍有效。

## 时间进入协议之后

- [事务与隔离](transactions-isolation.md)连接 snapshot timestamp、serializability 与 external consistency。
- [可靠性与可观测性](reliability-observability.md)把时钟健康、deadline 与跨服务 trace 放回运维现场。

## Reference

- [Lamport: Time, Clocks, and the Ordering of Events](https://lamport.azurewebsites.net/pubs/time-clocks.pdf)
- [Mattern: Virtual Time and Global States of Distributed Systems](https://vs.inf.ethz.ch/publ/papers/VirtTimeGlobStates.pdf)
- [RFC 5905: Network Time Protocol Version 4](https://www.rfc-editor.org/rfc/rfc5905)
- [IEEE 1588 Precision Time Protocol](https://standards.ieee.org/ieee/1588/6825/)
- [Spanner: Google's Globally-Distributed Database](https://research.google/pubs/spanner-googles-globally-distributed-database-2/)
- [Logical Physical Clocks and Consistent Snapshots](https://cse.buffalo.edu/tech-reports/2014-04.pdf)
