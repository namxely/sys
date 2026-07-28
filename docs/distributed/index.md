# 分布式系统

分布式系统由多个并发节点组成，消息可能延迟、重复、乱序或丢失，节点会暂停、重启，网络还可能分区。没有一个观察者能瞬间知道全局状态。因此核心工作不是“调用 RPC”，而是在明确故障模型下建立可证明的顺序、一致性、持久性与可用性边界。

## 学习路径

1. [时间、因果与全序](time-order.md)：从 happened-before、逻辑时钟走到物理时钟不确定性。
2. [复制与共识](replication-consensus.md)：理解 quorum、状态机复制、Paxos/Raft 与成员变更。
3. [事务与隔离](transactions-isolation.md)：区分原子提交、并发隔离和外部一致性。
4. [分片与再平衡](sharding.md)：比较范围、哈希、一致性哈希与迁移协议。
5. [分布式存储](distributed-storage.md)：串联 GFS、Bigtable、Dynamo 等系统的设计取舍。
6. [可靠性与可观测性](reliability-observability.md)：从故障预算、超时重试走到 trace 与灾难演练。

## 建模先于实现

每个协议都应先回答：

| 维度 | 典型选择 |
| --- | --- |
| 节点故障 | crash-stop、crash-recovery、Byzantine |
| 网络 | 同步、部分同步、异步 |
| 存储 | 易失、稳定存储、可能损坏 |
| 身份 | 固定成员、动态成员 |
| 安全性质 | 永远不能发生什么 |
| 活性性质 | 在哪些条件下最终会发生什么 |

“最终一致”“恰好一次”“高可用”若没有对象、范围和条件，都不是完整技术承诺。

## 一条贯穿全站的原则

网络超时只代表观察不到结果：

```text
request may be lost
response may be lost
server may commit and crash before replying
client may time out while server is still running
```

因此重试、幂等键、去重状态、事务提交和可观测性必须共同设计。传输层可靠不等于业务操作只执行一次。

## Reference

- [Lamport: Time, Clocks, and the Ordering of Events](https://lamport.azurewebsites.net/pubs/time-clocks.pdf)
- [Ongaro and Ousterhout: In Search of an Understandable Consensus Algorithm](https://raft.github.io/raft.pdf)
- [Google Research: Spanner](https://research.google/pubs/spanner-googles-globally-distributed-database-2/)
- [MIT 6.5840 Distributed Systems](https://pdos.csail.mit.edu/6.824/)
