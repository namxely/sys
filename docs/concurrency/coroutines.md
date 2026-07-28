# 协程

协程允许函数在暂停点保存状态、把控制权交给调用者或调度器，之后从原位置恢复。它改变的是控制流表示和等待成本，不自动提供并行、I/O 异步或线程安全。

## 普通调用与协程

普通函数调用形成严格嵌套栈：

```text
caller -> callee -> return -> caller
```

协程可：

```text
caller -> coroutine -> suspend -> caller/scheduler
                         |
                     resume later
```

暂停时必须保存“下一步从哪里开始”和跨暂停点仍存活的局部状态。实现可保存整个栈，也可把需要的状态提升到显式 frame。

<figure class="sys-figure" id="coroutine-state">
  <a class="sys-figure__media" href="../../assets/figures/coroutine-state.svg">
    <img src="../../assets/figures/coroutine-state.svg" alt="协程从创建、就绪、运行到等待事件、完成或取消的状态转换，以及调度、唤醒和取消路径" width="1200" height="560" loading="lazy">
  </a>
  <figcaption>挂起只保存继续执行所需状态；调度、事件唤醒、取消传播与资源回收是彼此独立但相互约束的协议。示意图依据 <a href="https://eel.is/c++draft/dcl.fct.def.coroutine">C++ coroutine 规范</a>与 <a href="https://kotlinlang.org/docs/coroutines-basics.html">Kotlin coroutine 官方文档</a>重新绘制。</figcaption>
</figure>

## stackful 与 stackless

### stackful

每个协程拥有独立栈，能在深层调用中暂停。切换通常保存/恢复寄存器和栈指针。优点是普通同步代码更自然；代价是栈预留/增长、扫描、调试和跨线程迁移复杂。

典型机制包括 fiber、green thread 和某些语言 goroutine 的分段/可增长栈。

### stackless

编译器把协程函数变成状态机，只有显式 suspension point 可以暂停。frame 保存跨暂停点活跃的局部变量、promise/continuation 和状态编号。C++20 coroutine、Rust `async`、Python `async def` 属于这一类语言表面。

frame 大小与生命周期是关键成本；在暂停点跨越的大对象会进入 frame，频繁 heap allocation 也可能主导短任务。

## asymmetric 与 symmetric transfer

asymmetric coroutine 通常由 caller/resumer 恢复，再通过 yield/await 返回。symmetric coroutine 可直接把控制转给另一协程。C++ coroutine 的 `await_suspend` 返回另一个 `coroutine_handle` 可表达 symmetric transfer，帮助长 continuation 链保持常量栈。

语言 API 的术语不同，判断时看控制权交给谁、谁负责下一次 resume，而不是看函数是否叫 `yield`。

## 编译后的状态机

源代码：

```text
x = read()
await writable(fd)
write(x)
```

概念上变为：

```text
frame { state, x, fd, continuation }
resume(frame):
  switch state:
    0: x = read(); state = 1; register writable(fd, frame); return
    1: write(x); state = done; resume continuation; return
```

真实编译器还处理异常、析构、取消和 frame elision。理解这个转换有助于发现：暂停后引用的栈对象是否仍存活，锁是否跨 await 持有，恢复发生在哪个线程。

## C++20 的最小 generator

下面是教学用途的惰性 `Generator<T>`，展示 promise、frame、resume 与销毁。它不是线程安全的，也没有异步 I/O。

```cpp
#include <coroutine>
#include <exception>
#include <iostream>
#include <iterator>
#include <optional>
#include <utility>
template<class T>
class Generator {
public:
    struct promise_type {
        std::optional<T> value;
        std::exception_ptr error;
        Generator get_return_object() {
            return Generator{std::coroutine_handle<promise_type>::from_promise(*this)};
        }
        std::suspend_always initial_suspend() noexcept { return {}; }
        std::suspend_always final_suspend() noexcept { return {}; }
        std::suspend_always yield_value(T v) { value = std::move(v); return {}; }
        void return_void() noexcept {}
        void unhandled_exception() noexcept { error = std::current_exception(); }
    };
    using handle = std::coroutine_handle<promise_type>;
    class iterator {
        handle h_;
    public:
        explicit iterator(handle h) : h_(h) {}
        iterator& operator++() {
            h_.resume();
            if (h_.done() && h_.promise().error) std::rethrow_exception(h_.promise().error);
            return *this;
        }
        const T& operator*() const { return *h_.promise().value; }
        bool operator==(std::default_sentinel_t) const { return h_.done(); }
    };
    explicit Generator(handle h) : h_(h) {}
    Generator(Generator&& o) noexcept : h_(std::exchange(o.h_, {})) {}
    Generator(const Generator&) = delete;
    ~Generator() { if (h_) h_.destroy(); }
    iterator begin() {
        h_.resume();
        if (h_.done() && h_.promise().error) std::rethrow_exception(h_.promise().error);
        return iterator{h_};
    }
    std::default_sentinel_t end() const { return {}; }
private:
    handle h_;
};
Generator<int> range(int n) {
    for (int i = 0; i < n; ++i) co_yield i;
}
int main() {
    for (int x : range(4)) std::cout << x << '\n';
}
```

边界：

- C++20 coroutine 是语言变换设施，不提供标准 task/scheduler；
- generator 被销毁时直接销毁 frame，不能还有外部 resume；
- `yield_value` 在 frame 中保存当前值；
- resume 后异常在观察点重抛；
- 该类型只支持单遍历，重复 `begin` 不属于其契约；
- move assignment 未实现，示例只用于解释机制。

## `await` 协议

C++ awaiter 概念上有：

- `await_ready()`：是否无需暂停；
- `await_suspend(handle)`：注册 continuation/启动操作；
- `await_resume()`：恢复后生成结果或抛错。

最危险的区间在“注册完成”和“真正返回到 caller”之间：异步操作可能立即完成并从另一线程 resume。库必须避免 frame 被并发 resume、过早销毁或发生 use-after-free。

## scheduler 在哪里

协程只有暂停/恢复机制，scheduler 决定：

- 哪个线程执行 resume；
- FIFO、优先级还是 work stealing；
- I/O completion 怎样转成 runnable coroutine；
- timer 与 cancellation 怎样竞速；
- frame 和执行上下文何时销毁。

在单线程事件循环中，CPU 密集协程若长期不 await，会阻塞所有任务；在线程池调度器上，跨 await 的 thread-local 与锁假设可能失效。

## 协程与线程

| 属性 | OS 线程 | stackless 协程 |
| --- | --- | --- |
| 调度 | 内核抢占 | 通常协作式暂停 |
| 栈 | 每线程栈 | 编译器 frame |
| 阻塞 syscall | 只阻塞该线程，但占线程资源 | 若直接调用会阻塞承载线程 |
| 多核并行 | 可 | 取决于 scheduler |
| TLS | 稳定线程语义 | 恢复后可能换线程 |
| 取消 | 平台/协作机制 | 通常协作式传播 |

协程适合大量等待型任务；CPU 密集工作仍需并行执行资源和调度。

## 结构化生命周期

裸 coroutine handle 很容易变成 detached 工作：调用者返回后，frame 仍引用调用者对象。更安全的 task abstraction 应规定：

- 谁拥有 frame；
- 父任务何时 join 子任务；
- 异常怎样传播；
- 取消何时检查；
- 外部 I/O 注册何时注销。

这进入[结构化并发](structured-concurrency.md)。

## 测量

不要只比较“协程切换纳秒数”。端到端观察：

- frame 分配次数与大小；
- runnable queue 长度；
- 每次 resume 的工作量；
- I/O 等待与 scheduler delay；
- 跨线程迁移；
- timer/cancellation 数量；
- p99 延迟和内存占用；
- CPU 密集任务造成的 event-loop lag。

编译器优化可能把 frame 嵌入调用者或消除 suspension；微基准要用反汇编/分配统计确认测到的路径。

## 失败模式

- 把 coroutine 当自动并行；
- 在协程中调用阻塞 I/O，占住 event-loop 线程；
- 跨 `co_await` 持有 mutex；
- frame 引用已离开作用域的对象；
- 同一 handle 被并发 resume；
- 完成与取消竞速导致 double resume；
- detached 协程异常无人观察；
- thread-local 状态跨恢复线程失效；
- 大对象跨暂停点使每个 frame 很大。

## 跨层连接

- readiness 与 completion 如何触发 resume，见[异步 I/O 与事件循环](async-event-loop.md)；
- 线程与内核调度仍在下层，见[进程与线程](../os/process-thread.md)和[调度](../os/scheduling.md)；
- 任务树、取消和 deadline 见[结构化并发](structured-concurrency.md)。

## Reference

- [ISO C++ working draft: coroutines](https://eel.is/c++draft/dcl.fct.def.coroutine)
- [Kotlin Coroutines basics](https://kotlinlang.org/docs/coroutines-basics.html)
- [C++ P0913R1: Add symmetric coroutine control transfer](https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2018/p0913r1.html)
- [Python Documentation: Coroutines and Tasks](https://docs.python.org/3/library/asyncio-task.html)
- [Rust Reference: Await expressions](https://doc.rust-lang.org/reference/expressions/await-expr.html)
- [Rust Async Book](https://rust-lang.github.io/async-book/)
- [Go Language Specification: Go statements](https://go.dev/ref/spec#Go_statements)
- [Go Memory Model](https://go.dev/ref/mem)
