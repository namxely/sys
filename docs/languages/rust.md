# Rust：所有权、安全边界与 Future

Rust 的核心不是“没有垃圾回收”，而是把资源有效性、可变别名与跨线程传递变成静态证明问题。编译器拒绝一部分本可正确运行的程序，以换取一条强边界：不含错误 `unsafe` 的 Safe Rust 不会产生内存未定义行为。理解这条边界，也要理解它不保证无死锁、无泄漏或业务正确。

本文以 Rust 1.97.1、2024 Edition 的官方文档为实现与版本观察点。语言 Reference 中仍有明确标注为未完全规定的区域，尤其是完整 aliasing 模型；此处不会把某一版 `rustc` 行为冒充永久语言保证。

## 所有权是资源状态机 {#ownership}

一个值有一个 owner；移动把销毁责任转移给新 owner，旧绑定不再可用。离开 drop scope 时，若值仍处于已初始化状态，就运行析构。

```rust
struct Buffer {
    data: Vec<u8>,
}
fn consume(mut b: Buffer) -> usize {
    b.data.push(1);
    b.data.len()
}
fn main() {
    let b = Buffer { data: vec![1, 2] };
    let n = consume(b);
    assert_eq!(n, 3);
}
```

这不是运行时所有权表。对普通移动，编译器通常只改变静态可用性，机器层可能没有额外动作。若类型实现 `Copy`，赋值保留源绑定并复制值；实现 `Drop` 的类型不能同时是 `Copy`。

析构顺序也是语义的一部分：局部绑定通常按声明逆序销毁，结构字段按声明顺序递归销毁。部分移动后只销毁仍初始化的字段。`mem::forget` 是安全函数，因此库不能把“析构必执行”作为内存安全的唯一前提。

## 借用：共享或独占 {#borrowing}

核心近似是：

- `&T`：在其有效期内可共享读取，不能通过普通路径修改；
- `&mut T`：在其有效期内对所指位置拥有独占访问；
- lifetime 描述引用可用区间之间的关系，不负责延长对象寿命。

```rust
fn split_at_mut<T>(xs: &mut [T], mid: usize) -> (&mut [T], &mut [T]) {
    assert!(mid <= xs.len());
    let (a, b) = xs.split_at_mut(mid);
    (a, b)
}
```

`split_at_mut` 的库实现需要证明两个子切片不重叠；安全调用者得到两个 `&mut`，可以依赖独占不变量。借用规则给优化器提供 alias 信息：若 `&T` 与 `&mut T` 合法并存，它们不能以破坏规则的方式指向同一活跃位置。

### 内部可变性

`UnsafeCell<T>` 是共享引用内部可变性的底层逃生口；`Cell`、`RefCell`、`Mutex` 和原子类型在其上建立不同检查：

- `Cell` 通过复制值避免给出内部引用；
- `RefCell` 在运行时检查单线程借用，违规会 panic；
- `Mutex` 用同步建立跨线程独占；
- atomics 以目标支持的原子操作和内存序约束并发。

类型为 `Sync` 意味着 `&T` 可安全跨线程共享；`Send` 意味着值可安全转移到另一线程。它们是 `unsafe auto trait`：编译器可自动推导，而手写错误实现会让安全调用者触发未定义行为。

## `unsafe` 是证明义务，不是关闭规则 {#unsafe}

`unsafe` 允许执行少数编译器无法验证的操作，如解引用裸指针、访问可变 `static`、调用 unsafe function、实现 unsafe trait 或声明外部 ABI。它不允许程序产生未定义行为，只是把证明责任交给程序员。

```rust
pub fn get_two_mut<T>(xs: &mut [T], i: usize, j: usize) -> (&mut T, &mut T) {
    assert!(i < xs.len() && j < xs.len() && i != j);
    let p = xs.as_mut_ptr();
    unsafe {
        // Safety: bounds are checked and i != j, so the two elements do not overlap.
        (&mut *p.add(i), &mut *p.add(j))
    }
}
```

一个可审计的 unsafe 封装应写清：

1. 调用前置条件；
2. 每个裸指针的 provenance、对齐、初始化和有效长度；
3. alias 与可变性不变量；
4. panic/unwind 时是否仍保持状态有效；
5. `Send`/`Sync` 和 FFI 跨线程约束；
6. 安全 API 为什么无法构造破坏这些条件的输入。

把 unsafe block 缩小只改善定位，不自动改善正确性。边界外的安全代码仍可能改变 unsafe 所依赖的全局状态，因此不变量必须附着于类型和 API。

### FFI 与 ABI

`extern "C"` 选择调用 ABI，不自动证明参数合法。跨边界还需约定：

- `#[repr(C)]` 或协议化序列化布局；
- 谁分配、谁释放，使用哪一个 allocator；
- 字符串编码、长度、空指针与别名；
- panic/foreign exception 能否穿越；
- callback 的线程、生命周期和取消。

Rust 2024 要求 `extern` block 明确为 `unsafe extern`，突出签名本身就是承诺。即使签名写对，C 端越界或保存短期指针仍可破坏 Rust 假设。

## async：编译成可轮询状态机 {#async-future}

`async fn` 返回一个实现 `Future` 的惰性值；没有 executor 主动 `poll`，future 不会自行推进。核心 trait 是：

```rust
pub trait Future {
    type Output;
    fn poll(
        self: std::pin::Pin<&mut Self>,
        cx: &mut std::task::Context<'_>,
    ) -> std::task::Poll<Self::Output>;
}
```

每个 `.await` 是潜在挂起点。概念上，编译器把跨挂起点仍活跃的局部变量装进匿名状态机：

```text
Start { input }
  --poll--> Waiting { input, io_future }
  --wake/poll--> Done { output }
```

`Poll::Pending` 前，future 应保存当前 `Waker`；资源可推进时调用 `wake`，executor 再把任务放回 runnable queue。future 的 `poll` 不应阻塞或忙等，否则会堵住承载多个任务的 executor 线程。

### 为什么需要 `Pin`

状态机可能自引用：某字段指向同一 future 内的另一字段。若第一次 poll 后移动整个 future，内部地址会失效。`Pin<&mut T>` 表示在满足 pin contract 的情况下不能再移动被固定值；`Unpin` 类型则不依赖固定地址。

Pin 不会自动让裸指针正确，也不等于“在堆上”。它是 unsafe code 可依赖的一项移动约束。

### 取消与 drop

大多数 Rust future 通过被丢弃来取消。取消可发生在任意 `.await` 挂起点，因此：

- 跨 await 的状态必须在 drop 时保持可析构；
- 外部操作是否真正取消取决于驱动和协议；
- 写入一半、事务一半和锁持有一半需要设计 cancellation safety；
- `select` 类组合可能重复创建并丢弃 losing future。

结构化并发库必须进一步定义 child task 是否 join、abort，以及错误如何传播；这些不是 `Future` trait 自带保证。

## 并发与原子 {#concurrency}

Safe Rust 阻止 data race，却不阻止逻辑 race、死锁、饥饿和 ABA。`Arc<Mutex<T>>` 只是共享所有权加互斥：

```rust
use std::sync::{Arc, Mutex};
use std::thread;
fn main() {
    let n = Arc::new(Mutex::new(0_u64));
    let mut hs = Vec::new();
    for _ in 0..4 {
        let n = Arc::clone(&n);
        hs.push(thread::spawn(move || *n.lock().unwrap() += 1));
    }
    for h in hs { h.join().unwrap(); }
    assert_eq!(*n.lock().unwrap(), 4);
}
```

`MutexGuard` 的 Drop 释放锁，panic 会令标准 mutex poisoned，提醒调用者受保护不变量可能未完成；`into_inner` 等 API 允许显式恢复。不要无思考地 `unwrap()` poison，也不要持锁跨慢 I/O 或 `.await`。

原子内存序与 C++ 有共同谱系，但应以 Rust `std::sync::atomic` 文档与目标平台验证。先用锁表达不变量，再用基准和模型工具证明有必要下沉到 lock-free。

## 内存与性能边界 {#performance}

Rust 的静态模型不承诺每个抽象都“零字节成本”：

- 泛型通常单态化，利于内联但可能膨胀代码体积；
- trait object 使用动态分派和 fat pointer，可能阻止部分优化；
- `Arc` 的原子引用计数会产生共享缓存行流量；
- `Box`、`Vec`、`String` 涉及 allocator，所有权本身不消除分配；
- async 状态机大小等于跨 await 保存状态的组合，深层组合可增大 future；
- panic 采用 unwind 或 abort 取决于 profile 与目标设置。

测量时同时看：

```text
cargo build --release
cargo asm / llvm-ir inspection
allocation count + RSS
perf stat / perf record
binary size and cold-start
```

不要用 debug build 评价稳态性能，也不要只看平均时间忽略单态化后的指令缓存压力。

## 正确性清单 {#correctness-checklist}

- 引用是否可能越过 owner、容器扩容或 FFI callback 生命周期？
- `unsafe` 的 Safety contract 是否覆盖别名、对齐、初始化和 unwind？
- 自定义 `Send`/`Sync` 是否真的对所有泛型参数成立？
- 资源释放是否错误地依赖析构“必定执行”？
- future 的每个挂起点是否 cancellation-safe？
- 是否持同步 mutex guard 跨 `.await`？
- `#[repr(C)]` 之外的布局是否被误当成稳定 ABI？
- 实现观察是否标注了 rustc/标准库版本？

## 继续阅读

- 从 Rust MIR/LLVM IR 追踪所有权抽象如何消失：见 [LLVM 与优化](../tooling/llvm-optimization.md)。
- FFI、符号与动态加载：见[链接、加载与 ABI](../tooling/linking-loading.md)。
- 与 GC runtime 对照：见 [Go](go.md) 和 [Python](python.md)。

## Reference

- [The Rust Reference: Destructors](https://doc.rust-lang.org/reference/destructors.html)
- [The Rust Reference: Unsafety](https://doc.rust-lang.org/reference/unsafety.html)
- [The Rust Reference: Undefined behavior](https://doc.rust-lang.org/reference/behavior-considered-undefined.html)
- [Rust standard library: `Future`](https://doc.rust-lang.org/std/future/trait.Future.html)
- [Rust standard library: `Pin`](https://doc.rust-lang.org/std/pin/)
- [Rustonomicon: Aliasing](https://doc.rust-lang.org/nomicon/aliasing.html)
- [Rustonomicon: Send and Sync](https://doc.rust-lang.org/nomicon/send-and-sync.html)
- [The Async Book](https://rust-lang.github.io/async-book/)
- [Rust Reference: Type layout](https://doc.rust-lang.org/reference/type-layout.html)
- [Rust Reference: External blocks](https://doc.rust-lang.org/reference/items/external-blocks.html)
