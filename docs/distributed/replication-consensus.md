# 复制与共识

复制可以提高读容量和容错，但多个副本会产生“更新以何种顺序生效”的问题。共识解决的是：即使节点故障和消息延迟，正确节点也不对同一位置决定不同值；状态机复制再把一系列共识决定组织成一致日志。

<a id="quorum"></a>
## Quorum 的交集

$N$ 个副本，写 quorum $W$、读 quorum $R$。若：

$$
W+R>N
$$

读写集合必相交；若 $2W>N$，两个写集合相交。但交集本身不自动产生线性一致性：还需版本选择、并发写处理、失败恢复与正确的读协议。

多数派系统通常在 $2f+1$ 节点中容忍 $f$ 个 crash failure。它不容忍任意 Byzantine 行为，也不能在少数派分区继续安全提交。

<a id="state-machine"></a>
## 状态机复制

所有副本从相同初始状态，按相同顺序执行确定命令：

$$
s_{i+1}=\delta(s_i,c_i)
$$

即可得到相同状态。非确定输入（时间、随机、外部 I/O）必须由 leader 决定并写入日志，或在状态机外受控处理。

客户端重试需要 `(client_id, sequence)` 去重，并把结果随状态持久化。否则日志只执行一次仍不能阻止客户端把同一业务命令提交两次。

<figure class="sys-figure" id="replication-timeline">
  <a class="sys-figure__media" href="../../assets/figures/replication-timeline.svg">
    <img src="../../assets/figures/replication-timeline.svg" alt="客户端请求进入领导者日志，复制到两个跟随者并在多数派确认后提交，随后再返回与继续复制" width="1300" height="650" loading="lazy">
  </a>
  <figcaption>“已经写入领导者日志”“已经被多数副本持久化”“已经提交”“已经应用并被客户端观察”是四个不同边界。示意图依据 <a href="https://raft.github.io/raft.pdf">Raft 论文</a>及其 <a href="https://pdos.csail.mit.edu/6.824/papers/raft-extended.pdf">扩展版本</a>重新绘制。</figcaption>
</figure>

<a id="paxos"></a>
## Paxos 的安全核心

Basic Paxos 的 proposer 用递增 proposal number：

1. **Prepare(n)**：acceptor 若未承诺更大编号，返回已接受的最高 proposal；
2. proposer 收到多数 promise 后，选择响应中最高编号已接受值；若没有则可选新值；
3. **Accept(n,v)**：acceptor 若未承诺更大编号则接受；
4. 一个值被多数接受即 chosen。

选择最高已接受值保证新多数与旧多数交集携带既有决定。Multi-Paxos 稳定 leader 后可省去每个 slot 的完整 prepare，但 leader 切换和日志补洞仍需实现。

<a id="raft"></a>
## Raft：term、日志与 leader completeness

Raft 将状态分为 follower/candidate/leader。随机 election timeout 降低平票；term 单调递增。leader 只提交：

- 当前 term 的 entry；
- 已复制到多数；

旧 term entry 可随当前 term entry 的提交间接提交。投票时比较 `(lastLogTerm,lastLogIndex)`，保证拥有所有已提交 entry 的候选者才能获多数，从而建立 Leader Completeness。

commit index 只表示可应用上界；状态机 apply 必须按日志顺序。响应客户端前，应明确 entry 已 committed 且应用/结果状态满足接口契约。

<a id="membership"></a>
## 成员变更与快照

从配置 $C_{\text{old}}$ 直接切到 $C_{\text{new}}$ 可能出现不相交多数。joint consensus 或逐一成员变更让过渡期 quorum 有安全交集。成员变更必须进入复制日志，不能只改本地配置。

快照压缩已应用前缀，但需包含：

- last included index/term；
- 完整状态机与客户端去重状态；
- 配置状态；
- 校验和与原子安装协议。

<a id="limits"></a>
## FLP、活性与工程边界

异步系统中即使一个 crash failure，确定性共识也无法同时保证总是终止。实际协议依赖部分同步：超时最终能区分出稳定 leader，但超时只是活性工具，不是故障证明。

常见实现错误：

- term/ballot 未先持久化就发送承诺；
- apply 线程和 snapshot 截断竞态；
- leader lease 未计入时钟偏差和暂停；
- read 直接读 leader 本地状态却未确认其仍为 leader；
- 配置变更与普通日志索引处理不一致；
- 持久化失败后节点继续投票。

## 验证与测量

使用确定性模拟控制消息、时钟、崩溃与重启；用 TLA+/模型检查安全不变量；持久化层做 torn write 和 fsync failure。性能报告分 leader CPU、fsync、replication RTT、batch、apply lag、snapshot 和 read path，不能只给“每秒提案数”。

## 共识之外

- [时间、因果与全序](time-order.md)说明 term、lease 与日志顺序依赖哪些时间假设。
- [事务与隔离](transactions-isolation.md)区分 consensus、2PC、serializability 与 external consistency。
- [分布式存储](distributed-storage.md)展示复制日志怎样进入 GFS、Bigtable、Dynamo 等不同数据模型。
- [可靠性与可观测性](reliability-observability.md)把 leader 变更、重试风暴与恢复演练接到运行时证据。

## Reference

- [Lamport: Paxos Made Simple](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)
- [Ongaro and Ousterhout: In Search of an Understandable Consensus Algorithm](https://raft.github.io/raft.pdf)
- [Ongaro and Ousterhout: In Search of an Understandable Consensus Algorithm — Extended Version](https://pdos.csail.mit.edu/6.824/papers/raft-extended.pdf)
- [Viewstamped Replication Revisited](https://dspace.mit.edu/server/api/core/bitstreams/9f8c52b3-ea46-4fde-9dc9-354ed6d9c7d9/content)
- [FLP: Impossibility of Distributed Consensus with One Faulty Process](https://groups.csail.mit.edu/tds/papers/Lynch/jacm85.pdf)
- [Raft TLA+ specification](https://github.com/ongardie/raft.tla)
- [etcd Raft implementation](https://github.com/etcd-io/raft)
