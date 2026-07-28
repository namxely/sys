# 分片与再平衡

分片把 key space 分给多个独立复制组，以突破单组容量和吞吐上限。它没有消除一致性问题，而是把问题分成“键属于谁”“路由如何更新”“跨分片操作如何提交”。

<a id="strategies"></a>
## 范围、哈希与目录

| 策略 | 优点 | 代价 |
| --- | --- | --- |
| range | 范围扫描、局部性 | 单调键热点、split |
| hash | 分布较均匀 | 范围查询散射 |
| directory | 任意放置、可精细迁移 | 元数据服务与缓存一致性 |
| composite | 租户/地区前缀 + 子键哈希/范围 | 设计和演进复杂 |

均匀 key count 不等于均匀负载；应以 bytes、QPS、CPU、storage I/O、网络和增长率共同决定 split。

<a id="consistent-hashing"></a>
## Consistent Hashing

节点和 key 映射到环，key 归属顺时针第一个节点。增加节点理论上只迁移相邻范围，比例约 $1/N$。虚拟节点让每个物理节点持有多个小区间，改善均衡并表达异构权重。

但环并不自动提供：

- 热 key 拆分；
- 副本跨故障域放置；
- 一致路由视图；
- 迁移期间写顺序；
- 快速故障检测。

现代系统也常用固定数量逻辑分区/token，再把分区映射到节点，减少成员变化对元数据形状的影响。

<a id="routing"></a>
## 路由与 epoch

客户端、proxy 或任意节点可路由。路由表缓存必须带版本/epoch。收到 stale route 时，服务端应返回“新 owner/刷新元数据”，而不是静默转发形成无界链。

请求携带 `(shard_id, epoch)`：

```text
if request.epoch < local.epoch:
    return STALE_EPOCH + current metadata hint
if local is not owner:
    return NOT_OWNER
execute under current shard state
```

epoch 只在由共识/原子元数据更新赋予唯一顺序时有效；本机计数器无法避免 split brain。

<a id="migration"></a>
## 在线迁移

一种可恢复流程：

1. 元数据记录 source、target、range 和 migration epoch；
2. 复制一致 snapshot；
3. 捕获 snapshot 之后的增量日志；
4. target 追平并校验；
5. 在有序切换点改变 owner；
6. source 保留 forwarding/redirect 窗口；
7. 确认旧客户端过期后回收。

双写容易出现一边成功一边失败。更稳妥的是单一 authoritative log，加 snapshot + catch-up；切换点由 shard replication group 与 metadata service 协调。

<a id="hotspots"></a>
## 热点与跨分片操作

单个 hot key 无法靠一致性哈希分散。方案包括 key salting + read aggregation、缓存、按子对象拆分、请求合并或业务限流；都改变读写语义。

跨分片事务支付多个复制组、2PC 和最慢参与者成本。数据建模应让强一致写尽量局部，但不能以反范式复制掩盖一致性需求。二级索引若跨分片，应定义同步事务、异步索引或查询验证。

## 测量与失败

- 画每 shard 的 bytes/QPS/P99/compaction debt，而非只看节点平均。
- 测迁移对 foreground latency、网络和磁盘的影响，提供限速与暂停。
- 注入 source/target/metadata leader 在各阶段崩溃。
- 验证重复迁移命令幂等、旧 epoch 写被拒绝、回滚不会双 owner。
- 审计 replica placement 是否跨 rack/zone，逻辑副本数不等于独立故障域数。

## 分片不是孤立层

- [复制与共识](replication-consensus.md)解释 shard epoch、owner 与配置变更怎样获得唯一顺序。
- [事务与隔离](transactions-isolation.md)展开跨分片 2PC、隔离与重试语义。
- [分布式存储](distributed-storage.md)比较 range、consistent hashing 与 tablet/chunk 的系统化取舍。
- [数据库存储引擎](../storage/database-storage.md)连接单分片内部的 B+ tree、LSM、WAL 与 compaction。

## Reference

- [Consistent Hashing and Random Trees](https://doi.org/10.1145/258533.258660)
- [Dynamo: Amazon's Highly Available Key-value Store](https://www.amazon.science/publications/dynamo-amazons-highly-available-key-value-store)
- [Bigtable: A Distributed Storage System for Structured Data](https://research.google/pubs/bigtable-a-distributed-storage-system-for-structured-data/)
- [Spanner: Google's Globally-Distributed Database](https://research.google/pubs/spanner-googles-globally-distributed-database-2/)
- [F1: A Distributed SQL Database That Scales](https://research.google/pubs/f1-a-distributed-sql-database-that-scales/)
