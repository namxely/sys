# MPI 与集合通信

MPI 为分布式内存进程提供消息传递。每个 rank 有独立地址空间；数据共享必须通过通信显式发生。这使通信成本可见，也让程序能跨节点扩展。

<a id="point-to-point"></a>
## 点对点语义

消息匹配由 communicator、source、tag 构成。`MPI_Send` 返回语义不等于对端应用已接收；实现可走 eager buffer 或 rendezvous。阻塞互发大消息可能死锁：

```text
rank 0: Send(to 1); Recv(from 1)
rank 1: Send(to 0); Recv(from 0)
```

使用 `MPI_Sendrecv`、非阻塞 `MPI_Isend/Irecv` 并及时 `MPI_Wait*`，或定义严格方向。非阻塞 buffer 在请求完成前不能修改/释放。

```c
MPI_Request req[2];
MPI_Irecv(in, n, MPI_DOUBLE, peer, 7, comm, &req[0]);
MPI_Isend(out, n, MPI_DOUBLE, peer, 7, comm, &req[1]);
int rc = MPI_Waitall(2, req, MPI_STATUSES_IGNORE);
if (rc != MPI_SUCCESS) MPI_Abort(comm, rc);
```

<a id="cost-model"></a>
## $\alpha$-$\beta$ 模型

传输 $n$ 字节：

$$
T(n)=\alpha+\beta n
$$

$\alpha$ 是消息启动延迟，$\beta$ 是每字节时间。许多小消息受 $\alpha$ 支配，应 batch；大消息受带宽、分片与拓扑支配。更完整模型还要加入 contention、软件 progression 与不同层级带宽。

<a id="collectives"></a>
## Collective 的算法不是固定的

| 操作 | 小消息常用 | 大消息常用 | 关键属性 |
| --- | --- | --- | --- |
| broadcast | binomial tree | pipeline/tree | $O(\log P)$ 步 |
| reduce | tree | reduce-scatter + gather | 运算可结合 |
| allreduce | recursive doubling | reduce-scatter + allgather/ring | 延迟/带宽权衡 |
| alltoall | pairwise | 分层/受限并发 | 容易拥塞 |

ring allreduce 将数据分成 $P$ 块，执行 reduce-scatter 与 allgather，各 $P-1$ 步。大消息近似每 rank 传输：

$$
2\frac{P-1}{P}n
$$

但延迟项为 $2(P-1)\alpha$，小消息未必合适。库会依据消息大小、拓扑和实现选择算法；手工强制需以测量为依据。

<a id="progress"></a>
## Progress、线程与并发

非阻塞调用允许重叠，不保证后台自动推进。实现可能需要 rank 进入 MPI、开启 progress thread 或硬件 offload。`MPI_Init_thread` 返回实际 thread support；若低于请求级别，程序必须降级或退出。

communicator 隔离消息上下文，重复使用 tag 不会跨 communicator 匹配。集体操作要求 communicator 内 rank 以兼容顺序参与；一个 rank 走错分支会让全体挂起。

<a id="correctness"></a>
## 正确性与故障

- count/datatype 不匹配会截断、越界或产生错误结果。
- 自定义 reduction 必须声明是否 commutative，且运算应 associative；浮点只近似满足。
- 一个 rank 崩溃时，传统 MPI job 常整体失败；容错语义需要实现/扩展支持与应用恢复设计。
- collective timeout 不能简单判定网络坏；straggler、GPU kernel、文件 I/O 或前序 rank 错误都可能阻塞。

## 测量

分别测 latency、unidirectional/bidirectional bandwidth、collective 随消息大小和 rank 数的曲线。先做每节点内、跨节点、跨机架分层基线。记录 rank mapping、进程/线程数、NIC rail、MPI 版本、collective tuning 和是否 GPU-aware。

## 把 collective 放回机器

- [拓扑与通信优化](topology-communication.md)解释 rank、NUMA、GPU 与 NIC 的映射成本。
- [Work、Span 与扩展定律](performance-models.md)提供扩展效率与通信开销的基线。
- [数据中心网络与 RDMA](../network/datacenter-rdma.md)展开 collective 下方的 Clos、ECMP、RDMA 与拥塞。
- [复制与共识](../distributed/replication-consensus.md)对比“所有 rank 参与一次 collective”和“故障下多数节点决定一个值”的不同语义。

## Reference

- [MPI 5.0 Standard](https://www.mpi-forum.org/docs/)
- [Open MPI Documentation](https://docs.open-mpi.org/)
- [MPICH Documentation](https://www.mpich.org/documentation/)
- [Rabenseifner: Optimization of Collective Reduction Operations](https://fs.hlrs.de/projects/par/mpi/myreduce.html)
