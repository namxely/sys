# 分布式存储

分布式存储把数据切片、复制到多个故障域，并在节点与网络故障下继续提供定义明确的读写语义。经典系统的价值不在“架构图”，而在它们如何针对 workload 选择 chunk、日志、索引、共识和一致性。

<a id="gfs"></a>
## GFS：大块、追加与故障常态

GFS 面向大文件、流式读和追加。master 管理 namespace、chunk 位置和 lease，chunkserver 存大 chunk。数据流与控制流分离：客户端向 master 查询位置，随后直接访问 chunkserver。

primary lease 为 chunk mutation 排序；secondary 以相同顺序应用。record append 提供“至少一次原子追加”的特定语义，可能留下 padding 或重复记录，应用需以 record ID 去重。

大 chunk 降低 master 元数据和交互频率，却不适合海量微小随机文件。设计来自 workload，不是通用最佳块大小。

<a id="bigtable"></a>
## Bigtable：tablet 与 LSM 家族

Bigtable 将 `(row, column, timestamp)` 映射到值，row range 构成 tablet。写进入 commit log 和 memtable，再形成 SSTable；读合并内存与多个不可变文件。Chubby 用于 master election、元数据和 server 活性协作。

row key 字典序决定局部性，也会制造热点。tablet split 提高扩展性，但单调前缀写仍可能集中到最后一个 tablet。

<a id="dynamo"></a>
## Dynamo：可用性与冲突显式化

Dynamo 面向 always-on key-value workload，使用 consistent hashing、N/R/W、sloppy quorum、hinted handoff、Merkle tree 和 vector clock。网络分区时接受多个并发版本，再由应用或规则 reconcile。

$R+W>N$ 的传统交集推理在 sloppy quorum 和故障替代节点下需谨慎；最终收敛还依赖 read repair、anti-entropy 与冲突合并。last-write-wins 以时间戳丢弃并发更新，不是无损合并。

<a id="design-space"></a>
## 一个统一设计空间

| 维度 | 选择示例 | 后果 |
| --- | --- | --- |
| 数据单元 | chunk、object、row range、key | 元数据、迁移粒度 |
| 分区 | range、hash、directory | 扫描与热点 |
| 复制 | leader、quorum、erasure code | 延迟、容量、修复 |
| 一致性 | linearizable、snapshot、eventual | 可编程性与可用性 |
| 后台维护 | compaction、scrub、re-replication | 前台干扰 |
| 元数据 | 单 master、分片、共识组 | 简洁性与扩展 |

Erasure coding 用 $k$ 个数据块和 $m$ 个校验块容忍部分丢失，空间效率高于 $m+1$ 副本，但小写、编码和修复网络成本更高。热数据可能先复制，冷数据再转 EC。

<a id="repair"></a>
## Repair、Scrub 与数据丢失窗口

节点故障后，系统检测不足副本并重建。若数据量 $D$、可用修复带宽 $B_r$：

$$
T_{\text{repair}}\ge D/B_r
$$

修复越快，暴露于第二故障的窗口越短，但会与用户 I/O 争抢网络和磁盘。placement 必须考虑 rack/zone 共因故障；三副本在同一机架并非三故障域。

scrub 读取并校验静态数据，发现 silent corruption；只有 checksum + 独立冗余 + 明确权威版本才能自动修复。

<a id="client-contract"></a>
## 客户端契约

- write ACK 明确是一个内存副本、quorum WAL 还是多个 durable media。
- read consistency 是 stale、read-your-writes、linearizable 还是 snapshot。
- timeout 后提供 request/transaction ID 查询与幂等重试。
- list/scan 是否包含并发更新、分页 token 是否稳定。
- delete 与 tombstone 保留多久，旧副本复活如何避免。

## 测量与演练

除 steady-state 吞吐外，测 node/rack loss、recovery、rebalancing、compaction、scrub 和容量接近满载。报告 foreground P99、repair bandwidth、under-replication duration、checksum error、metadata availability 和恢复点。最危险的系统常在“平时很快、故障恢复未经压测”。

## 从案例回到机制

- [分片与再平衡](sharding.md)展开 range、consistent hashing、epoch 与在线迁移。
- [复制与共识](replication-consensus.md)解释 leader、quorum 与复制日志的安全边界。
- [缓存、日志与崩溃一致性](../storage/caching-logging-consistency.md)区分本地 WAL durable 与跨副本 durable。
- [数据中心网络与 RDMA](../network/datacenter-rdma.md)说明修复、复制与前台 I/O 共享的实际 fabric。

## Reference

- [The Google File System](https://research.google/pubs/the-google-file-system/)
- [Bigtable: A Distributed Storage System for Structured Data](https://research.google/pubs/bigtable-a-distributed-storage-system-for-structured-data/)
- [Dynamo: Amazon's Highly Available Key-value Store](https://www.amazon.science/publications/dynamo-amazons-highly-available-key-value-store)
- [Ceph: A Scalable, High-Performance Distributed File System](https://www.usenix.org/conference/osdi-06/ceph-scalable-high-performance-distributed-file-system)
- [Spanner: Google's Globally-Distributed Database](https://research.google/pubs/spanner-googles-globally-distributed-database-2/)
- [Windows Azure Storage: A Highly Available Cloud Storage Service](https://sigops.org/s/conferences/sosp/2011/current/2011-Cascais/printable/11-calder.pdf)
