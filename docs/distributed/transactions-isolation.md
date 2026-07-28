# 事务与隔离

事务同时涉及两个维度：并发执行看起来像什么，以及参与节点能否原子提交。Serializability、snapshot isolation、two-phase commit 和 consensus 回答不同问题，不能互相替换。

<a id="histories"></a>
## History 与冲突图

history 记录事务的读、写、提交和中止。若存在一个串行顺序产生等价观察，则 history serializable。冲突可串行化通过 serialization graph 判断：节点是事务，冲突操作顺序形成边；图无环则可按拓扑序串行化。

严格可串行化（strict serializability）再要求串行顺序尊重真实时间：若事务 A 在 B 开始前已完成，A 必须排在 B 前。

<a id="isolation"></a>
## 隔离级别与异常

仅用“脏读/不可重复读/幻读”不足以描述所有实现。更精确地看依赖：

- `wr`：B 读取 A 写入的版本；
- `ww`：B 覆盖 A 的版本；
- `rw` anti-dependency：A 读到旧版本，B 后写新版本。

Snapshot Isolation 让事务读一个一致快照，并用 first-committer-wins 阻止并发写同一项，却允许 write skew：两个事务读相同约束、各写不同项，合并后破坏不变量。

Serializable Snapshot Isolation 跟踪危险的 `rw` 依赖结构，并中止可能形成环的事务。应用必须重试 serialization failure。

<a id="mvcc"></a>
## MVCC 可见性

记录版本携带创建/删除事务标识或 timestamp。先把 snapshot $S$ 定义为一个确定的可见性 cut，并令 $\operatorname{committedBefore}(x,S)$ 表示事务 $x$ 已成功提交，且提交点位于 $S$ 之前。忽略当前事务“读己之写”的局部特例时，版本 $v$ 的通用判断是：

$$
\operatorname{visible}(v,S)
=\operatorname{committedBefore}(\operatorname{creator}(v),S)
\land\left(
\operatorname{deleter}(v)=\varnothing
\lor\neg\operatorname{committedBefore}(\operatorname{deleter}(v),S)
\right)
$$

因此，创建事务未提交或在 cut 之后提交时版本不可见；删除事务在 cut 之前提交时版本不可见；删除事务仍活跃、已中止或在 cut 之后提交时，旧版本仍可见。当前事务自己的写入和删除通常另有规则。

这只是抽象模型，不是 PostgreSQL tuple header 的逐字段算法。PostgreSQL 用 `xmin`/`xmax`、事务状态与 snapshot 中的活动事务集合共同判断，不应把 `xmin`/`xmax` 直接当成全局 commit timestamp；其他系统可能使用 commit table 或 timestamp oracle。长事务保留旧 snapshot，会阻止 vacuum/compaction 清除版本。二级索引与主记录版本必须保持可验证关联。

<a id="2pc"></a>
## Two-Phase Commit

协调者让参与者原子决定 commit/abort：

1. **prepare**：参与者验证、锁定资源、把 prepared 状态 durable，投 yes/no；
2. 全 yes 则协调者 durable 记录 commit，否则 abort；
3. **decision**：通知参与者完成并释放资源。

参与者投 yes 后不能单方面 abort；若协调者失联，它可能阻塞等待决定。2PC 提供原子提交，不决定全局事务顺序，也不复制协调者状态。实践中常把 transaction record 存入共识复制服务以提高恢复能力，但两层语义仍需区分。

<a id="external-consistency"></a>
## 时间戳、锁与外部一致性

分布式 serializability 可通过 strict 2PL、确定性排序、timestamp ordering 或 MVCC + 验证实现。Spanner 以 Paxos 复制分片、2PC 跨分片，并利用 TrueTime 不确定区间和 commit wait 保证 external consistency。

“全局 timestamp”必须解释分配、单调性、故障恢复和时钟偏差。timestamp 唯一不等于事务一定可串行化。

<a id="application"></a>
## 业务契约与重试

- 事务中外发不可撤销副作用会破坏 abort；使用 outbox/inbox 等可恢复协议。
- 自动重试必须重新执行整个事务并保留幂等键，不能只重发最后一条 SQL。
- timeout 后结果未知，先查询 transaction/request ID 状态。
- 隔离级别是每个数据库/事务的具体语义，不能凭名称跨产品推断。
- saga 将长事务拆为局部提交和补偿，不等价 ACID rollback；补偿也可能失败。

## 测量与测试

报告 commit/abort/serialization-retry、lock wait、version age、2PC prepared duration 与 coordinator recovery。用并发 history 生成器验证不变量；故障注入覆盖 prepare 前后、decision 持久化前后、重复消息和参与者重启。

## 与相邻机制对齐

- [时间、因果与全序](time-order.md)解释 timestamp 的因果边界与物理时钟不确定性。
- [复制与共识](replication-consensus.md)区分日志顺序、共识决定和事务原子提交。
- [分片与再平衡](sharding.md)展示事务跨越多个复制组后的协调成本。
- [数据库存储引擎](../storage/database-storage.md)把 snapshot 可见性接回版本布局、WAL 与回收。

## Reference

- [Berenson et al.: A Critique of ANSI SQL Isolation Levels](https://www.microsoft.com/en-us/research/publication/a-critique-of-ansi-sql-isolation-levels/)
- [Adya: Weak Consistency — A Generalized Theory](https://publications.csail.mit.edu/lcs/pubs/pdf/MIT-LCS-TR-786.pdf)
- [Serializable Snapshot Isolation in PostgreSQL](https://drkp.net/papers/ssi-vldb12.pdf)
- [Gray and Lamport: Consensus on Transaction Commit](https://www.microsoft.com/en-us/research/publication/consensus-on-transaction-commit/)
- [Spanner: Google's Globally-Distributed Database](https://research.google/pubs/spanner-googles-globally-distributed-database-2/)
- [PostgreSQL Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
