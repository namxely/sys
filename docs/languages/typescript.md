# TypeScript：结构化类型与类型擦除

TypeScript 在 JavaScript 之上建立静态分析层，目标是描述真实 JavaScript 代码的形状，而不是创造一个独立运行时。它的核心边界是：类型检查结果大多会被擦除，运行时仍遵循 ECMAScript 与宿主规则。因此，编译通过不是外部数据验证，也不会让 `number` 在运行时携带类型标签。

本文以 TypeScript 7.0.2 为版本观察点。7.0 将编译器与语言服务迁移到 Go，并采用 TypeScript 6.0 引入的新默认值和兼容语义；但 7.0 尚未提供稳定的 programmatic API，依赖 compiler API、语言插件或嵌入式语言工具链的项目可能仍需并行保留 6.0。类型推断、默认编译选项、模块解析与 checker 性能会随版本变化；发布库时应把 `typescript` 版本和 `tsconfig` 纳入构建输入。

## 结构化兼容 {#structural-typing}

TypeScript 主要根据成员结构判断兼容，而非声明名称：

```typescript
interface Named {
  name: string;
}
class User {
  constructor(public name: string, public id: number) {}
}
const x: Named = new User("Ada", 1);
```

`User` 无需显式 `implements Named`，因为实例包含兼容的 `name`。结构化类型贴合 JavaScript 的对象字面量与 duck typing，但也意味着：

- 两个领域概念若结构相同，可能被意外混用；
- class 的 private/protected 成员会引入来源相关限制；
- 函数参数与可选参数的兼容规则为 JavaScript 惯例保留实用性；
- TypeScript 官方明确说明类型系统并非完全 sound。

需要名义区分时，可用不可伪造的品牌字段：

```typescript
declare const userIdBrand: unique symbol;
type UserId = string & { readonly [userIdBrand]: true };
function parseUserId(x: string): UserId {
  if (!/^[a-z0-9]+$/.test(x)) throw new Error("invalid user id");
  return x as UserId;
}
```

真正安全的转换来自运行时检查；`as UserId` 只是向 checker 声明，不生成验证代码。

## narrowing 是控制流分析 {#narrowing}

TypeScript 根据 `typeof`、`instanceof`、判别字段、真值和用户定义 type predicate 收窄 union：

```typescript
type Result<T> =
  | { ok: true; value: T }
  | { ok: false; error: Error };
function unwrap<T>(r: Result<T>): T {
  if (r.ok) return r.value;
  throw r.error;
}
```

判别 union 把“字段组合是否合法”变成类型不变量，比多个独立可选字段更精确。穷尽检查可借 `never`：

```typescript
type Event = { kind: "open" } | { kind: "close"; code: number };
function describe(e: Event): string {
  switch (e.kind) {
    case "open": return "open";
    case "close": return `close:${e.code}`;
    default: {
      const unreachable: never = e;
      return unreachable;
    }
  }
}
```

控制流分析仍是静态近似。回调、别名修改、getter 副作用和外部 JavaScript 可让先前判断失效；公开 API 应减少跨越可变边界后继续依赖旧 narrowing。

## 泛型、条件类型与分配律 {#conditional-types}

泛型描述输入与输出类型的关系：

```typescript
function first<T>(xs: readonly T[]): T | undefined {
  return xs[0];
}
type AwaitedValue<T> = T extends PromiseLike<infer U> ? AwaitedValue<U> : T;
```

条件类型形如：

$$
T \mathbin{\texttt{extends}} U\ ?\ X : Y
$$

当检查对象是裸类型参数时，union 输入通常会分配：

```typescript
type Box<T> = T extends unknown ? { value: T } : never;
type B = Box<string | number>; // {value: string} | {value: number}
```

若要整体检查可用 tuple 包裹：

```typescript
type IsNever<T> = [T] extends [never] ? true : false;
```

mapped type、indexed access、template literal type 与 `infer` 能构造精确 API，但递归条件类型会增加 checker 实例化和编辑器延迟。类型级“程序”也需要复杂度预算：导出简单中间类型、限制递归深度，测 `tsc --extendedDiagnostics`。

## `any`、`unknown` 与 `never` {#top-bottom}

- `unknown` 可接收任意值，但使用前必须收窄；
- `any` 同时跳过许多检查并向外传播，应视为不受信任边界；
- `never` 表示没有值，可用于穷尽性；
- `object` 排除 primitive，却不表示任意 key-value map；
- `Record<string, unknown>` 也不能替代输入 schema。

```typescript
function parseMessage(x: unknown): { text: string } {
  if (
    typeof x === "object" &&
    x !== null &&
    "text" in x &&
    typeof x.text === "string"
  ) return { text: x.text };
  throw new TypeError("invalid message");
}
```

HTTP、JSON、环境变量、DOM、数据库与 IPC 都在类型系统之外。函数签名写 `x: Message` 只约束 TypeScript 调用者，不能验证网络字节。

## 类型擦除与 emit {#erasure}

TypeScript 编译后主要是 JavaScript：

```typescript
function add(a: number, b: number): number {
  return a + b;
}
```

emit 近似为：

```javascript
function add(a, b) {
  return a + b;
}
```

由此得到几个边界：

- interface/type alias 不存在于运行时；
- overload signature 只影响检查，实际只有一个实现；
- generic type argument 通常不单态化；
- `readonly` 通常是静态限制，不会自动 `Object.freeze`；
- private keyword 与 ECMAScript `#private` 的运行时语义不同；
- target/downlevel transform 可能生成 helper，但不会依据类型改变业务语义。

`noEmitOnError` 决定有类型错误时是否仍 emit；构建链若由其他转译器剥离类型，`tsc --noEmit` 应作为独立质量门。

## 配置就是语义边界 {#compiler-options}

建议显式固定而非依赖跨版本默认值：

```json
{
  "compilerOptions": {
    "target": "ES2025",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "useUnknownInCatchVariables": true,
    "noImplicitOverride": true,
    "verbatimModuleSyntax": true
  }
}
```

这些开关改变静态模型：

- `strict` 是一组会随版本扩展的严格检查；
- `noUncheckedIndexedAccess` 让未知索引结果包含 `undefined`；
- `exactOptionalPropertyTypes` 区分属性缺失与显式 `undefined`；
- `useUnknownInCatchVariables` 强迫检查异常值；
- `verbatimModuleSyntax` 减少 import elision 的隐式变换。

TypeScript 7.0 延续 6.0 的多项新默认值，并将部分 6.0 deprecation 提升为硬错误；既有项目升级应同时阅读 6.0 与 7.0 发布说明，运行全量类型检查、声明兼容测试和真实工具链集成测试，不能只看语义版本号。编译速度提升也不等于所有生态插件已经迁移到新的 API 边界。

## 模块解析必须匹配运行时 {#module-resolution}

TypeScript 同时处理：

1. 源码中 specifier 如何找到类型；
2. 输出保留或改写什么语法；
3. 实际 Node/browser/bundler 如何加载文件。

`moduleResolution: "NodeNext"` 模拟 Node 的 ESM/CJS、`package.json` `type`、`exports` 和条件；`bundler` 模式则允许 bundler 特有解析。类型能解析但运行时不能加载，是配置模型与宿主不一致，不是“Node 缓存问题”。

库发布时检查：

- `exports` 与 `types` 条件是否指向对应格式；
- `.d.ts` 是否泄漏私有路径或版本相关 helper；
- ESM/CJS 是否有双实例状态；
- side effect import 是否被 tree-shaking 错删；
- consumer 使用不同 TypeScript 版本时声明是否可解析。

## 性能与错误边界 {#performance-failures}

### 静态错误边界

- `as`、non-null assertion `!` 和 `any` 会切断证明链；
- declaration file 可以撒谎，运行时包版本必须匹配；
- variance、callback bivariance 等实用规则会保留不完备处；
- getter、Proxy 和 mutation 可能破坏静态形状直觉；
- enum、decorator 等 emit 语义需按目标版本核验。

### 构建性能

- 用 project references 把大图切成可缓存边界；
- 缩小 `include` 和全局 `types`；
- 避免在公共 API 展开巨型递归 conditional/mapped type；
- 记录 `--extendedDiagnostics` 的 files、symbols、types、instantiations 与 check time；
- 把编辑器 latency、冷 `tsc`、incremental build 和 declaration emit 分开测。

## 继续阅读

- 运行时行为和 Promise 调度：见 [JavaScript](javascript.md)。
- Node 模块、流与 libuv：见 [Node.js](nodejs.md)。
- 编译前端与类型检查如何组织：见[编译器流水线](../tooling/compiler-pipeline.md)。

## Reference

- [TypeScript：Type Compatibility](https://www.typescriptlang.org/docs/handbook/type-compatibility)
- [TypeScript：Narrowing](https://www.typescriptlang.org/docs/handbook/2/narrowing.html)
- [TypeScript：Conditional Types](https://www.typescriptlang.org/docs/handbook/2/conditional-types.html)
- [TypeScript：Mapped Types](https://www.typescriptlang.org/docs/handbook/2/mapped-types.html)
- [TypeScript：Modules Reference](https://www.typescriptlang.org/docs/handbook/modules/reference.html)
- [TypeScript：Compiler Options](https://www.typescriptlang.org/tsconfig/)
- [Announcing TypeScript 7.0](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/)
- [TypeScript 6.0 Release Notes](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-6-0.html)
- [TypeScript 7 native compiler source](https://github.com/microsoft/typescript-go)
