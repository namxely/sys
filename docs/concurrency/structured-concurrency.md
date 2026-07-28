# 结构化并发

结构化并发把并发任务限制在词法或动态作用域中：父任务离开作用域前，子任务必须完成、失败或被取消。任务因而形成树，而不是一组失去归属的后台句柄。

## 非结构化任务的问题

```text
handle_request()
  spawn refresh_cache()
  spawn write_audit()
  return
```

返回后两个任务：

- 还引用 request 的内存吗？
- 失败由谁观察？
- 客户端取消时继续吗？
- 服务关闭时谁等待它们？
- deadline 到期后是否仍写外部系统？

若答案散落在全局 registry、回调和日志中，生命周期已经脱离控制流结构。

## 任务树

```text
request
├── authenticate
├── fetch-profile
└── assemble
    ├── fetch-A
    └── fetch-B
```

基本约束：

1. parent 拥有 child 的生命周期；
2. scope 结束前 join 所有 child；
3. child 失败向 parent 传播；
4. parent 取消向后代传播；
5. 资源按作用域逆序释放；
6. detached task 必须成为显式、较长生命周期服务的孩子。

这把并发的 goto 变回可局部推理的块结构。

## fail-fast 不是唯一策略

子任务失败后常见语义：

- **fail-fast**：取消 siblings，聚合错误后退出；
- **collect-all**：等待全部，返回每项成功/失败；
- **quorum**：达到足够成功即取消剩余；
- **supervisor**：child 失败不自动取消 siblings；
- **restart**：由上层监督树按策略重启。

API 必须说清策略。将所有场景硬套 fail-fast，会让批量任务丢失有价值结果；完全不传播失败则制造幽灵任务。

## deadline、timeout 与取消

deadline 是绝对时刻，timeout 是从现在起的时长。跨服务传播 deadline 能避免每层重置完整 timeout：

$$
D_\mathrm{effective}=\min(D_\mathrm{parent},D_\mathrm{local})
$$

取消通常是协作式信号。每个阻塞点/循环需：

- 检查取消；
- 取消或等待在途 I/O；
- 保证资源释放；
- 定义不可撤销副作用；
- 把“操作完成”和“取消到达”竞态归并到单一结果。

超时返回不是底层工作已经停止的证明。

## Python 3.11+ TaskGroup

下面的标准库示例展示父任务 timeout、子任务作用域与失败传播。任一 child 抛出普通异常时，`TaskGroup` 会取消其余 child，退出时抛出异常组。

```python
import asyncio
async def step(name: str, delay: float, fail: bool = False) -> str:
    try:
        await asyncio.sleep(delay)
        if fail:
            raise RuntimeError(f"{name} failed")
        return name
    finally:
        print(f"{name}: cleanup")
async def request() -> list[str]:
    async with asyncio.timeout(2.0):
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(step("profile", 0.2)),
                group.create_task(step("inventory", 0.4)),
                group.create_task(step("policy", 0.3)),
            ]
        return [task.result() for task in tasks]
if __name__ == "__main__":
    print(asyncio.run(request()))
```

若要观察多个异常，可用 `except*` 处理异常组。不要在 child 中吞掉 `CancelledError` 而不继续传播，否则结构化取消可能失效。具体规则以当前 Python 文档为准。

## nursery/scope 的实现不变量

一个抽象 task scope 需要维护：

```text
state: OPEN -> CANCELLING -> JOINING -> CLOSED
children: count / registry
first or aggregate error
cancellation token/source
deadline timer
parent continuation
```

`spawn` 只在 OPEN 接受；child 完成原子减少计数；首个失败按策略触发 CANCELLING；最后一个 child 完成后恢复 parent。关闭与 child completion 可能并发，需要防 double resume 和丢失唤醒。

## 资源作用域

任务树和资源树应对齐：

```text
open connection pool
  enter task scope
    children borrow pool
  join/cancel children
close pool
```

若先关闭 pool 再 join children，就会发生 use-after-close；若 child detach，就无法确定何时安全关闭。

RAII、`defer`、context manager 和 `try/finally` 都可以表达资源作用域，但只能在任务生命周期也被收束时完整生效。

## 背压与 fan-out

结构化并发不自动限制 child 数量。对 $n$ 个输入直接 spawn $n$ 个任务，仍可能耗尽连接、fd、内存或下游 quota。

用 semaphore、有界 channel 或固定 worker group 限制并发：

$$
C_\mathrm{effective}\le
\min(C_\mathrm{CPU},C_\mathrm{I/O},C_\mathrm{downstream},C_\mathrm{memory})
$$

并发上限应由瓶颈和 SLO 测量，而不是固定成“CPU 核数”或任意常量。

## 服务级 detached 工作

确实比单请求活得更久的任务，应重新归属：

```text
process/service scope
├── accept loop
├── metrics exporter
├── cache refresher
└── request scopes...
```

服务关闭时顶层 scope 统一取消并 join。所谓 detached 不再是“无人负责”，只是父作用域更长。

## Go、Kotlin、Swift、C++ 的边界

- Go `context.Context` 传播 deadline/cancel，但裸 `go` 语句不强制 join；需要 `errgroup` 或显式监督协议。
- Kotlin coroutine scope 与 structured concurrency 紧密结合，`supervisorScope` 提供不同失败策略。
- Swift task group 和 child task 形成结构化作用域，unstructured task 有单独语义。
- C++ coroutine 语言本身不提供结构化 scheduler；`std::jthread`/stop token 和 execution proposals 提供不同拼图，具体可用性取决于标准/库版本。

不要因为语法都叫 async/await 就假设失败、取消和 child 生命周期相同。

## 测量

- active child 数和 fan-out 分布；
- scope 完成/取消延迟；
- deadline budget 在各层消耗；
- 取消后仍在运行的任务；
- 异常组大小与首因；
- semaphore/channel 排队；
- shutdown join 时间；
- orphan/detached task 数，应接近显式服务任务集合。

用 trace ID + task ID + parent ID 重建任务树，比只记录线程 ID 更适合 coroutine scheduler。

## 失败模式

- task handle 离开作用域却未 join；
- timeout 只取消 wrapper，底层 I/O 继续；
- child 吞掉取消异常；
- fan-out 无界；
- fail-fast 与 collect-all 语义混淆；
- cleanup 启动新的无限期工作；
- child 持有父栈引用却被 detach；
- shutdown 只发取消，不等待资源真正释放；
- deadline 每层重置，整体远超客户端预算。

## 跨层连接

- coroutine frame 与 scheduler 见[协程](coroutines.md)；
- I/O completion 与取消竞态见[异步 I/O 与事件循环](async-event-loop.md)；
- 队列与活性见[并发基础](foundations.md)；
- stop/join 最终落到线程与[操作系统调度](../os/scheduling.md)。

## Reference

- [Python Documentation: Task Groups](https://docs.python.org/3/library/asyncio-task.html#task-groups)
- [PEP 654: Exception Groups and except*](https://peps.python.org/pep-0654/)
- [Kotlin Documentation: Coroutine Scope and Structured Concurrency](https://kotlinlang.org/docs/coroutines-basics.html#coroutine-scope-and-structured-concurrency)
- [Swift Evolution SE-0304: Structured Concurrency](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0304-structured-concurrency.md)
- [Go context package](https://pkg.go.dev/context)
- [Go x/sync errgroup](https://pkg.go.dev/golang.org/x/sync/errgroup)
- [WG21 P2300R10: std::execution](https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2024/p2300r10.html)
- [WG21 P0660R10: stop_token](https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2019/p0660r10.pdf)
