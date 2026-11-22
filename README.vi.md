# Hệ Thống Máy Tính (Sys) — Hướng Dẫn Tiếng Việt & Labs Thực Hành

[![Upstream: WineChord/sys](https://img.shields.io/badge/Upstream-WineChord%2Fsys-blue)](https://github.com/WineChord/sys)
[![License: MIT](https://img.shields.io/badge/License-MIT-5c6bc0.svg)](LICENSE)
[![Labs CI](https://github.com/namxely/sys/actions/workflows/labs-ci.yml/badge.svg)](https://github.com/namxely/sys/actions/workflows/labs-ci.yml)

> **Ghi nguồn (MIT License):** Repository này được fork hợp lệ từ [**WineChord/sys**](https://github.com/WineChord/sys) theo giấy phép [MIT](LICENSE). Toàn bộ kiến thức gốc trong [`docs/`](docs/) được giữ nguyên; phần mở rộng của [@namxely](https://github.com/namxely) bổ sung bản đồ học tập Anh–Việt và bộ bài thực hành [`labs/`](labs/README.md) viết bằng Python 3.12 thuần có kiểm thử tự động.

[English Guide](README.en.md) · [中文原版 README](README.md) · [Tài liệu Labs](labs/README.md)

---

## Bản Đồ Kiến Thức (`docs/`)

| Tầng hệ thống | Thư mục | Chủ đề trọng tâm |
| :--- | :--- | :--- |
| **Nền tảng & Phần cứng** | [`foundations/`](docs/foundations/index.md) | Biểu diễn dữ liệu, mô hình hiệu năng & phân cấp bộ nhớ |
| | [`architecture/`](docs/architecture/index.md) | ISA, pipeline, CPU, GPU SIMT, cache coherence, bộ nhớ ảo & TLB |
| **Hệ điều hành & Đồng thời** | [`os/`](docs/os/index.md) | Tiến trình, luồng, lập lịch, hệ thống tệp & I/O bất đồng bộ |
| | [`concurrency/`](docs/concurrency/index.md) | Mutex, atomics, cấu trúc lock-free & coroutines |
| **Mạng & Lưu trữ** | [`network/`](docs/network/index.md) | Gói tin, định tuyến, kiểm soát tắc nghẽn TCP, DNS, HTTP, TLS, Socket & RDMA |
| | [`storage/`](docs/storage/index.md) | SSD, hệ thống tệp, storage engine của CSDL & crash consistency |
| **Song song & Phân tán** | [`parallel/`](docs/parallel/index.md) | Lập trình song song, SIMD & tối ưu khả năng mở rộng |
| | [`distributed/`](docs/distributed/index.md) | Đồng thuận (Raft), nhân bản (replication), phân mảnh & chịu lỗi |
| **Runtime & Hiệu năng** | [`languages/`](docs/languages/index.md) | Cơ chế runtime của C, C++, Go, Rust, Python, JVM, Node.js & Wasm |
| | [`performance/`](docs/performance/index.md) | Benchmark, profiling CPU/RAM & dự báo năng lực hệ thống |
| | [`tooling/`](docs/tooling/index.md) | Trình biên dịch, linker, debugger & công cụ quan sát hệ thống |
| | [`guide/`](docs/guide/index.md) | Cấu trúc & phương pháp biên soạn |

---

## Lộ Trình Gợi Ý Cho Kỹ Sư Backend & Systems

1. **Bộ nhớ đệm & Chính sách loại bỏ (Eviction)**: Đọc `docs/architecture/cache-coherence.md` + `docs/storage/`, sau đó chạy `python labs/cache_policies.py`.
2. **Giao thức mạng & Stream Framing (RESP2)**: Đọc `docs/network/` + `docs/os/`, sau đó chạy `python labs/resp_protocol.py`.
3. **Hệ thống phân tán & Runtime**: Đọc `docs/distributed/` + `docs/languages/`.

---

## Chạy Nhanh Bộ Labs (`Python 3.12+`)

```bash
python -m unittest discover -s labs -v
python labs/cache_policies.py
python labs/resp_protocol.py
```
