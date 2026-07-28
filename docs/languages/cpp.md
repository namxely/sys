# C++：对象、生命周期与内存模型

C++ 的力量来自一项危险而精确的承诺：高级抽象可以直接映射到存储、调用约定与机器指令，同时编译器能基于语言规则进行激进优化。要驾驭它，不能只记“栈对象会自动析构”，而要把存储、对象生命周期、资源所有权、ABI 和并发顺序连成一条链。

本文以当前 WG21 working draft 为语义基准；对象布局部分以 Itanium C++ ABI 为具体实现实例。后者适用于许多 ELF 平台上的 GCC/Clang，但不是 ISO C++ 保证，也不代表 MSVC ABI。

## 存储不是对象 {#storage-object-lifetime}

一块地址范围先是 storage，只有满足类型的对齐、大小并完成规定的初始化后，某个对象的 lifetime 才开始。对象生命周期结束后，地址可能仍在，但通过旧指针访问原对象通常已不再合法。

```cpp
#include <cstddef>
#include <memory>
#include <new>
struct X {
    int v;
    explicit X(int x) : v(x) {}
    ~X() {}
};
int main() {
    alignas(X) std::byte buf[sizeof(X)];
    X* p = std::construct_at(reinterpret_cast<X*>(buf), 7);
    int x = p->v;
    std::destroy_at(p);
    return x != 7;
}
```

这里有四层事实：

1. `buf` 提供具有正确大小和对齐的 storage；
2. `construct_at` 在该 storage 中开始 `X` 的生命周期；
3. `destroy_at` 结束生命周期，但不回收 `buf`；
4. 析构后继续读取 `p->v` 不是“值还在所以能用”，而是越过了语言生命周期边界。

这一区分解释了 placement new、arena、variant、对象池与反序列化为何容易出错。`memcpy` 是否隐式创建对象、旧指针是否需要 `std::launder`，都取决于对象类别和具体规则，不能用“内存就是字节”替代标准语义。

## RAII 是控制流协议 {#raii}

RAII 把资源所有权绑定到对象生命周期。构造成功意味着不变量成立；离开作用域时，无论正常返回还是异常展开，已构造对象都会逆序销毁。

```cpp
#include <cstdio>
#include <stdexcept>
class File {
    std::FILE* p = nullptr;
public:
    explicit File(const char* path) : p(std::fopen(path, "rb")) {
        if (!p) throw std::runtime_error("open");
    }
    ~File() { if (p) std::fclose(p); }
    File(const File&) = delete;
    File& operator=(const File&) = delete;
    File(File&& other) noexcept : p(other.p) { other.p = nullptr; }
};
```

这段代码的关键不在析构函数短，而在所有权协议完整：

- 拷贝被禁止，避免两个对象关闭同一句柄；
- 移动转移所有权，并让源对象进入可析构状态；
- 移动构造标记 `noexcept`，容器扩容时更可能安全移动；
- 构造失败不会产生一个“半有效”可见对象。

RAII 不保证析构总会发生。`std::abort`、`std::_Exit`、进程被强杀、硬件故障以及某些终止路径不会正常展开。析构也不应抛出异常：若栈展开期间再次抛出，通常会调用 `std::terminate`。

## Rule of Zero 与所有权形状 {#ownership}

优先让标准库组件承载所有权：

```cpp
#include <memory>
#include <string>
#include <vector>
struct Session {
    std::string id;
    std::vector<std::byte> buffer;
    std::unique_ptr<int> state;
};
```

当成员已经正确实现复制、移动和析构时，类本身通常不应手写这些特殊成员，这就是 Rule of Zero。只有在直接管理裸资源时才需要 Rule of Five，并应首先问能否把裸资源封装成一个更小的 RAII 类型。

`shared_ptr` 表达共享所有权，但不等于“通用指针”：

- 控制块计数更新可能是原子操作；
- 强引用环不会自动断开；
- 对象销毁线程由最后一个引用决定，可能把昂贵析构带进延迟敏感路径；
- `shared_ptr` 实例本身的并发读写规则与所指对象的线程安全是两个问题。

## 对象模型落到 ABI {#object-model-abi}

ISO C++ 规定可观察语义，却通常不固定多态对象的字节布局。以 Itanium C++ ABI 为例，动态类对象通常含 vptr，指向 vtable 的 address point；表中还可出现 offset-to-top、RTTI、虚基偏移与虚函数入口。

```cpp
struct Base {
    int x = 1;
    virtual int f() const { return x; }
    virtual ~Base() = default;
};
struct Derived final : Base {
    int y = 2;
    int f() const override { return x + y; }
};
```

调用 `Base* p = new Derived; p->f();` 的概念路径是：

```text
p
└── object bytes
    ├── vptr ──> vtable address point ──> Derived::f entry
    ├── Base::x
    └── Derived::y
```

多重继承可能引入多个 vptr 和 `this` adjustment thunk；虚继承需要在构造阶段使用特殊表。不要把一次 `sizeof` 或反汇编结果提升成跨编译器保证。二进制接口还包括：

- 名字修饰与重载编码；
- 参数和返回值的寄存器/栈传递；
- 异常对象与展开器协议；
- RTTI 和 vtable 的发射位置；
- 标准库类型布局及编译选项。

因此“头文件没变”不代表 ABI 没变。成员顺序、虚函数、基类、对齐、编译器 ABI 版本、`_GLIBCXX_USE_CXX11_ABI` 等都可能破坏已编译调用方。

## 异常、展开与零成本路径 {#exceptions}

许多 Itanium ABI 实现使用表驱动异常：正常路径没有逐层 `setjmp` 开销；抛出时进行两阶段处理，先搜索 handler，再执行 cleanup 并转移控制。所谓“zero-cost exception”只描述未抛出路径的主要机制，仍会增加表、代码尺寸和抛出成本。

RAII 正是清理阶段的语言接口。若跨越 C ABI、禁用展开的边界或不同异常运行时，必须明确转换：

```cpp
extern "C" int api() noexcept {
    try {
        // C++ implementation
        return 0;
    } catch (...) {
        return -1;
    }
}
```

异常不能自然替代错误协议：实时系统可能禁用异常，批处理可能更适合累积错误，库 ABI 需要约定异常是否可穿越。

## 并发内存模型 {#memory-model}

两个线程访问同一非原子标量，至少一个是写，且访问没有 happens-before 顺序时，形成 data race，程序具有未定义行为。`volatile` 不建立线程同步；它主要约束对某些易变对象的访问，不是原子或互斥替代品。

### release/acquire 建立什么

```cpp
#include <atomic>
#include <cassert>
#include <thread>
int data = 0;
std::atomic<bool> ready = false;
int main() {
    std::thread producer([] {
        data = 42;
        ready.store(true, std::memory_order_release);
    });
    std::thread consumer([] {
        while (!ready.load(std::memory_order_acquire)) {}
        assert(data == 42);
    });
    producer.join();
    consumer.join();
}
```

若 acquire load 读到 release store 写入的值，二者 synchronizes-with；`data = 42` sequenced-before release，经传递后 happens-before 消费者的读取，因此读取非原子 `data` 是有序的。

常见序从强到弱并非简单“越弱越快”：

- `seq_cst` 还参与单一全序，最易推理；
- release/acquire 建立跨线程发布与获取；
- relaxed 只保证该原子对象的原子性和 modification order，不发布周围普通写；
- fence 的正确性依赖它连接的具体原子读写关系。

在没有剖析和形式化论证前，优先 mutex 或 `seq_cst`。弱序 bug 常在特定架构、优化级别与时序下才显现。

## 编译器为何能“改变”代码 {#optimization-boundary}

as-if rule 允许编译器执行任何不改变规定可观察行为的变换。未定义行为使编译器不必保留错误执行的直觉结果。例如有符号整数溢出、越界访问、悬垂引用和数据竞争会让基于“这种情况不可能发生”的优化成立。

要理解优化后的行为：

1. 先确认源程序在语言层是否定义良好；
2. 再看 IR 中的 alias、lifetime、`nsw`、poison 等信息；
3. 最后看目标汇编与硬件内存模型。

直接从汇编倒推语言规则会漏掉编译器已经利用的假设。可配合 sanitizers、静态分析与模型检查，但工具覆盖不等于证明。

## 性能与错误边界 {#performance-failures}

### 性能问题

- 大对象值传递可能复制，也可能被 copy elision 消除；应测代码生成。
- 虚调用可能阻止内联，也可能经 devirtualization 消失。
- RAII 本身通常可内联，但所有权设计可能引入分配、引用计数或锁。
- 原子操作成本取决于序、争用、缓存一致性和目标 ISA。
- 异常的冷路径成本、二进制尺寸与指令缓存影响需分别测量。

### 正确性清单

- 每个资源是否有唯一、共享或借用的明确所有权？
- 析构函数是否 `noexcept` 且不会阻塞不可控时长？
- 公开 ABI 是否固定了编译器、标准库、架构和构建选项？
- placement construction 后的生命周期与指针使用是否合法？
- 每个共享可变位置是否通过 mutex 或正确原子关系排序？
- C/FFI 边界是否阻止异常逃逸并约定分配/释放的同一侧？

## 继续阅读

- 对象文件、符号和动态库：见[链接、加载与 ABI](../tooling/linking-loading.md)。
- 观察优化如何利用未定义行为：见 [LLVM 与优化](../tooling/llvm-optimization.md)。
- 用 PMU 与采样验证原子争用和缓存成本：见[采样、perf 与 eBPF](../performance/profiling.md)。

## Reference

- [C++ working draft：Object model](https://eel.is/c++draft/intro.object)
- [C++ working draft：Object lifetime](https://eel.is/c++draft/basic.life)
- [C++ working draft：Destructors](https://eel.is/c++draft/class.dtor)
- [C++ working draft：Multi-threaded executions and data races](https://eel.is/c++draft/intro.races)
- [C++ working draft：Order and consistency](https://eel.is/c++draft/atomics.order)
- [Itanium C++ ABI：Data layout, vtables and linkage](https://itanium-cxx-abi.github.io/cxx-abi/abi.html)
- [Itanium C++ ABI：Exception handling](https://itanium-cxx-abi.github.io/cxx-abi/abi-eh.html)
- [Clang AddressSanitizer documentation](https://clang.llvm.org/docs/AddressSanitizer.html)
- [Clang ThreadSanitizer documentation](https://clang.llvm.org/docs/ThreadSanitizer.html)
