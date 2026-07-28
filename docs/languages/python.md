# Python：对象模型、CPython 与 asyncio

Python 语言把行为组织在对象协议上：属性访问、迭代、上下文管理、描述符、协程都由数据模型连接。性能与并发问题则必须再指定实现；“Python 有 GIL”实际是对 CPython 某种构建模式的描述，不是 Python 语言规范。

本文以 Python 3.14 文档为语义与标准库基准，以 CPython 3.14 为实现观察点。CPython 字节码、对象头、自适应特化和垃圾回收策略都属于可能跨版本变化的实现细节。

## 一切由对象协议连接 {#object-model}

每个对象都有 identity、type 与 value。identity 一经创建不变；type 决定对象支持的操作，也决定可变性和特殊方法分派。

```python
class Celsius:
    def __init__(self, value: float) -> None:
        self._value = value
    @property
    def value(self) -> float:
        return self._value
    def __iter__(self):
        yield self._value
        yield self._value * 9 / 5 + 32
x = Celsius(20)
assert list(x) == [20, 68]
```

`property` 是 descriptor。属性查找并不只是“查字典”，而是在对象、类、MRO 和 descriptor 协议之间按规则解析。数据描述符可优先于实例字典；函数作为非数据描述符，在通过实例访问时产生 bound method。

特殊方法通常由类型隐式查找，而非普通实例属性查找。例如 `len(x)` 的分派不等价于直接读取 `x.__len__` 后调用；这让解释器能对协议做一致优化。

### 名字不是盒子

赋值把名字绑定到对象：

```python
a = [1, 2]
b = a
b.append(3)
assert a == [1, 2, 3]
```

这里没有“引用传递”这一独立参数模式；函数调用同样把形参绑定到实参对象。可变对象的修改对所有别名可见，重新绑定局部名字则不会改写调用者名字。

## CPython 对象与回收 {#cpython-memory}

CPython 通常用 `PyObject` 头记录类型指针和引用计数，具体类型在其后扩展字段。`id(x)` 在 CPython 中通常对应对象地址，但语言只保证对象生命周期内 identity 唯一。

CPython 的常规回收组合两套机制：

1. 引用计数在计数降到零时通常立即析构；
2. 循环 GC 发现仅由环内部互相引用的不可达容器对象。

这解释了为什么局部对象常“立即释放”，也解释了单靠引用计数无法处理环。不要把及时析构当成跨 Python 实现保证；文件等资源应使用上下文管理：

```python
from pathlib import Path
def first_line(path: Path) -> str:
    with path.open(encoding="utf-8") as f:
        return f.readline()
```

`with` 把 acquire/cleanup 放进 `__enter__` / `__exit__` 协议。异常是否被抑制由 `__exit__` 返回值决定，资源释放不依赖某次 GC。

### 保留内存不等于泄漏

对象释放后，CPython allocator 或系统 allocator 可能保留 arena，不立即把 RSS 还给 OS。排查时区分：

- Python 层仍可达对象；
- allocator 内部空闲块；
- C extension 分配；
- mmap、线程栈和共享库；
- 进程 RSS 与 Python heap。

`tracemalloc` 观察 Python 分配来源，GC 引用图解释可达性，系统 profile 则解释原生部分。

## 从源代码到解释器 {#interpreter}

CPython 通常经历：

```text
source -> tokenizer/parser -> AST -> code object + bytecode
       -> evaluation loop -> adaptive specialization -> native C operations
```

`dis` 可以观察 code object：

```python
import dis
def add(xs):
    return sum(x + 1 for x in xs)
dis.dis(add, adaptive=True, show_caches=True)
```

CPython 3.11 起，部分指令带 inline cache 并可根据运行时类型自适应特化。3.14 的 `dis` 文档仍明确：bytecode 是 CPython implementation detail，操作码、cache 和 offset 都可能跨版本改变。生成或修改字节码的工具必须固定版本。

“一行 Python 慢”往往跨越多层：

- 动态属性和协议查找；
- Python frame 与对象分配；
- C 实现的内建操作；
- C extension 释放 GIL 后的本地计算；
- 缓存局部性与系统调用。

先 profile，再决定改算法、批量调用 C kernel、减少对象、使用进程/线程，还是换实现。

## GIL 与 free-threaded CPython {#gil}

传统 CPython 构建要求线程持有 GIL 才能访问 Python 对象和多数 C API。它保护解释器内部状态和引用计数，但不等于：

- 整个 Python 操作序列原子；
- 用户数据结构自动线程安全；
- 没有 race condition；
- C extension 不会释放 GIL；
- 阻塞 I/O 时一定持有 GIL。

CPython 常在阻塞 I/O 和显式 C API 区域释放 GIL；因此 I/O-bound 线程可并发，native kernel 也可并行。纯 Python CPU-bound 线程在启用 GIL 的同一解释器内通常不能同时执行 Python 代码。

Python 3.13 起提供 free-threaded CPython 构建，3.14 文档说明该模式可在无 GIL 时真正并行执行 Python 线程。它不是“删一把锁”：

- 引用计数、容器访问和 allocator 需要不同同步策略；
- C extension 必须声明和实现 free-threading 支持，否则可能重新启用 GIL；
- free-threaded ABI 与扩展兼容性需单独验证；
- 单线程开销与多线程扩展性必须在目标版本实测。

PEP 703 描述的是 CPython 3.13 路径与设计依据；后续发布行为以相应版本文档为准。

## asyncio：协作式任务 {#asyncio}

`async def` 调用返回 coroutine object；事件循环把 coroutine 包装为 Task 并在 awaitable 完成时恢复。`await`、`async for`、`async with` 是潜在挂起点；只有当前 Task 实际挂起并把控制权交还事件循环时，其他 Task 才有机会运行，已经完成的 awaitable 可以同步继续。

```python
import asyncio
async def fetch(name: str, delay: float) -> str:
    await asyncio.sleep(delay)
    return name
async def main() -> None:
    async with asyncio.TaskGroup() as tg:
        a = tg.create_task(fetch("a", 0.02))
        b = tg.create_task(fetch("b", 0.01))
    print(a.result(), b.result())
asyncio.run(main())
```

`TaskGroup` 把 child task 生命周期限制在作用域内：退出前等待所有任务，失败时取消其余任务并聚合异常。它比裸 `create_task` 更容易维护“创建者负责回收”的不变量。

### 取消是异常协议

Task 取消会在下一次可恢复机会注入 `CancelledError`。协程应在 `finally` 中释放资源，通常在清理后继续传播取消：

```python
async def serve(reader, writer) -> None:
    try:
        while data := await reader.read(4096):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()
```

吞掉 `CancelledError` 会破坏 timeout、TaskGroup 等上层结构。屏蔽取消只应用在很小的、必须完成的一致性区间。

### 事件循环的阻塞边界

- 普通 CPU 循环不会因位于 `async def` 自动让出；
- 同步文件/数据库库会阻塞事件循环线程；
- `asyncio.to_thread` 适合把阻塞调用移到线程，但线程取消不等于强杀底层函数；
- CPU-bound pure Python 在 GIL 构建上通常要用进程，free-threaded 构建则需实测扩展兼容性；
- stream 的 `drain()` 是背压点，省略它可能无界累积输出缓冲。

## 错误与性能边界 {#performance-failures}

### 正确性

- 是否把 CPython 实现细节误写成语言保证？
- descriptor、`__getattribute__` 或 mutable default 是否制造隐藏共享状态？
- 资源是否依赖 `__del__`，并形成环或在解释器退出期访问已清理全局？
- thread-safe 单操作是否被误当成多步事务？
- coroutine 是否被创建却未 await，Task 是否失去强引用或无人收集异常？
- 取消和超时是否沿所有 I/O 层传播？

### 性能

- 用 `cProfile`/sampling profiler 先确定 Python 还是 native 时间；
- 用 `tracemalloc` 和 allocation profile 找对象 churn；
- 对 microbenchmark 固定 Python 实现、版本、构建模式和热身；
- 检查 free-threaded、JIT 或替代实现时，重新验证 C extension、ABI 和 profile 工具；
- 并发吞吐必须同时测 event-loop lag、queue depth 与尾延迟。

## 继续阅读

- 对照其他 event loop：见 [JavaScript](javascript.md) 与 [Node.js](nodejs.md)。
- 对照编译期所有权：见 [Rust](rust.md)。
- 设计可重复 Python 基准：见[基准设计](../performance/benchmarking.md)。

## Reference

- [Python 3.14 Language Reference: Data model](https://docs.python.org/3.14/reference/datamodel.html)
- [Python 3.14 `dis`: CPython bytecode](https://docs.python.org/3.14/library/dis.html)
- [CPython source repository](https://github.com/python/cpython/tree/3.14)
- [CPython C API: Thread states and the GIL](https://docs.python.org/3.14/c-api/threads.html)
- [Python 3.14: Free-threading HOWTO](https://docs.python.org/3.14/howto/free-threading-python.html)
- [PEP 703: Making the Global Interpreter Lock Optional](https://peps.python.org/pep-0703/)
- [`asyncio` task documentation](https://docs.python.org/3.14/library/asyncio-task.html)
- [`asyncio` event loop documentation](https://docs.python.org/3.14/library/asyncio-eventloop.html)
- [`tracemalloc` documentation](https://docs.python.org/3.14/library/tracemalloc.html)
