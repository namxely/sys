# 指标、日志、追踪与连续剖析

可观测性不是“装了监控”，而是能否从系统输出的证据中回答内部状态问题。一个成熟系统既要能看到已知故障，也要能调查事先没有写进告警规则的问题；后者要求信号共享身份、时间与语义，而不只是堆积四套互不相通的数据。

本文以 OpenTelemetry Specification 1.59.0、OTLP 1.11.0、Semantic Conventions 1.43.0 和 W3C Trace Context Recommendation 为边界。OpenTelemetry 各语言 SDK、Collector component 与 semantic convention 的稳定性并不相同，使用前应锁定依赖版本并检查对应 stability 标记。

## 从问题选择信号 {#signals}

| 信号 | 最自然的问题 | 典型粒度 | 不擅长回答 |
| --- | --- | --- | --- |
| metric | 发生了多少、趋势是否异常 | 时间窗内聚合 | 某个请求经过了什么 |
| log | 某个离散事件携带了哪些字段 | event | 全局分布与调用因果 |
| trace | 一次事务跨组件如何传播 | request/transaction | 函数内部 CPU 热点 |
| profile | 资源消耗落在哪些调用栈 | stack sample | 业务语义与远端因果 |

它们的连接点比各自的数量更重要：

- metric exemplar 指向一个代表性 trace；
- span 带稳定的 service、operation 与 status 语义；
- log 带 trace/span ID，但不复制整份 span；
- profile sample 能关联 process、service、deployment，条件允许时再关联 trace；
- deployment、feature flag 与配置变更进入同一时间线。

只保留“CPU 80%”不足以调查：要知道哪个 workload、哪个 cgroup、哪版 binary、哪类 request，以及时间窗内是否发生频率、GC、队列或下游变化。

## 统一的数据身份 {#identity}

OpenTelemetry 的 telemetry entity 通常由三层描述：

1. **Resource**：产生数据的实体，如 service、process、container、host；
2. **Instrumentation Scope**：哪个 library/name/version 产生数据；
3. **Signal record**：metric point、log record、span 或 profile sample。

Resource attribute 应在进程生命周期内相对稳定。高变化字段如 `user.id`、URL query、随机 job ID 不应混入 resource；否则同一服务被切成海量时间序列与存储分区。

命名要区分：

- **身份**：`service.name`、deployment environment；
- **工作类别**：route、RPC method、queue name；
- **单次实例**：trace ID、request ID；
- **结果**：status、error type；
- **测量值**：duration、bytes、queue depth。

单次实例适合 log/trace，不适合 metric label。把 request ID 放进 counter attribute，会让每次请求创建一条新 time series。

## Trace：跨边界保存因果 {#traces}

trace 由 span 构成。span 至少需要：

- trace ID 与 span ID；
- operation name；
- start/end timestamp；
- parent 或 link；
- attributes、events 与 status；
- resource 和 instrumentation scope。

### Parent 与 Link

parent-child 表示一个主要因果树，例如 HTTP server span 调用 database client span。link 表示不能自然归入一棵树的关系：

- batch 从多个 message 聚合；
- fan-in job 依赖多个上游；
- queue consumer 与 producer 跨越较长时间；
- retry attempt 与原始 attempt；
- trace 被异步任务继续，但生命周期独立。

不要为了画成漂亮的树而伪造 parent。错误的因果结构会让 critical path、service graph 与 latency attribution 都失真。

### W3C Trace Context

HTTP `traceparent` 的核心字段为：

```text
version-trace-id-parent-id-trace-flags
00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
```

接收方必须校验长度、十六进制格式、全零 ID 和版本规则，再创建本地 span。`tracestate` 承载 vendor-specific 状态；它不是任意 metadata 通道。

跨 trust boundary 时，传播上下文属于安全输入：

- 外部 trace ID 可保留连续性，但不能因此信任对方的采样或身份声明；
- baggage 可能被最终用户构造，不应装 secret、令牌或高敏个人信息；
- 限制 header 数量与长度，避免转发放大；
- 不把 trace attribute 自动复制到 metric label。

### Span 边界

每个函数一个 span 会产生噪声和成本。优先为这些边界建 span：

- network/database/message broker 调用；
- queue 等待与异步 hand-off；
- 用户可感知的高层 operation；
- 独立 retry attempt；
- 跨 runtime、process 或权限域的工作。

进程内短函数的 CPU 分解通常交给 profile。span event 适合记录 operation 内少量关键转折，不适合逐行日志。

## Metric：在聚合中保存语义 {#metrics}

metric instrument 要匹配被测量的数学性质：

| Instrument/聚合 | 适合 | 常见错误 |
| --- | --- | --- |
| counter/sum | requests、bytes、errors 的累计增量 | 表示可下降的 queue depth |
| up-down counter | active requests、allocated units | 当成跨进程全局唯一 gauge |
| gauge | 当前温度、队列深度、利用率快照 | 对每次事件都发一个随机 ID |
| histogram | duration、size 的分布 | 只保存平均数 |

### Temporality

累计 temporality 从起点给总量；增量 temporality 给相邻 collection interval 的变化。转换时必须处理：

- process restart/reset；
- collector 丢失 interval；
- counter wrap 或错误下降；
- multiple writer；
- start timestamp。

rate 是对 sum 在时间上的派生，不是另一个随意累加的 counter。

### Histogram 与尾部

平均延迟

$$
\bar{x} = \frac{1}{n}\sum_{i=1}^{n}x_i
$$

无法区分“全部 100 ms”和“99% 10 ms、1% 9 s”。histogram 保存 bucket/count/sum，后端才能估 quantile。估计精度受 bucket boundary 影响；不同 boundary 的 histogram 不能在不定义重桶规则时直接合并。

percentile 也不可相加：

$$
p_{99}(A+B) \ne p_{99}(A)+p_{99}(B)
$$

通常只有在强条件下才能用 convolution 或原始联合分布推导。端到端 trace 的 critical path 与服务侧 histogram 应互相校验。

### Cardinality

若 metric 有 $k$ 个 attributes，第 $i$ 个有 $c_i$ 个活跃值，最坏 time-series 数量近似：

$$
C \leq \prod_{i=1}^{k} c_i
$$

实际组合未必全出现，但乘法增长足以制造事故。route template 比 raw URL 好；error class 比完整 message 好；tenant 只有在容量与访问控制允许时才适合作为维度。

### Exemplar

exemplar 在一个聚合数据点旁保留代表性测量和 trace/span context。它让“p99 bucket 上升”可跳到一个真实慢请求，同时不把每个 trace ID 变成 label。exemplar 是抽样桥梁，不代表该 bucket 的所有事件。

## Log：把事件写成可查询记录 {#logs}

结构化 log 的价值不只是 JSON，而是稳定 schema：

```json
{
  "timestamp": "2026-07-28T08:00:00.123Z",
  "severity": "ERROR",
  "service": "checkout",
  "event": "payment_attempt_failed",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "error_type": "deadline_exceeded",
  "attempt": 2,
  "elapsed_ms": 803
}
```

应稳定的是 field 语义，不是 message 文案。建议：

- `event` 用低基数机器可读名字；
- error 保留 type/code/stack，避免只写 `failed`；
- time 用统一绝对时间，并在 duration 字段明确单位；
- request body、token、cookie、credential 默认不记录；
- 大 payload 写摘要、尺寸与受控引用，不全文复制；
- retry 每个 attempt 可记录，但最终 operation 只计算一次业务结果。

同一异常被每层 catch 后重复记成 ERROR 会造成告警放大。选择一个拥有处理责任的层记录主要错误，下层把细节附在 span event 或向上传递的 error chain。

### 标准库级关联示例

下面的 Go 代码只演示 context 中的 trace identity 如何进入结构化日志；真正的 span 创建与传播应由选定的 OpenTelemetry SDK 完成：

```go
package main

import (
	"context"
	"encoding/json"
	"os"
)

type traceKey struct{}

type event struct {
	Name    string `json:"event"`
	TraceID string `json:"trace_id,omitempty"`
	Value   int    `json:"value"`
}

func writeEvent(ctx context.Context, name string, value int) error {
	e := event{Name: name, Value: value}
	if id, ok := ctx.Value(traceKey{}).(string); ok {
		e.TraceID = id
	}
	return json.NewEncoder(os.Stdout).Encode(e)
}

func main() {
	ctx := context.WithValue(context.Background(), traceKey{}, "4bf92f3577b34da6a3ce929d0e0e4736")
	_ = writeEvent(ctx, "items_processed", 7)
}
```

不要把 context 当成任意参数袋。这里只放 request-scoped identity；业务参数仍显式传递。

## Profile：从请求回到调用栈 {#profiles}

连续剖析定期采集 CPU、allocation、wall-clock 或 lock 等 stack profile。它补上 trace span 内部的黑盒：

- 同一个 RPC span 变慢，是 JSON decode、GC、lock 还是 kernel path；
- 新 deployment 的 CPU 增量落在哪个 frame；
- allocation rate 上升由哪条调用链造成；
- on-CPU 正常时，off-CPU stack 在等什么。

profile 的维度必须受控。按 service/version/region 聚合通常有价值；把每个 request 都变成独立 profile 既昂贵又破坏统计。trace-profile correlation 应在采样预算内使用，并明确 profile sample 与某个 trace 的关联是统计还是精确。

截至 2026-07-28，OpenTelemetry Profiles signal 的规范稳定性仍为 Alpha；数据格式、SDK 和 Collector 支持都不能当成稳定的跨版本契约。原生 runtime profiler、Linux `perf` 与 eBPF 的机制见[采样、perf 与 eBPF](profiling.md)。

## Sampling：看见什么，也决定看不见什么 {#sampling}

### Head sampling

请求开始时决定是否保留。优点是成本可预测、整条调用链能遵循同一 sampled flag；缺点是当时还不知道请求最终是否慢或失败。

概率为 $q$ 的独立采样中，样本事件的无偏计数估计可用 Horvitz–Thompson 直觉：

$$
\hat{N} = \sum_{i\in S}\frac{1}{q_i}
$$

前提是 inclusion probability 已知且采样实现符合模型。parent-based、rate limit、collector loss 与 tail rules 会改变这个前提。

### Tail sampling

trace 完成或积累足够 span 后，根据 latency、error、attribute 决定。它能保留稀有失败，但需要暂存数据、处理迟到 span，并承担 collector 内存与一致性成本。

“保留全部错误、慢请求和 1% 正常请求”的数据集不能直接计算总体 error rate 或 latency distribution，除非记录并应用各类 inclusion probability。tail sampling 适合调查，不自动等于无偏统计。

### 一致性

同一 trace 的 sampling decision 应尽量一致传播。否则上游保留而下游丢弃会形成 broken trace；下游独立提高采样也可能产生 orphan span。跨组织传播时仍要执行本地成本和安全策略。

## Collector 与传输 {#collector}

常见数据路径：

```text
application SDK
  -> local/agent collector
  -> gateway collector
  -> storage/query backend
```

Collector 可做 batching、retry、memory limiting、filter、attribute transform、tail sampling 与多后端 export。每一步也会成为故障源：

- exporter queue 满；
- retry 放大下游故障；
- memory limiter 丢数据；
- transform 删除 identity；
- clock skew 与 timestamp 修正；
- collector 自己没有 telemetry；
- OTLP 接收成功但后端写入失败。

遥测管道要有自己的 loss、queue、retry、export latency 与 rejection 指标。应用不应因远端 telemetry backend 变慢而无限阻塞主请求；本地队列也必须有界。

## 从遥测到服务目标 {#slo}

先定义用户结果，再选择 telemetry。一个 availability SLI 可写成：

$$
\mathrm{SLI} =
\frac{\text{good events}}{\text{valid events}}
$$

关键在于 good/valid 的边界：

- client cancel 是否计入；
- health check、synthetic traffic 是否排除；
- 重试按 attempt 还是最终 operation；
- partial success 是否 good；
- dependency failure 由谁承担。

dashboard 应能沿同一语义下钻：

1. SLO/window 是否异常；
2. 哪个 operation、region、version 贡献；
3. 对应 trace 的 critical path；
4. 相关 log/error chain；
5. span 内 profile 或 host/container 饱和证据；
6. deployment/config/event 时间线。

告警以可行动的用户影响为主，资源信号用于诊断。CPU 高但 SLO 正常可能只是有效利用；SLO burn 高而 CPU 低可能是 dependency、queue、lock 或流量被拒绝。

## 成本、可靠性与隐私预算 {#budgets}

遥测成本可粗略拆为：

$$
\text{bytes/s} =
\text{events/s}\times
\text{bytes/event}\times
\text{retained fraction}
$$

实际还包括 index cardinality、replication、compression、query scan 与 egress。优化顺序通常是：

- 删除无用途字段与重复事件；
- 规范低基数 attributes；
- metric 聚合高频事件；
- 对 trace/profile 采样；
- 按调查价值设置 retention tier；
- 在靠近数据源处过滤敏感内容。

隐私与安全不是 export 后再补：

- 建立字段 allowlist 与 data classification；
- secret、token、认证 header 不进入 telemetry；
- 用户输入和 URL query 做明确 redaction；
- tenant boundary 与 query authorization 一致；
- 限制 baggage、log payload 与 stack/local variable capture；
- 定义 retention、删除与审计策略；
- 将 observability backend 视为生产数据系统。

## 一套可复验的落地顺序 {#workflow}

1. 写下服务边界、用户 operation 与 SLI；
2. 定义 resource identity 和 semantic convention；
3. 用 metric 覆盖 rate/error/duration/saturation；
4. 在 network、queue、database 边界建立 trace；
5. 用结构化 log 保存不可从 span/metric 重建的事件；
6. 接入 runtime/host profile；
7. 设计 head/tail sampling 与丢失预算；
8. 校验跨服务 context、clock、retry 与 async link；
9. 做故障注入，确认从告警能下钻到证据；
10. 监控 telemetry pipeline 自身并定期删去无用数据。

最终验收不是“每个页面都有图”，而是拿一个真实问题，从用户影响出发，能在有限时间内找到可复验的机制解释。

## 常见失败 {#failure-modes}

- metric label 使用 raw URL、request ID 或完整错误文本；
- trace 每个函数都建 span，却漏掉 queue wait；
- 把 sampling 后的 trace count 当总体 traffic；
- 用 span duration 之和替代 critical path；
- percentile 相加或在不同 bucket schema 间直接合并；
- log message 可读但字段语义随版本漂移；
- propagation 信任外部 baggage；
- telemetry exporter 无界 retry；
- collector 丢数据却没有自监控；
- trace 有 ID，log/profile/deployment 却无法关联；
- 只按平均值告警，忽略尾部与 burn rate；
- 为排障记录 credential 或完整用户 payload。

## 继续阅读

- CPU、off-CPU、PMU 与内核事件：见[采样、perf 与 eBPF](profiling.md)。
- 把遥测转成负载边界与排障决策：见[容量与系统化排障](capacity-troubleshooting.md)。
- 先保证测量对象可比：见[基准设计](benchmarking.md)。

## Reference

- [OpenTelemetry Specification 1.59.0](https://opentelemetry.io/docs/specs/otel/)
- [OpenTelemetry Protocol 1.11.0](https://opentelemetry.io/docs/specs/otlp/)
- [OpenTelemetry Semantic Conventions 1.43.0](https://opentelemetry.io/docs/specs/semconv/)
- [OpenTelemetry Trace API](https://opentelemetry.io/docs/specs/otel/trace/api/)
- [OpenTelemetry Metrics Data Model](https://opentelemetry.io/docs/reference/specification/metrics/data-model/)
- [OpenTelemetry Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)
- [OpenTelemetry Profiles specification and Alpha status](https://opentelemetry.io/docs/specs/otel/profiles/)
- [W3C Trace Context Recommendation](https://www.w3.org/TR/trace-context/)
- [W3C Baggage Recommendation](https://www.w3.org/TR/baggage/)
- [Google SRE Workbook: Implementing SLOs](https://sre.google/workbook/implementing-slos/)
