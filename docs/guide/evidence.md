# 证据与实验

系统解释只有在规格、实现与测量能够互相对齐时才可靠。三者缺一，结论都可能越过自己的适用边界。

## 四类证据 {#evidence-classes}

### 规格与协议

语言标准、ABI、ISA、RFC、系统调用契约和持久化保证描述允许观察到的行为。它们适合回答“程序可以依赖什么”，但通常不会规定所有实现细节和性能。

### 实现与源码

内核、编译器、运行时和库源码回答“这个版本怎样做到”。源码证据必须绑定版本或提交；内部函数名、数据结构和启发式策略可能变化，不能自动提升为跨版本契约。

### 论文与设计文档

原始论文适合解释问题、模型、算法、实验条件与历史因果。论文结果只在披露的硬件、数据、负载和比较口径内成立；不能把一张排名图改写为普遍定律。

### 测量

测量回答“这台机器、这个版本、这个负载发生了什么”。它最接近目标现象，也最容易受环境、采样、预热、频率、共租户和工具语义影响。

## 最小实验契约 {#experiment-contract}

一个可以复查的实验至少记录：

```yaml
system:
  cpu: model, cores, topology
  memory: capacity, channels, NUMA
  os: kernel and configuration
toolchain:
  compiler: version and flags
  runtime: version and environment
workload:
  input: distribution and size
  concurrency: clients and arrival process
measurement:
  warmup: duration or iterations
  samples: count and aggregation
  clocks: source and resolution
```

这份记录不是为了堆元数据，而是为了判断两个结果是否可比较。

## 先写假设，再选指标 {#hypothesis-first}

假设“尾延迟由锁竞争引起”，应推出可观测预测：

- 临界区等待时间和等待线程数上升；
- 锁持有者被抢占时尾部进一步放大；
- 分片或缩短临界区后延迟下降；
- CPU 总利用率可能不高，但运行队列和上下文切换形态改变。

如果只看到 p99 上升便直接寻找“最像”的火焰图，会形成确认偏差。指标必须能区分竞争假设与替代解释，例如下游超时、缺页、GC 或网络重传。

## 分布而不是单值 {#distributions}

延迟、对象大小、队列长度和请求成本通常是偏态或多峰分布。至少报告：

- 样本数与时间窗口；
- p50、p90、p99 等分位数；
- 最大值是否来自测量错误或真实长尾；
- 吞吐与并发度；
- 冷启动和稳态是否分开。

对独立同分布样本，均值标准误近似为 $s/\sqrt{n}$；系统测量往往存在自相关和批次效应，简单扩大请求数并不能消除部署、机器和时间窗口的偏差。更稳妥的方法是以机器、进程或时间块为重采样单位。

## 观察会改变系统 {#observer-effect}

- 逐事件 tracing 可能增加调度和 I/O；
- 采样 profiler 可能遗漏短事件或把时间归到安全点；
- 硬件计数器可能复用、溢出或受推测执行影响；
- debug 构建会改变内联、布局、时序和分配行为；
- 抓包位置决定能否看到 offload 前后的真实分段。

因此要做空载开销对照，并用至少两种不同机制的证据交叉验证关键结论。

## 版本与时效 {#versioning}

页面中的事实按稳定性分为：

| 类型 | 例子 | 写法 |
| --- | --- | --- |
| 稳定契约 | TCP 字节流、语言内存模型 | 直接引用规范版本 |
| 可变实现 | 调度启发式、GC 阈值 | 写明版本与源码位置 |
| 平台能力 | 指令扩展、网卡 offload | 写明硬件型号与固件 |
| 测量结果 | 延迟、带宽、扩展曲线 | 写明环境和负载 |
| 推断 | 可能的瓶颈或因果链 | 明确标为推断并给证伪方法 |

## 图表与代码证据 {#figures-code}

图表必须回答具体问题：状态如何迁移、数据怎样流动、性能在什么边界改变、哪个消融支持因果。图注应包含数据集或负载、指标方向、版本、可比性和来源。无法确认授权或上下文的图，不应仅因“直观”而复用。

参考代码应保持关键语义：

- 并发代码保留同步、内存序和生命周期；
- 网络代码保留部分读写、超时、取消和背压；
- 存储代码保留错误路径、刷新与提交顺序；
- 性能代码保留预热、重复、对照和结果校验。

如果为教学省略了生产机制，要在代码附近说明省略会造成的边界。

## 发布前核对 {#publication-check}

1. 外部事实是否有就近来源？
2. `Reference` 是否包含真正使用的材料，并去重？
3. 规格、实现、论文结果和本地测量是否被混写？
4. 快速变化事实是否有版本和核验日期？
5. 代码是否能解析、编译或明确说明环境？
6. 公式、表格、图和链接是否在生成页面中可用？
7. 是否保留了反例、失败模式和未知信息？

## Reference

- [The Linux Kernel Documentation](https://docs.kernel.org/)
- [Linux perf Documentation](https://perf.wiki.kernel.org/)
- [RFC 9000: QUIC](https://www.rfc-editor.org/rfc/rfc9000.html)
- [The Tail at Scale](https://research.google/pubs/the-tail-at-scale/)
- [Benchmarking Crimes](https://www.cse.unsw.edu.au/~gernot/benchmarking-crimes.html)
