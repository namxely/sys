# 调度

调度器在 runnable 实体之间分配 CPU 时间，同时面对互相冲突的目标：吞吐、响应、公平、deadline、能耗、cache/NUMA 局部性和优先级。不存在脱离工作负载的“最佳调度算法”。

## 三类时间

对一个任务：

$$
T_\mathrm{response}=T_\mathrm{run}+T_\mathrm{runqueue}+T_\mathrm{sleep}
$$

- `run`：真正占用 CPU；
- `runqueue`：已可运行但等待 CPU；
- `sleep`：等待 I/O、锁、计时器或其他事件。

CPU profile 只能解释 `run`。延迟高而 CPU 栈很少时，应该先看 runqueue 和等待事件。

## 抢占与时间片

非抢占调度让任务主动让出 CPU，长任务会阻塞交互任务。抢占调度由定时器、唤醒和优先级事件触发，能缩短响应，却增加切换、cache 干扰和调度开销。

时间片小：

- 响应快、切换多；
- cache/TLB 复用差；
- 批处理吞吐可能下降。

时间片大则相反。现代调度器往往不只使用固定 round-robin 时间片，而是结合虚拟时间、权重和 deadline。

## 公平调度：从理想 CPU 到 EEVDF

Linux CFS 把理想多任务 CPU 近似为每个同权任务同时获得 $1/n$ 处理能力，用加权虚拟运行时间记录实际服务：

$$
\Delta v_i=\Delta t_i\frac{w_0}{w_i}
$$

较小 `vruntime` 表示获得的规范化服务较少。经典 CFS 用红黑树选取最小 `vruntime` 实体。

Linux 从 6.6 开始逐步转向 EEVDF。其核心是：

- lag 描述任务相对理想公平份额欠了多少；
- 只有满足 eligibility 的任务可被选择；
- 在 eligible 任务中选择最早虚拟 deadline；
- 较短 slice 可获得更早 deadline，改善延迟敏感任务响应。

这是 Linux 具体演化，不是 POSIX 对 `SCHED_OTHER` 的算法保证。

## 实时调度

### 固定优先级

- `SCHED_FIFO`：最高优先级 runnable 任务运行到阻塞、让出或被更高优先级抢占。
- `SCHED_RR`：同优先级任务增加 round-robin 时间片。

实时优先级任务不受普通公平调度约束，错误的忙循环可能饿死系统服务。生产部署需配合权限、预算和 watchdog。

### deadline

周期任务可用 runtime $C$、period $T$、relative deadline $D$ 描述。Linux `SCHED_DEADLINE` 使用 EDF 与 CBS 思路提供带宽预留。单 CPU、隐式 deadline 的理想独立任务集常用必要/充分边界：

$$
\sum_i \frac{C_i}{T_i}\le 1
$$

真实系统还要考虑阻塞、IRQ、迁移、cache、不可抢占区和 admission control。

## 多核调度

每 CPU runqueue 提高扩展性，却需负载均衡。迁移任务可能改善公平与利用率，也会损失：

- 私有 cache 热度；
- TLB 和分支历史；
- NUMA 内存局部性；
- 同步伙伴的拓扑接近性。

调度器因而在“让空闲 CPU 立即工作”和“等待原 CPU 保留局部性”之间权衡。wake affinity、NUMA balancing、capacity awareness 与 energy-aware scheduling 都属于具体实现策略。

## SMT 与异构核心

两个 SMT sibling 共享核心资源，capacity 不等于两个完整核心之和。大小核系统中，CPU capacity、能效与支持的 ISA/性能特征也可能不同。线程亲和性不能只写“绑到 CPU 2”，还应理解 CPU 2 的核心类型、siblings 与 NUMA 节点。

## 优先级反转

高优先级 H 等低优先级 L 持有的锁，中优先级 M 又持续抢占 L，H 会被间接阻塞。priority inheritance 可临时提升 L，使其尽快释放锁；priority ceiling 是另一种协议。

这不是仅靠调度器解决的问题。锁设计、临界区长度、IRQ 和资源依赖共同决定最坏阻塞。

## 设置亲和性的实验

以下 Linux C11 代码把当前线程绑定到指定逻辑 CPU：

```c
#define _GNU_SOURCE
#include <errno.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    int cpu = atoi(argv[1]);
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    if (sched_setaffinity(0, sizeof set, &set) < 0) {
        perror("sched_setaffinity");
        return 1;
    }
    printf("running_on=%d\n", sched_getcpu());
}
```

亲和性是允许 CPU 集合，不保证进程不会被抢占；容器 cpuset 还可能让指定 CPU 非法。固定 CPU 也可能把任务绑到繁忙 sibling，必须检查拓扑和邻居负载。

## 观测调度

```bash
perf sched record -- ./program
perf sched timehist
cat /proc/$PID/sched
cat /proc/pressure/cpu
```

关注：

- wakeup 到真正运行的延迟；
- voluntary / involuntary context switch；
- migration 与运行 CPU；
- runqueue 长度和 CPU PSI；
- 哪个线程唤醒、哪个线程阻塞；
- cgroup CPU quota 是否造成 throttling。

采样 CPU utilization 接近 100% 但 PSI 很低，可能只有单个任务充分利用分配 CPU；PSI 高则表示任务因 CPU 竞争被推迟。二者语义不同。

## 常见失败模式

- 看到高延迟只做 CPU profile，忽略 runqueue/sleep；
- 线程数等于逻辑 CPU 数，却忽略 SMT、IRQ 和运行时线程；
- 全部绑核后破坏内核负载均衡和 NUMA；
- 用高实时优先级“解决抖动”，导致系统饿死；
- 忽略 cgroup quota 的周期性 throttling；
- 把 nice 值当固定 CPU 百分比；
- 把 CFS 旧文档细节当当前 EEVDF 的完整行为；
- 仅看平均调度延迟，不看 deadline miss 和尾部。

## 跨层连接

- 被调度实体来自[进程与线程](process-thread.md)；
- 迁移的 cache/NUMA 成本见 [CPU](../architecture/cpu.md)；
- lock convoy 与优先级反转见[锁与条件变量](../concurrency/locks-condition-variables.md)；
- cgroup CPU 控制见[隔离与容器](isolation-containers.md)；
- 协程调度器最终仍运行在线程和内核调度器上，见[协程](../concurrency/coroutines.md)。

## Reference

- [Linux Kernel Documentation: EEVDF Scheduler](https://www.kernel.org/doc/html/latest/scheduler/sched-eevdf.html)
- [Linux Kernel Documentation: CFS Scheduler](https://www.kernel.org/doc/html/latest/scheduler/sched-design-CFS.html)
- [Linux Kernel Documentation: Deadline Task Scheduling](https://www.kernel.org/doc/html/latest/scheduler/sched-deadline.html)
- [Linux Kernel Documentation: Capacity Aware Scheduling](https://www.kernel.org/doc/html/latest/scheduler/sched-capacity.html)
- [Stoica and Abdel-Wahab, Earliest Eligible Virtual Deadline First, TR-95-22](https://people.eecs.berkeley.edu/~istoica/papers/eevdf-tr-95.pdf)
- [Liu and Layland, Scheduling Algorithms for Multiprogramming in a Hard-Real-Time Environment](https://doi.org/10.1145/321738.321743)
- [Linux sched(7)](https://www.man7.org/linux/man-pages/man7/sched.7.html)
- [Linux PSI](https://www.kernel.org/doc/html/latest/accounting/psi.html)
