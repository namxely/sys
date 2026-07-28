# LLVM 与优化：SSA、poison 与 pass pipeline

LLVM IR 位于源语言与目标机器之间：它低到可以表达地址、整数宽度、原子序和调用约定，高到仍保留无限虚拟寄存器、类型、控制流与 metadata。它不是可移植汇编，也不是“更安全的 C”；IR 自身有精确而强的未定义行为与 poison 规则，优化合法性依赖这些语义。

本文固定 LLVM 21.1.0 发布文档作为可重现基准。主站 `llvm.org/docs` 在 2026-07-28 对应后续开发分支，IR 与 pass 名称可能已经不同；实验应始终配套 `opt --version` 与发布版 LangRef。

## 三种等价载体 {#representations}

LLVM code representation 可存在为：

- in-memory IR.
- bitcode；
- human-readable `.ll` assembly。

文本与 bitcode 适合工具交换，但跨 LLVM 大版本的兼容承诺需要按 bitcode policy 核验；内部 C++ API 更不是稳定 ABI。

```llvm
define i32 @sum(i32 %a, i32 %b) {
entry:
  %x = add i32 %a, %b
  ret i32 %x
}
```

每个 `%x` 是 SSA value，不代表一个固定机器寄存器。后端可消除它、常量折叠、复用寄存器或把值 spill 到内存。

## Module、DataLayout 与 target {#module-target}

Module 包含 function、global、alias、metadata 和 target information。相同 IR 在不同 target 上可能有不同合法布局：

```llvm
target triple = "x86_64-unknown-linux-gnu"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
```

DataLayout 描述 endianness、pointer/address space、ABI/preferred alignment、native integer width 与 stack alignment。生成 IR 的前端不能凭宿主 `sizeof` 猜目标；cross compilation 时 host 与 target 明确分离。

opaque pointer 之后，普通 pointer 类型不再编码 pointee type；load/store/call 自己携带访问类型。类型正确不等于 provenance、对齐或对象生命周期正确。

## SSA 与控制流 {#ssa}

基本块由 label 开始，以 terminator 结束。$\phi$ 的 incoming value 与 predecessor 一一对应：

```llvm
define i32 @abs(i32 %x) {
entry:
  %neg = icmp slt i32 %x, 0
  br i1 %neg, label %minus, label %plus
minus:
  %n = sub i32 0, %x
  br label %join
plus:
  br label %join
join:
  %r = phi i32 [ %n, %minus ], [ %x, %plus ]
  ret i32 %r
}
```

这段 IR 对最小负数的行为取决于 `sub` flags：没有 `nsw` 时按固定位宽整数运算；加上 `sub nsw` 后，signed overflow 产生 poison。前端必须准确翻译源语言的溢出规则。

内存操作不服从“每地址只写一次”。LLVM 用 alias analysis、MemorySSA、capture/provenance、function attribute 和 lifetime marker 为内存变换提供证明。

## `undef`、poison、UB 与 `freeze` {#undefined-poison}

这四个概念不能混用：

### Immediate UB

执行到某些操作会使整个执行没有语义约束，例如违反 LangRef 规定的内存访问、执行 `unreachable`、某些除零或调用契约错误。优化器可假设定义良好的程序不会走到这里。

### Poison

poison 是延迟触发的坏值，可由 `nsw`/`nuw`/`exact` 等违反承诺产生。它会沿许多运算传播；一旦在分支条件、内存地址等触发位置使用，可能产生 UB。

```llvm
%x = add nsw i32 2147483647, 1 ; poison
%y = icmp eq i32 %x, 0         ; poison
br i1 %y, label %a, label %b   ; UB
```

### `undef`

每次使用 `undef` 可选择任意允许值，不应把它当作“某个未知但固定的变量”。LangRef 建议在可能时用 poison 表示未定义计算。

### `freeze`

`freeze` 把 poison/undef 变成一次选择后对该结果所有使用保持固定的任意值：

```llvm
%p = add nsw i32 %a, %b
%safe = freeze i32 %p
```

这不会恢复源程序意图，只阻止坏值继续以某些方式传播。任何手写 IR、instrumentation 或 pass 都必须理解这组规则，否则“看起来等价”的变换可能错误。

## 属性与 metadata 是优化契约 {#attributes}

例如：

- `nonnull`、`dereferenceable`、`align` 描述 pointer；
- `noalias` 描述调用边界的别名承诺；
- `readonly`/`memory(...)` 描述内存效应；
- `nounwind`、`willreturn`、`mustprogress` 描述控制流；
- `range`、TBAA、alias scope 提供值或别名信息；
- debug metadata 保持源码映射。

属性不是装饰。前端若错误标注 `nonnull`，用户传 null 时可能不是“检查失效”，而是整个调用进入 poison/UB 语义，导致周围控制流被删除。

metadata 的语义强度不同：debug info 丢失通常不改变程序语义；某些 optimization metadata 则影响变换但有特定 drop 规则。写 pass 时要按 LangRef 逐项处理，不能盲目复制全部 metadata。

## Pass：analysis、transform 与 invalidation {#passes}

analysis 计算 dominator tree、loop info、alias、scalar evolution 等事实；transform 修改 IR。修改后，旧 analysis 是否仍有效必须明确：

```text
IR before
  -> AnalysisManager caches DominatorTree / LoopInfo
  -> Transform changes CFG
  -> preserve exact valid analyses
  -> invalidate the rest
```

New Pass Manager 以 analysis manager 和 preserved analyses 管理缓存。错误宣称“preserved”会让后续 pass 使用陈旧事实，产生误编译；全部 invalidate 虽正确，却损失编译性能。

最小 function pass 骨架：

```cpp
#include <llvm/IR/Function.h>
#include <llvm/IR/PassManager.h>
#include <llvm/Support/raw_ostream.h>
struct CountBlocksPass : llvm::PassInfoMixin<CountBlocksPass> {
    llvm::PreservedAnalyses run(
        llvm::Function& f,
        llvm::FunctionAnalysisManager&) {
        llvm::errs() << f.getName() << ": " << f.size() << "\n";
        return llvm::PreservedAnalyses::all();
    }
};
```

该 pass 只读 IR，所以可保留全部 analysis。若删改 instruction、edge 或 attribute，返回集合必须重新论证。

## 默认优化流水线 {#default-pipeline}

`-O0` 到 `-O3`、`-Os`、`-Oz` 是 driver/pipeline 选择，不属于 LLVM IR 语义。具体 pass 顺序会随 LLVM 版本与 target 改变。概念上需要反复：

1. canonicalize CFG、loops、aggregates；
2. expose constants、known bits、ranges；
3. inline/devirtualize 以扩大局部视野；
4. eliminate dead/redundant work；
5. vectorize/unroll 并权衡 code size；
6. lower 到 target legality；
7. machine optimization、register allocation、scheduling。

pass 不是彼此独立。Inlining 可能暴露常量，随后 SROA 和 DCE 消除对象；也可能扩大函数导致 I-cache miss 与 register spill。观察中间 IR 比只看最终汇编更容易定位因果。

```bash
opt -S -passes='default<O2>' input.ll -o output.ll
opt -S -passes='print<domtree>' input.ll -disable-output
opt -S -passes='loop-simplify,licm' input.ll -o licm.ll
```

用 `-print-pipeline-passes`、debug pass manager 或固定版文档核实 syntax；不要把博客中的旧 legacy pass 参数照搬到新版本。

## Loop 与 vectorization {#loops-vectorization}

LLVM 常先把循环正规化，建立 preheader、single latch、dedicated exit 等结构。ScalarEvolution 用递推表达 induction 与 trip count；Loop Vectorizer/SLP 再依据依赖与成本模型向 SIMD 映射。

向量化合法性需要证明：

- 迭代间没有破坏语义的 memory dependence；
- reduction 顺序在整数/浮点规则下可改变；
- runtime alias check 能覆盖未知关系；
- remainder/epilogue 处理边界；
- 对齐、masked access 与 target instruction 合法。

浮点优化尤其敏感。`fast-math` flags 分别放宽 NaN、Inf、signed zero、reassociation 等语义，不能用一个“CPU 会更快”理由全开。数值稳定性和可复现性也属于正确性契约。

### 读 optimization remark

```bash
clang -O3 -Rpass=loop-vectorize \
  -Rpass-missed=loop-vectorize \
  -fsave-optimization-record demo.c -c
```

remark 可区分 Passed、Missed、Analysis，并携带 source location、pass 与原因。它解释编译器判断，不证明目标 workload 真的加速。

## LTO、ThinLTO 与 PGO {#lto-pgo}

普通分离编译只在 translation unit 内优化；LTO 把 IR 延迟到链接期，能跨单元 inline、devirtualize 和 internalize。Full LTO 视野更集中，资源消耗大；ThinLTO 用 summary index 与分布式 backend 平衡跨单元分析和并行。

PGO 提供实际执行频率：

- instrumentation PGO 先插桩、运行代表 workload、再优化；
- sample PGO 从 profile sample 映射回源码/IR；
- context-sensitive profile 可区分调用上下文。

错误 profile 的风险：

- 训练流量不覆盖生产热路径；
- binary/source mismatch 令映射失真；
- 稀有错误路径被过度冷化；
- 优化后 layout 改变 profile 采集偏差；
- profile 合并掩盖不同机器/租户。

保留 profile provenance、覆盖率和版本，并同时做无 PGO 对照。

## 验证与误编译排查 {#verification}

```bash
opt -passes=verify input.ll -disable-output
clang -O2 -fsanitize=address,undefined test.c
```

IR verifier 检查结构不变量，不证明语义等价。Alive2 可对一部分 LLVM IR transformation 做 translation validation；随机 differential testing 与 reducer 则寻找不同编译配置的输出分歧。

排查顺序：

1. 固定源码、输入、compiler commit、target 与 flags；
2. 用 sanitizer/语言规则排除源 UB；
3. 比较不同优化级别与 backend；
4. 保存 preprocessed source 或 bitcode；
5. 二分 pass/commit；
6. 用 `llvm-reduce` 保留错误谓词最小化。

## 性能与边界 {#performance-failures}

- IR instruction count 不等于机器 work；
- “消除了 load”可能增加 register pressure 与 spill；
- unroll/vectorize 可能伤害 I-cache 和 tail；
- LTO 改变 symbol visibility、debugging、incremental build 与 link memory；
- sanitizer build 改变 layout 和 timing，适合找错而非性能基线；
- `-march=native` 绑定构建机特性，不适合未知部署机器；
- hand-written IR 必须固定 LLVM 语义版本并通过 verifier。

## 继续阅读

- 前端与后端全景：见[编译器流水线](compiler-pipeline.md)。
- LTO 之后如何形成 ELF：见[链接、加载、ELF 与 ABI](linking-loading.md)。
- 检验优化收益：见[基准设计](../performance/benchmarking.md)与[采样分析](../performance/profiling.md)。

## Reference

- [LLVM 21.1.0 Language Reference Manual](https://releases.llvm.org/21.1.0/docs/LangRef.html)
- [LLVM 21.1.0 Undefined Behavior Manual](https://releases.llvm.org/21.1.0/docs/UndefinedBehavior.html)
- [LLVM 21.1.0 New Pass Manager](https://releases.llvm.org/21.1.0/docs/NewPassManager.html)
- [LLVM 21.1.0 Analysis and Transform Passes](https://releases.llvm.org/21.1.0/docs/Passes.html)
- [LLVM 21.1.0 Vectorizers](https://releases.llvm.org/21.1.0/docs/Vectorizers.html)
- [LLVM 21.1.0 Optimization Remarks](https://releases.llvm.org/21.1.0/docs/Remarks.html)
- [Clang 21.1.0 ThinLTO](https://releases.llvm.org/21.1.0/tools/clang/docs/ThinLTO.html)
- [LLVM 21.1.0 PGO](https://releases.llvm.org/21.1.0/docs/HowToBuildWithPGO.html)
- [Alive2: Bounded translation validation for LLVM](https://github.com/AliveToolkit/alive2)
- [Finding and Understanding Bugs in C Compilers](https://www.cs.utah.edu/~regehr/papers/pldi11-preprint.pdf)
