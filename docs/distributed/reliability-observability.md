# 可靠性与可观测性

可靠性不是“节点永不坏”，而是系统在给定故障与负载下仍满足用户可观察的目标，并能在越界时快速检测、止损和恢复。可观测性则让内部状态能由 traces、metrics、logs 和 profiles 推断；采集更多数据本身不保证能回答问题。

<a id="slo"></a>
## SLI、SLO 与 Error Budget

SLI 是用户相关测量，如成功请求比例或满足延迟阈值的比例。窗口内可用性：

$$
A=\frac{\text{good events}}{\text{valid events}}
$$

SLO 定义目标，error budget 为 $1-\mathrm{SLO}$。分母必须排除什么、重试算几次、部分响应是否 good，都需明确。基础设施 CPU 不是用户 SLI。

复合串联系统若故障独立且任一失败即整体失败：

$$
A_{\text{series}}=\prod_i A_i
$$

独立假设通常不成立；共享 DNS、证书、配置和机房会产生相关故障。

<a id="timeouts"></a>
## Timeout、Retry、Hedging 与负载

timeout 应从端到端 deadline 向下游分配。重试会放大负载；原始失败率 $p$、最多 $k$ 次尝试的独立理想失败概率是 $p^k$，但故障往往相关，且额外尝试增加拥塞，使 $p$ 上升。

安全策略：

- 只对可重试错误和幂等操作重试；
- 指数退避 + jitter；
- retry budget 限制额外流量；
- 传播 cancellation；
- hedged request 仅在尾延迟收益大于额外负载时，并取消输家；
- overload 时 admission control 和背压优先于无限排队。

<a id="failure-detectors"></a>
## 故障检测与降级

超时是怀疑，不是证明。阈值过短会误报并触发抖动，过长会延迟恢复。failure detector 应结合连续成功/失败、phi accrual 或健康状态，但最终协议仍要容忍误判。

降级必须保持核心不变量：

- stale read 是否允许、最大陈旧多久；
- 写是否排队、拒绝或转本地；
- cache fallback 是否会泄漏租户数据；
- 关闭某项校验是否扩大安全风险；
- 恢复时如何处理积压和重复。

<a id="telemetry"></a>
## Metrics、Logs 与 Traces

**Metrics** 适合聚合趋势与告警；**logs** 保存离散事件和诊断上下文；**traces** 用 parent/child span 还原一次请求跨服务关键路径。

trace context 必须跨 RPC、队列和异步任务传播。sampling 要保留错误和高延迟的代表性，但 tail-based sampling 会增加缓冲与决策延迟。高基数 label 会让 metrics 后端失控，应把 request ID 放 trace/log 而非 time-series label。

RED 与 USE 是互补视角：

- 服务：rate、errors、duration；
- 资源：utilization、saturation、errors。

平均延迟不可相加推导 P99；端到端 trace 与分布需保留。

<a id="recovery"></a>
## 备份、恢复与灾难演练

RPO 是可接受数据丢失窗口，RTO 是恢复时间目标。复制减少故障切换时间，却会同步复制误删与软件错误；不可变、隔离、定期验证的备份仍必要。

恢复演练应验证：

1. 备份可发现、可解密、校验通过；
2. 在新环境恢复元数据和数据；
3. 应用级不变量与权限正确；
4. DNS/流量切换可控；
5. 实测 RPO/RTO；
6. 故障期间写入和重放策略明确。

<a id="testing"></a>
## 从单元测试到混沌实验

- 单元/属性测试验证局部状态机。
- 确定性模拟枚举消息、超时、崩溃顺序。
- model checking 验证有限状态安全/活性。
- fault injection 验证真实实现错误路径。
- load + failure 联合测试揭示恢复风暴。
- game day 验证人员、权限、runbook 和沟通。

实验必须有 steady-state hypothesis、blast radius、abort condition 和恢复验证。不要把生产故障当成第一次备份恢复测试。

## 可靠性依赖的机制

- [复制与共识](replication-consensus.md)提供 leader、quorum、日志恢复与成员变更的状态来源。
- [时间、因果与全序](time-order.md)解释 deadline、clock health 与跨节点事件排序。
- [TCP、UDP 与 QUIC](../network/transport-tcp-udp-quic.md)说明 timeout 为什么不能证明请求未执行。
- [拓扑与通信优化](../parallel/topology-communication.md)帮助定位 collective straggler、链路热点与跨层退化。

## Reference

- [Dapper: A Large-Scale Distributed Systems Tracing Infrastructure](https://research.google/pubs/dapper-a-large-scale-distributed-systems-tracing-infrastructure/)
- [OpenTelemetry Specification](https://opentelemetry.io/docs/specs/otel/)
- [Google SRE Book: Service Level Objectives](https://sre.google/sre-book/service-level-objectives/)
- [Google SRE Workbook: Implementing SLOs](https://sre.google/workbook/implementing-slos/)
- [RFC 8633: Network Time Protocol Best Current Practices](https://www.rfc-editor.org/rfc/rfc8633)
- [TLA+ Home Page](https://lamport.azurewebsites.net/tla/tla.html)
- [Amazon Builders' Library: Timeouts, Retries, and Backoff with Jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)
