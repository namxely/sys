# DNS、HTTP 与 TLS

一次 HTTPS 访问不是“发一个 HTTP 包”，而是一条相互约束的解析与握手链：名称解析出候选地址，客户端选择路径与传输，TLS 认证对端并协商密钥，HTTP 才在已建立的安全通道上交换语义。

<a id="dns"></a>
## DNS：分层命名与缓存

递归解析器替客户端追踪委派；权威服务器回答自己负责的 zone。典型路径是根 → TLD → 权威，但缓存命中会截断路径。RRset 是缓存与签名的基本单位，常见记录包括 `A`、`AAAA`、`CNAME`、`NS`、`MX`、`TXT`。

TTL 控制缓存上限，却不是全球切换倒计时：旧查询可能在不同时间缓存，负缓存也有 TTL。`CNAME` 表示别名，不能与同名其他数据随意共存；负载均衡还需考虑客户端/递归解析器位置与地址选择。

DNSSEC 提供来源认证与完整性链，不提供查询内容保密。DoT/DoH 加密客户端到解析器的一段，权威查询和解析器信任仍是不同问题。

<a id="tls"></a>
## TLS 1.3：认证与密钥派生

完整握手的核心：

1. ClientHello 提供版本、cipher suites、key share 与 SNI 等；
2. ServerHello 选择参数并给出 key share；
3. 双方从 (EC)DHE 共享秘密经 HKDF 派生握手密钥；
4. 服务端发送证书与 CertificateVerify，客户端验证名称、链、有效期和签名；
5. Finished 对握手 transcript 做密钥确认；
6. 派生应用流量密钥。

TLS 1.3 的 cipher suite 主要选择 AEAD 与哈希，密钥交换和签名算法另行协商。前向保密依赖临时 (EC)DHE；会话恢复降低握手成本，但 0-RTT 数据可被重放。

证书验证失败不能通过“忽略错误”修复。应检查系统时间、SNI/hostname、完整证书链、信任根与吊销策略，并区分 TLS 终止点和真正业务后端。

<a id="http"></a>
## HTTP：语义独立于线格式

HTTP 定义资源、方法、状态码、字段和缓存语义。HTTP/1.1、HTTP/2、HTTP/3 共享这些语义，但线格式和传输不同：

| 版本 | 复用方式 | 主要阻塞边界 |
| --- | --- | --- |
| HTTP/1.1 | 多连接或流水线 | 连接内响应顺序 |
| HTTP/2 | TCP 上多个 stream | TCP 丢包影响整个连接 |
| HTTP/3 | QUIC streams | 通常限于丢包所属流 |

`GET` 和 `HEAD` 是 safe；`GET`、`HEAD`、`PUT` 与 `DELETE` 的标准方法语义是 idempotent，但具体服务仍需正确实现。`POST` 并非必然不可重试：配合幂等键和原子结果记录可以安全重放。

<a id="cache"></a>
## 缓存与条件请求

新鲜度由 `Cache-Control`、`Expires` 和计算年龄共同决定。过期不等于内容必须重新完整下载；客户端可带 `If-None-Match`/ETag 或 `If-Modified-Since` 再验证，未变化则返回 `304`。

共享缓存必须尊重 `private`、`no-store`、`Vary` 和认证语义。`no-cache` 表示使用前必须验证，不等于禁止存储。缓存键遗漏语言、编码或授权维度会造成内容混淆甚至数据泄漏。

<a id="waterfall"></a>
## 延迟瀑布与失败边界

冷连接近似：

$$
T\approx T_{\mathrm{DNS}}+T_{\mathrm{transport}}
+T_{\mathrm{TLS}}+T_{\mathrm{request}}+T_{\mathrm{server}}
$$

连接复用、DNS 缓存、TLS resumption 和 QUIC 可以消去或重叠其中部分 RTT。测量时分别记录：

- 解析、连接、TLS、首字节和下载时间；
- 是否命中本地/递归/CDN 缓存；
- HTTP 版本、IP 家族、复用连接与重试次数；
- 证书验证结果和最终远端地址。

`curl -w`、浏览器 timing、服务端 trace 与抓包需要同一时间基准。只看“总耗时”无法区分 DNS 慢、握手重传、服务端排队或响应体拥塞。

## 请求链的相邻层

- [TCP、UDP 与 QUIC](transport-tcp-udp-quic.md) 展开 HTTP/1.1、HTTP/2 与 HTTP/3 所依赖的传输差异。
- [Socket 与 I/O 模型](sockets-io.md)说明握手与响应在非阻塞程序中怎样表现为 readiness、completion 和 deadline。
- [可靠性与可观测性](../distributed/reliability-observability.md)把 trace context、重试预算和 SLO 接到同一请求链。

## Reference

- [RFC 1034: Domain Names — Concepts and Facilities](https://www.rfc-editor.org/rfc/rfc1034)
- [RFC 1035: Domain Names — Implementation and Specification](https://www.rfc-editor.org/rfc/rfc1035)
- [RFC 4033: DNS Security Introduction and Requirements](https://www.rfc-editor.org/rfc/rfc4033)
- [RFC 8446: TLS 1.3](https://www.rfc-editor.org/rfc/rfc8446)
- [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110)
- [RFC 9111: HTTP Caching](https://www.rfc-editor.org/rfc/rfc9111)
- [RFC 9113: HTTP/2](https://www.rfc-editor.org/rfc/rfc9113)
- [RFC 9114: HTTP/3](https://www.rfc-editor.org/rfc/rfc9114)
