# 构建系统与可复现产物

构建系统的首要正确性不是“尽量少编译”，而是：当且仅当某个显式或隐式输入影响输出时，依赖图能让相应 action 重新执行。增量、并行、远程缓存和分布式执行都建立在这条不变量上；漏一条依赖，速度越快，传播错误产物也越快。

可复现构建进一步要求：给定等价源输入和定义好的构建环境，独立构建产生逐字节一致的产物。它与 hermeticity、provenance 和供应链隔离相关，却不是同一个概念。

## 构建是有向无环图 {#build-graph}

把每个 action 看作纯函数的理想模型：

$$
O = F(S, D, T, C, E)
$$

其中 $S$ 是源码，$D$ 是依赖，$T$ 是工具链，$C$ 是配置，$E$ 是允许的环境。若所有实际输入都在 key 中，输出 digest 可安全缓存。

```text
headers + source + compiler + flags + sysroot
              \          |          /
               -> compile action -> object
objects + linker + script + libraries -> executable
```

真实 action 常偷偷读取：

- 环境变量、当前目录、用户 home；
- 系统 header/library；
- 当前时间、timezone、locale；
- network response；
- `/proc`、hostname、CPU features；
- 未声明的 generated file；
- directory iteration order。

这些输入若不在 dependency graph/cache key 中，就会造成 stale cache 或不可复现。

## 生成器与执行器 {#generator-executor}

CMake 之类工具通常配置项目、探测平台并生成底层构建图；Ninja 专注快速执行已有图。二者角色不同：

```bash
cmake -S . -B build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build build --parallel
```

配置阶段的 feature test、compiler path 与 cache 也是输入。复制旧 `CMakeCache.txt` 到不同 sysroot 或 compiler 可能得到表面成功但语义不一致的构建。

### 精确依赖

C/C++ include 依赖通常由 compiler depfile 产生；generated header 还必须有生成 rule 的顺序与文件依赖。只写：

```text
app.o: app.cc
```

会漏掉头文件。过度依赖（把整个源码树都作为输入）虽正确，却使小改动触发全量重建。目标是**完整且最小**。

Ninja 的 `depfile`、`deps`、`restat`、implicit/order-only dependency 解决不同问题；把 order-only 当内容依赖会漏重建，把所有顺序边当内容依赖则损失增量性能。

## 四个容易混淆的概念 {#four-properties}

| 概念 | 回答的问题 |
| --- | --- |
| deterministic | 同一环境重复运行是否得到相同输出？ |
| reproducible | 独立参与者在定义的等价环境能否得到相同输出？ |
| hermetic | build 是否只能访问声明输入，隔绝环境与网络隐式变化？ |
| provenance | 能否验证产物由谁、用何输入和过程产生？ |

一个 hermetic build 仍可因未固定随机种子而不 deterministic；两个构建可偶然字节相同，却没有可信 provenance；签名只证明签名者认可某些 bytes，不证明这些 bytes 来自声称源码。

SLSA 1.2 的 build provenance 跟踪 artifact 到 source、builder、parameters 与 dependencies；其 build level 关注 provenance authenticity/isolation，并明确不应把 level 直接等同于 hermetic 或 reproducible。

## 不可复现来源 {#variance-sources}

### 时间

archive、generated source、version string、document footer 和 debug info 可能写入 wall clock。优先删除构建时间；若产物语义需要时间，使用与源码 revision 关联的 `SOURCE_DATE_EPOCH`：

```bash
export SOURCE_DATE_EPOCH="$(git log -1 --pretty=%ct)"
```

这只对支持该约定的工具有效。用 `libfaketime` 拦截时间可能破坏并行构建依赖的 duration，不是通用修复。

### 路径

绝对源码/构建路径会进入 debug info、`__FILE__`、response file 或 archive：

```bash
clang -ffile-prefix-map="$PWD"=/src \
      -fdebug-prefix-map="$PWD"=/src \
      -fmacro-prefix-map="$PWD"=/src
```

这些选项的支持和精确行为需按 compiler 版本核验。调试器还要通过 source mapping 找回真实路径。

### 顺序与并行

filesystem directory iteration、hash map、并发任务完成顺序会改变 archive member、symbol/string table 或 generated registry。修复方式是给逻辑输入建立稳定排序，而不是强制 `-j1` 掩盖 race。

```python
from pathlib import Path
files = sorted(Path("schema").glob("*.json"), key=lambda p: p.as_posix())
```

排序 key 必须明确定义；默认 locale collation 不是跨环境稳定顺序。

### locale、timezone 与编码

```bash
export LC_ALL=C.UTF-8
export TZ=UTC
```

仅设置 `LANG` 可能被更具体 `LC_*` 覆盖。某些最小系统没有 `C.UTF-8`，builder image 仍需固定可用 locale。

### 随机性与未初始化数据

build ID、temporary name、hash seed、LTO partition 和压缩器可能使用随机值。能移除则移除，需要伪随机则用由稳定输入导出的 seed。编译工具写出未初始化 padding 属于 bug，会泄露过程内存并造成不稳定。

### archive metadata

member timestamp、uid/gid、permission、file order 和 compression metadata 都会变化。选择 deterministic archive 模式、规范化权限与所有者；后处理 zip/tar 时保留安全路径规则。

## 定义构建环境 {#environment}

“在容器里构建”不自动 hermetic。镜像 tag 可漂移，网络下载可变化，host kernel、挂载、CPU 和 daemon 仍可能影响结果。环境定义至少包含：

- toolchain binary digest 与 target/sysroot；
- dependency lockfile 和 artifact digest；
- build script/configuration；
- environment allowlist；
- locale/timezone/umask；
- network policy；
- CPU/ISA feature 与 emulation；
- kernel/runtime 接口边界。

依赖最好在执行前 resolve 并以 digest 固定；构建步骤不从 mutable `latest`、默认 branch 或无 checksum URL 下载。

### 内容寻址缓存

action cache key 应包含：

```text
hash(
  command + normalized arguments +
  toolchain digest +
  declared input digests +
  relevant environment +
  target platform
)
```

漏入 key 的 feature flag、compiler plugin、response file 或 generated config 会 cache poisoning。缓存命中后仍应验证 output digest；不同 trust domain 的远程缓存要隔离或签名验证。

## 可复现验证 {#verification}

一次 hash 相等只证明那两次输出相同。更强流程主动改变非语义环境：

```text
build A: path=/tmp/a, user=u1, locale=C.UTF-8, jobs=2
build B: path=/tmp/b, user=u2, locale=other, jobs=16
compare artifact digests
  -> if different: diffoscope / section-aware comparison
  -> classify timestamp/path/order/tool/input
  -> fix generator, rebuild from clean state
```

验证对象要明确：

- unstripped binary 是否要求相同？
- debug package 是否独立比较？
- signature/timestamp 是否在可复现 core 之外？
- package container metadata 是否规范化？
- provenance 是否绑定最终 subject digest？

数字签名通常包含非确定性或时间，不应简单要求两份 signed envelope 字节相同；比较 unsigned payload，再验证各自 signature 与 provenance。

### 一组本地门

```bash
cmake --build build --clean-first
ctest --test-dir build --output-on-failure
sha256sum dist/*
ninja -C build -t graph > build.dot
ninja -C build -t query target
```

`clean-first` 不能替代 incremental test。CI 还应有“先构建、改一个 header/generated input、再增量构建并比较 clean build”的图正确性测试。

## 构建性能 {#build-performance}

优化按因果顺序：

1. 用 trace/timing 分解 configure、compile、codegen、link、package；
2. 修剪无效依赖边与 generated fan-out；
3. 减少 header/token、模板实例化和重复 codegen；
4. 用并行度匹配 CPU、内存、I/O 与 license server；
5. 引入本地/远程 cache；
6. 再考虑 unity build、PCH、modules、distributed execution。

关键路径时间受 work 与 span 共同约束：

$$
T_P \geq \max\left(\frac{T_1}{P}, T_\infty\right)
$$

无限加 worker 无法短于 dependency graph critical path，反而可能因内存压力和 I/O contention 变慢。

PCH/unity build 可减少重复 parsing，却可能扩大失效域、掩盖缺失 include 和改变宏/ODR 行为。必须同时测 clean、incremental、峰值内存与 correctness。

## 常见失败 {#failure-modes}

- “本地不用 clean 就好”：漏依赖，fresh CI 才失败；
- “CI 每次 clean 所以没问题”：增量开发和远程缓存仍可能错误；
- “lockfile 固定了全部”：toolchain、build script、系统库和网络仍漂移；
- “hash 不同就是源码不同”：timestamp、path、order 等非语义输入；
- “容器保证复现”：mutable image、host/kernel 与未封网；
- “cache 只影响速度”：错误 key 会返回语义错误产物；
- “签名证明源码”：签名只绑定 bytes 与 signer，provenance/verification 才连接过程；
- “关并行即可复现”：它隐藏未定义顺序与 race，没修根因。

## 继续阅读

- 构建生成 object 后发生什么：见[链接、加载、ELF 与 ABI](linking-loading.md)。
- 编译时间为何增长：见[编译器流水线](compiler-pipeline.md)。
- 设计稳定测量：见[基准设计](../performance/benchmarking.md)。

## Reference

- [CMake：Buildsystem Manual](https://cmake.org/cmake/help/latest/manual/cmake-buildsystem.7.html)
- [CMake：Presets Manual](https://cmake.org/cmake/help/latest/manual/cmake-presets.7.html)
- [Ninja Build Manual](https://ninja-build.org/manual.html)
- [Reproducible Builds：Definitions](https://reproducible-builds.org/docs/definition/)
- [Reproducible Builds：SOURCE_DATE_EPOCH](https://reproducible-builds.org/docs/source-date-epoch/)
- [Reproducible Builds：Build path](https://reproducible-builds.org/docs/build-path/)
- [Reproducible Builds：Timestamps](https://reproducible-builds.org/docs/timestamps/)
- [Reproducible Builds：Stable inputs](https://reproducible-builds.org/docs/stable-inputs/)
- [SLSA Specification 1.2](https://slsa.dev/spec/v1.2/)
- [SLSA 1.2：Build requirements](https://slsa.dev/spec/v1.2/build-requirements)
- [SLSA：Build provenance](https://slsa.dev/spec/v1.2/build-provenance)
