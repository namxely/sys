# WebAssembly：验证、线性内存与宿主能力

WebAssembly（Wasm）不是“浏览器里的汇编文本”，也不是一个自带文件、网络和进程 API 的小型操作系统。它首先是一套可验证的低层指令、类型、二进制格式与执行语义；真正的 I/O 能力来自 embedder 提供的 imports。把 core module、runtime instance、host API 与 WASI 分开，才能理解它为什么既可移植，又不会仅凭“沙箱”二字自动安全。

本文以 [WebAssembly Core Specification 3.0](https://webassembly.github.io/spec/core/) 为核心语义基准；该 release 标注日期为 2026-07-27，内容核验至 2026-07-28。浏览器绑定以 WebAssembly JavaScript/Web API 为例，服务端能力以 WASI 与 Wasmtime 为例；它们是不同层，不应被混成一个“Wasm 标准库”。

## 一条从浏览器下载成本到通用组件的路线 {#history}

早期 Web 应用若要运行接近原生速度的计算，常借助插件、JavaScript 引擎特化或 asm.js 子集。这些路线分别面临安全、启动、解析体积和工具链复用问题。2017 年的原始设计论文把 Wasm 描述为一种紧凑、快速解码、可验证且与硬件无关的目标格式，并在浏览器中与 JavaScript 共存。

Wasm 的初始成功来自几个互相支撑的选择：

- 二进制结构可单遍解码，函数体可独立验证与编译；
- 指令带静态类型，控制流是结构化的；
- guest 通过索引访问函数、table、memory 和 global，而不是任意宿主地址；
- core 语义不授予环境能力，宿主只提供明确 imports；
- C/C++、Rust 等前端可复用成熟优化器生成 Wasm。

后来用途从浏览器计算扩展到 edge、插件、serverless 和跨语言组件，问题也从“如何运行一个 module”演化为“接口类型、资源所有权、异步 I/O 与多组件组合如何可移植”。WASI、Component Model 与 WIT 正是在 core 之上回答这些问题，而不是重写 core 指令集。

## 四层契约，不要揉成一层 {#contracts}

```text
source language
      │ compiler
      ▼
core module (.wasm)
      │ validate + instantiate
      ▼
runtime instance ───── imports/exports ───── host embedder
      │                                         │
      └──── component adapters / WASI APIs ─────┘
```

1. **Core spec**：value type、instruction、module、validation、binary/text format 和 execution。
2. **Embedding API**：宿主怎样编译、实例化、提供 imports、取得 exports。
3. **Component Model / WIT**：比 core 函数签名更丰富的接口、资源和语言间 canonical ABI。
4. **WASI**：文件、时钟、随机、socket、HTTP 等能力接口及其版本化组合。

`.wasm` 扩展名只说明二进制容器的一类结果，不能告诉你使用了哪版 proposals、是否为 component、需要哪些 imports、线程是否启用或目标 runtime 是否支持。

## Module 是声明，instance 才有运行时状态 {#module-instance}

[Core spec 的 module 定义](https://webassembly.github.io/spec/core/syntax/modules.html)包含 types、functions、tables、memories、globals、elements、data、imports、exports 和可选 start function。编译后的 module 可视为不可变声明；instantiate 时才把它与具体 imports 匹配，在 store 中分配运行时对象并执行初始化。

两个 instance 可来自同一个 compiled module，却拥有不同的 memory 和 mutable globals：

```text
compiled module M
   ├── instance A: memory A, globals A, imports A
   └── instance B: memory B, globals B, imports B
```

这一区分直接影响缓存和隔离：

- 编译产物可跨请求复用，不等于运行时状态可共享；
- export function 绑定所属 instance，不能脱离它访问“同名 memory”；
- start function 在实例化期间执行，可能调用 imports 并失败；
- import 类型必须匹配，名字相同并不足够。

JS API 中 `WebAssembly.Module` 与 `WebAssembly.Instance` 就体现了这条边界。实际引擎还可能维护 tiering code、jump table 和 VM context，但这些不是 core module 的序列化内容。

## Validation：在执行前维持类型不变量 {#validation}

[Core validation rules](https://webassembly.github.io/spec/core/valid/index.html) 为 module 的索引、类型和指令建立静态约束。验证函数体时，可以把控制流想成一个 type stack machine：

$$
\Gamma \vdash \text{instr} : [t_1^*] \rightarrow [t_2^*]
$$

一条指令从栈上消费输入类型序列，再产生输出类型序列。`i32.add` 消费两个 `i32` 并产生一个 `i32`；`call` 必须匹配目标函数签名；`br` 的值必须符合目标 block 的 label type。结构化 `block`、`loop`、`if` 与 branch depth 避免了任意跳入指令中部。

[规范附录的验证算法](https://webassembly.github.io/spec/core/appendix/algorithm.html)用 value stack、control stack 和 unreachable-polymorphic 状态给出可实现形式。验证的核心效果是：

- 执行不会因操作数类型错配而“掉出”Wasm 类型系统；
- branch 只能到结构化控制栈中的目标；
- local/global/table/memory/function 索引必须在对应 index space 中有效；
- import/export、element/data segment 和 start function 满足静态限制。

实现可以并行或惰性验证函数，但任何函数体在实际执行前都必须通过适用规则。验证通过不证明算法会终止，也不证明逻辑上不会读取 guest 自己的错误对象。

## Linear memory：连续字节数组，不是宿主地址空间 {#linear-memory}

linear memory 是可增长的字节序列。普通 load/store 的地址来自 guest 整数，并加上指令中的静态 offset；每次访问都必须落在当前 memory 范围内，否则 trap。

若有效地址为

$$
a = \operatorname{uN}(i) + o
$$

访问宽度为 $w$，合法条件可概括为

$$
a+w \leq |\text{memory}|
$$

同时还要按规范处理地址加法溢出。引擎可用显式比较、guard pages、信号处理或组合方案实现 bounds check，但不可改变越界必须 trap 的语义。

linear memory 与 GC heap 不同：

- 它只是 bytes，core 不知道 guest 的 `struct`、allocator 或字符串；
- C/Rust 编译器可在其中实现 stack、heap 与 allocator；
- `memory.grow` 以 page 为单位增长，可能失败并返回约定值；
- 宿主拿到的 view 在增长后可能需要重新建立；
- bounds safety 阻止访问 linear memory 之外，不阻止 unsafe guest 覆盖自己 memory 内的另一逻辑对象。

因此，“Wasm memory safe”应准确理解为：通过验证的 core 指令遵守类型与线性内存边界；若 guest 由 C 编译而来，它仍可能在自己的分配器布局内发生 use-after-free、整数溢出或对象间越界，只是通常不能直接逃到宿主地址空间。

## 一段可观测的 module 与宿主 {#code}

下面的 WAT module 导出一页 memory 和一个求和函数。指针按 byte offset 解释，长度按 `i32` 元素数解释：

```wat
(module
  (memory (export "memory") 1 2)
  (func (export "sum_i32") (param $p i32) (param $n i32) (result i32)
    (local $i i32)
    (local $s i32)
    (block $done
      (loop $loop
        local.get $i
        local.get $n
        i32.ge_u
        br_if $done
        local.get $s
        local.get $p
        local.get $i
        i32.const 4
        i32.mul
        i32.add
        i32.load
        i32.add
        local.set $s
        local.get $i
        i32.const 1
        i32.add
        local.set $i
        br $loop))
    local.get $s))
```

用 WABT 的 `wat2wasm` 生成二进制：

```sh
wat2wasm sum.wat -o sum.wasm
wasm-validate sum.wasm
wasm-objdump -x -d sum.wasm
```

Node.js 宿主实例化它、写入 memory，再刻意触发越界 trap：

```javascript
import { readFile } from "node:fs/promises";
const bytes = await readFile(new URL("./sum.wasm", import.meta.url));
const { instance } = await WebAssembly.instantiate(bytes, {});
const values = [1, 2, 3, 4];
const view = new DataView(instance.exports.memory.buffer);
values.forEach((value, i) => view.setInt32(i * 4, value, true));
const total = instance.exports.sum_i32(0, values.length);
if (total !== 10) throw new Error(`unexpected sum: ${total}`);
let trapped = false;
try {
    instance.exports.sum_i32(65532, 2);
} catch (error) {
    trapped = error instanceof WebAssembly.RuntimeError;
}
if (!trapped) throw new Error("expected an out-of-bounds trap");
console.log({ total, trapped });
```

第二次调用第一次读取 memory 末尾 4 bytes 尚合法，第二次读取从 65536 开始，超过一页 memory，必须 trap。`DataView.setInt32(..., true)` 把宿主写入明确固定为 little-endian，与 Wasm load 的字节序一致；跨语言接口还需约定元素宽度、alignment、长度单位和所有权。

代码还暴露了一个重要事实：core 函数只看到 `(i32, i32) -> i32`，不知道第一个参数是指针、第二个参数是元素数。这些高层含义来自编译器 ABI 或 WIT 接口契约。

## Imports、exports 与最小能力 {#host-interface}

[Core introduction](https://webassembly.github.io/spec/core/intro/introduction.html) 指出 module 只能通过 imports 与环境交互。一个没有文件相关 import 的实例不能凭 core 指令自行打开宿主文件。能力边界因此可由 embedder 构造：

```text
guest import request
        │
        ▼
host function
   ├── validate handle and range
   ├── enforce policy / quota
   ├── perform OS operation
   └── return typed result
```

但 import 也正是主要攻击面。宿主函数必须把 guest 提供的 offset/length 当作不可信输入，防止整数回绕、TOCTOU、重入和 stale memory view；若把“打开任意路径”的函数直接导入，Wasm 自身不会替宿主重新收窄权限。

浏览器 JS API 通过 `WebAssembly.instantiate`、`Memory`、`Table` 等对象建立绑定；Web API 再规定 streaming compilation 与 MIME 等 Web 集成。非浏览器 runtime 可定义完全不同的 embedder，而仍执行同一 core module。

## WASI、Component Model 与 WIT {#wasi-components}

WASI 为常见系统能力定义可移植接口，但它不是 POSIX syscall 的简单编号映射。官方 [WASI releases](https://wasi.dev/releases) 在核验时列出：

- **WASI 0.1**：legacy module API，POSIX-inspired，运行时覆盖较广；
- **WASI 0.2**：以 Component Model 和 WIT 为基础的 stable release；
- **WASI 0.3**：在 0.2 基础上加入 `async func`、`stream<T>` 与 `future<T>` 的 stable release。

这些都是 0.x 版本；具体 API proposal 还有各自 phase。写“支持 WASI”信息不足，应记录 preview1/0.1、0.2 或 0.3，所需 world、runtime 版本和启用 features。

### WIT 把接口语义抬高一层

core type 只有数值、reference 等低层表示。WIT 可表达 `string`、`list<T>`、`record`、`variant`、`result`、resource 与 world 的 imports/exports。Canonical ABI 负责把这些类型 lowering 到 core values/linear memory，并在另一侧 lifting 回高层值。

例如接口可以表达：

```wit
package example:checksum;
world tool {
  export checksum: func(data: list<u8>) -> result<u32, string>;
}
```

不同语言组件不必共同约定“指针在 offset 0、错误字符串由谁 free”这类手写 ABI 细节；adapter 和 canonical ABI 处理表示转换。代价是边界仍可能复制、转码、分配，资源 handle 也有明确 lifetime。类型更丰富不意味着跨组件调用免费。

### WASI 是能力接口，不是自动授权

filesystem API 以 preopened directory 等 capability-oriented 方式让宿主选择可见资源。应用是否能联网、读时钟、取随机数或打开路径，由运行时实例化配置与具体接口决定。给整个宿主根目录的预打开权限，再精美的 interface type 也不会恢复最小权限。

## JIT、AOT 与缓存 {#jit-aot}

Wasm engine 仍需把 stack-machine bytecode 映射到寄存器、分支和目标 ISA。常见实现路径包括：

- baseline compiler：快速生成代码，缩短冷启动；
- optimizing JIT：投入更多编译时间做内联、bounds-check elimination、寄存器分配；
- AOT：部署前生成目标相关产物，减少运行时编译；
- tiering：先 baseline，profile 变热后切到优化代码。

“AOT 编译过”不等于产物能跨 CPU 直接运行。机器码缓存键至少应考虑：

```text
module bytes + engine version + feature set + compiler flags
+ target ISA + CPU features + security-relevant configuration
```

忽略 engine 或 feature 版本可能加载语义不兼容的缓存；按开发机 CPU 全量特性编译，也可能在较旧节点触发非法指令。某些 runtime 的 serialized compiled module 还明确要求视为受信任工件，而不是可从不可信来源直接反序列化。

性能也不能只比较 steady-state：

$$
T_{\text{request}} =
T_{\text{decode+validate}}+
T_{\text{compile}}+
T_{\text{instantiate}}+
T_{\text{execute}}+
T_{\text{host boundary}}
$$

短命任务可能由前三项主导；热服务可能由执行、memory locality 和 host call batching 主导。Component lowering/lifting、字符串转码与小调用高频往返也可能比 guest 算法本身更贵。

## 安全边界与资源治理 {#security}

Wasm 的静态验证与 linear-memory bounds 为隔离提供了坚实起点，但完整威胁模型至少还包含：

| 风险 | core 能否直接阻止 | 宿主措施 |
| --- | --- | --- |
| 非法 stack type / branch target | 验证拒绝 | 保持 feature/version 一致 |
| linear memory 越界 | 执行 trap | 正确处理 trap，不复用污染状态 |
| guest 内部对象互相覆盖 | 不能完全阻止 | 使用安全语言、sanitizer、输入验证 |
| 无限循环 | 不能 | fuel、epoch interruption、deadline |
| memory/table 无限增长 | 不能自动限制 | resource limiter、实例配额 |
| 文件或网络越权 | 取决于 imports | 最小 imports、preopen 与 capability |
| host function 漏洞 | 不能 | 审计 offset/length、重入与 ownership |
| Spectre 类微架构侧信道 | core 边界不足以覆盖 | engine/browser mitigation 与进程隔离 |

[Wasmtime security guidance](https://docs.wasmtime.dev/security.html) 把 safe embedder API 与 unsafe 配置、资源限制、可信编译产物等边界分开说明。高风险多租户环境还应组合 OS process、seccomp/sandbox、cgroup、时间与内存配额，而不是让 Wasm instance 独自承担全部隔离。

退出语义也值得设计。trap、WASI exit、host exception 与 engine interruption 不是同一种失败；池化 instance 前要确认 memory、global、resource handle 和宿主侧状态是否已重置。

## 测量与排错闭环 {#measurement}

### 正确性

1. 用 spec-compatible validator 检查 module；
2. 列出 imports/exports、memory/table limits 和启用 proposals；
3. 对 offset/length、`memory.grow`、trap 与缺失 import 做边界测试；
4. 用 WASI shared tests 或目标 runtime conformance suite 验证接口；
5. fuzz decoder、validator、canonical lowering 与 host functions。

### 性能

分别记录 decode/validate、compile、instantiate、首调、steady-state 与 host boundary。基准必须固定 engine build、optimization level、target features、module hash、WASI/Component 版本和缓存冷热。

常见误判包括：

- 把 `.wasm` 体积小等同于首次执行快；
- 把一次 bounds-check elimination 推广到所有 memory access；
- 忽略 JS↔Wasm 或 component boundary 的复制与类型转换；
- 用 native 程序包含 I/O 的端到端时间对比纯 guest kernel；
- 只看平均吞吐，不看 trap、实例化和 tail latency。

### 跨层连接

- Wasm validation 与 JVM bytecode verification 都用类型不变量约束执行，但 object model、GC 和 host capability 边界不同；可对照 [Java 与 JVM](java-jvm.md)。
- linear memory 的页、越界和宿主映射最终仍落到[虚拟内存与 TLB](../architecture/virtual-memory-tlb.md)，但 Wasm page 与 OS page 不是同一抽象。
- AOT/JIT 最终进入目标 ISA 与优化流水线，可对照[编译器流水线](../tooling/compiler-pipeline.md)和 [ISA 与微架构](../architecture/isa-microarchitecture.md)。
- WASI socket/HTTP 是接口层；拥塞控制、TLS 和内核网络栈仍在其下，可沿[网络分层](../network/layers-packets.md)继续追踪。

Wasm 最有价值的思维方式不是“比容器更轻”，而是把一段可验证计算与一组显式宿主能力组合起来，再用更外层隔离和配额完成系统安全。

## Reference

- [WebAssembly Core Specification, Release 3.0](https://webassembly.github.io/spec/core/)
- [WebAssembly Core Specification — Validation](https://webassembly.github.io/spec/core/valid/index.html)
- [WebAssembly Core Specification — Validation Algorithm](https://webassembly.github.io/spec/core/appendix/algorithm.html)
- [WebAssembly JavaScript Interface](https://webassembly.github.io/spec/js-api/)
- [WebAssembly Web API](https://webassembly.github.io/spec/web-api/)
- [Haas et al. — Bringing the Web up to Speed with WebAssembly](https://doi.org/10.1145/3062341.3062363)
- [WASI release and proposal status](https://wasi.dev/releases)
- [WebAssembly Component Model documentation](https://component-model.bytecodealliance.org/)
- [WebAssembly Interface Types language](https://component-model.bytecodealliance.org/design/wit.html)
- [Wasmtime documentation](https://docs.wasmtime.dev/)
- [Wasmtime security documentation](https://docs.wasmtime.dev/security.html)
- [WebAssembly Binary Toolkit repository](https://github.com/WebAssembly/wabt)
