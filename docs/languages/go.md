# Go：goroutine、调度器与垃圾回收

Go 把并发、内存管理和构建模型收进一个较小的语言与运行时组合。`go f()` 看起来只是在函数调用前加一个关键字，实际会牵动 goroutine 栈、G–M–P 调度、抢占、网络轮询、垃圾回收和取消传播。理解这些层次，才能判断“goroutine 很轻”在什么负载下仍然成立。

本文的语言保证以 Go 1.26 specification 与 2022 memory model 为准；运行时结构以 Go 1.26 的 `runtime` 源码为实现实例，属于版本相关细节，并非语言规范承诺。

## 语言层：goroutine 不等于线程 {#goroutine-semantics}

`go f(x)` 先在当前 goroutine 中求值函数和值参数，再启动一个新的 goroutine 执行调用；语言不保证它何时开始、在哪个 OS 线程运行，也不保证主 goroutine 返回前等待它。

```go
package main

import (
	"context"
	"fmt"
	"sync"
)

func worker(ctx context.Context, jobs <-chan int, out chan<- int) {
	for {
		select {
		case <-ctx.Done():
			return
		case x, ok := <-jobs:
			if !ok {
				return
			}
			select {
			case out <- x * x:
			case <-ctx.Done():
				return
			}
		}
	}
}

func main() {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	jobs, out := make(chan int), make(chan int)
	var wg sync.WaitGroup
	wg.Add(1)
	go func() { defer wg.Done(); worker(ctx, jobs, out) }()
	go func() { jobs <- 6; close(jobs) }()
	fmt.Println(<-out)
	wg.Wait()
}
```

这段代码刻意展示结构化边界：

- channel 有方向，生产和消费关系在类型中可见；
- `ok` 区分零值与 channel 关闭；
- 阻塞发送也监听取消，避免消费者提前离开后永久挂起；
- `WaitGroup` 负责 join，`context` 负责停止意图，两者不能互换；
- 创建 `CancelFunc` 的一侧负责调用它，释放父子引用和定时器。

## G–M–P 调度器 {#gmp-scheduler}

Go runtime 源码把三类实体区分为：

- **G**：goroutine，包括栈、寄存器保存区和调度状态；
- **M**：machine，即执行 Go/runtime/syscall 的 OS 线程；
- **P**：运行用户 Go 代码所需的调度与分配资源；P 的数量决定同一时刻可执行 Go 代码的并行度上限，通常由 `GOMAXPROCS` 控制。

概念关系不是固定绑定：

```text
local run queue ---> P <----> M ---- executes ----> G
                         \
                          +--> network poller / global queue / steal
```

每个 P 有本地 runnable queue，降低全局锁竞争；缺少工作时可从全局队列、netpoll 或其他 P 偷取。系统调用可能让 M 阻塞，runtime 可把 P 转交给另一个 M。同步阻塞与调度状态转换围绕 `gopark`、`goready`、`findRunnable` 等路径展开。

这带来三个常见误区：

1. goroutine 不是“永不阻塞线程”；cgo、某些系统调用和不可抢占区仍会影响 M。
2. `GOMAXPROCS=N` 不是“进程只有 N 个线程”；runtime、syscall 与 cgo 可需要更多 M。
3. 轻量不等于免费；每个 G 仍保留栈、调度元数据及其可达对象。

### 栈与抢占

goroutine 使用可增长栈，避免为每个任务预留传统线程量级的固定栈。函数调用的栈检查可触发扩栈，并修正栈内指针。现代 Go 还支持异步抢占，但运行时和编译器仍需维护安全点；长时间执行不可抢占的外部代码不会因语法上运行于 goroutine 就变得公平。

调度问题应通过 `runtime/trace`、goroutine profile 和调度延迟指标验证，而不是从 goroutine 数量单独推断。

## channel：同步语义与 `hchan` 实现 {#channel}

规范层面，channel 是带类型的通信与同步原语。无缓冲发送与接收会 rendezvous；有缓冲 channel 在容量允许时解耦双方。关闭表示以后不会再有发送：

- 向已关闭 channel 发送会 panic；
- 关闭已关闭 channel 会 panic；
- 从已关闭且已排空 channel 接收会立即得到零值和 `ok == false`；
- nil channel 的发送和接收永远阻塞，`select` 可借此动态禁用分支。

Go 1.26 `runtime/chan.go` 的 `hchan` 实现包含环形缓冲区、发送/接收索引、等待发送和接收的 `sudog` 队列以及互斥锁。关键不变量包括：常规情况下发送等待队列与接收等待队列至少一个为空；对有缓冲 channel，缓冲非空意味着接收等待队列为空，缓冲未满意味着发送等待队列为空。

发送大致有三条路径：

1. 已有等待接收者：直接把元素交给对方并唤醒；
2. 缓冲有空间：复制到环形缓冲并推进索引；
3. 否则：把当前 G 封装为等待者，挂入发送队列并 park。

这说明 channel 传递的是值，可能发生元素复制；并且高争用 channel 仍有锁、缓存行和调度成本。用它表达所有权转移与背压很自然，但热点计数器通常更适合原子或分片。

## 内存模型：用同步建立可见性 {#memory-model}

Go memory model 以 sequenced-before、synchronized-before 和 happens-before 描述执行。无同步地并发读写同一位置形成 data race；race-free 程序获得顺序一致性语义的强保证。

典型同步边包括：

- goroutine 创建语句 synchronized-before 新 goroutine 开始；
- channel 发送在对应接收完成之前同步；
- channel 关闭在观察到关闭的接收之前同步；
- mutex 的 `Unlock` 与后续 `Lock` 建立顺序；
- `sync/atomic` 操作提供文档规定的原子顺序。

```go
package main

import (
	"fmt"
	"sync"
)

func main() {
	var mu sync.Mutex
	var ready bool
	var data int
	done := make(chan struct{})
	go func() {
		mu.Lock()
		data, ready = 42, true
		mu.Unlock()
		close(done)
	}()
	<-done
	mu.Lock()
	if ready {
		fmt.Println(data)
	}
	mu.Unlock()
}
```

不要依赖 `time.Sleep`、goroutine 的“通常顺序”、单核机器或一次测试来建立可见性。`go test -race` 能动态发现已执行路径上的竞争，但不能证明未执行路径没有竞争。

## 垃圾回收：成本由活跃堆决定 {#garbage-collector}

Go GC 是并发、追踪式、非分代的 mark-sweep 收集器；精确实现随版本演进。理解调优时可从官方 GC guide 的简化模型出发：

- $L$：上次收集后的 live heap；
- $R$：root set 的额外扫描量；
- `GOGC` 决定新分配多少后触发下一轮；
- `GOMEMLIMIT` 为 runtime 管理内存设置软上限。

简化目标堆大小近似为：

$$
H_{\text{target}} = L + (L + R)\frac{\text{GOGC}}{100}
$$

提高 `GOGC` 通常用更多内存换更少 GC CPU；降低它则相反。Go 1.19 起的软内存上限还考虑 runtime 管理的非堆内存，并故意允许在避免 GC thrashing 时超出：它不是容器 OOM 的硬保险。应给 runtime 不可见内存、cgo、mmap 与操作系统留余量。

GC 的关键输入是**分配速率与活跃对象图**，不只是堆的名义大小。缓存、长寿命 goroutine 栈、未停止的 ticker、挂起 channel 和保存在 closure 中的对象都可能维持可达性。

### 逃逸与分配

“局部变量在栈上”不是规范保证。编译器根据指针是否可能超出调用帧做逃逸分析；接口装箱、closure 捕获、可变大小结构和跨 goroutine 共享都可能影响分配。用：

```text
go build -gcflags='all=-m=2' ./...
go test -bench=. -benchmem ./...
```

观察编译器报告和实测分配，而不要机械地“禁止指针”。减少分配可能降低 GC 扫描和缓存压力，但复制大值也有成本。

## `context`：取消树，不是参数袋 {#context}

`context.Context` 跨 API 边界携带 deadline、取消信号和 request-scoped values。派生 context 构成树，父节点取消会传播到后代。正确约定是：

- 作为首个参数显式传入，不存入长期对象字段；
- 不传 `nil`，暂时不确定时使用 `context.TODO()`；
- value 只放跨 API 的请求元数据，不放可选配置；
- 调用 `CancelFunc`，即使认为父节点很快会取消；
- 底层阻塞 API 必须真正接受 deadline/取消，否则上层 context 只是愿望。

取消是通知，不是强制中断。工作函数需要在安全点观察 `Done()`，并负责回滚或释放。

## 性能与故障边界 {#performance-failures}

### 观测路径

| 问题 | 首要证据 |
| --- | --- |
| CPU 热点 | `go tool pprof` CPU profile |
| 分配/保留 | allocs 与 heap profile，区分累计分配和当前存活 |
| goroutine 泄漏 | goroutine profile、任务创建/完成计数 |
| 调度/阻塞 | `runtime/trace`、mutex/block profile |
| GC 压力 | `runtime/metrics`、`gctrace`、分配率与 live heap |
| data race | `go test -race` 的可复现实例 |

### 设计清单

- goroutine 是否有明确结束条件和 join？
- queue/channel 是否有容量，满时策略是什么？
- 发送、接收、锁等待和外部 I/O 是否都能响应取消？
- channel 的关闭权是否只有生产方拥有？
- `GOMEMLIMIT` 是否为 cgo、mmap 和内核缓存留余量？
- runtime 实现判断是否标注了 Go 版本，并能在升级后重测？

## 继续阅读

- 理解 goroutine 最终如何落到线程和系统调用：见[进程与线程](../os/process-thread.md)。
- 验证 GC、调度和分配成本：见[采样、perf 与 eBPF](../performance/profiling.md)。
- 对照另一种显式借用与异步模型：见 [Rust](rust.md)。

## Reference

- [The Go Programming Language Specification（Go 1.26）](https://go.dev/ref/spec)
- [The Go Memory Model](https://go.dev/ref/mem)
- [Go runtime HACKING：G, M and P](https://go.dev/src/runtime/HACKING)
- [Go runtime `proc.go`：scheduler implementation](https://go.dev/src/runtime/proc.go)
- [Go runtime `chan.go`：channel implementation](https://go.dev/src/runtime/chan.go)
- [A Guide to the Go Garbage Collector](https://go.dev/doc/gc-guide)
- [`context` package documentation](https://pkg.go.dev/context)
- [`runtime/metrics` package documentation](https://pkg.go.dev/runtime/metrics)
- [Go execution tracer documentation](https://go.dev/doc/diagnostics#execution-tracer)
