# Daft 并发机制介绍

## 1. 总览

Daft 的并发机制不是单点参数，而是分层协同：

1. Runner 层：决定在本机并行（Native）还是分布式并行（Ray）。
2. 任务切分层：通过 Partition（分区）与 Batch（批次）控制任务粒度。
3. UDF 层：通过 `@daft.func`、`@daft.cls`、`@daft.method` 控制执行并发、进程隔离和重试。
4. I/O 层：通过下载连接并发（`max_connections`）控制远程读取吞吐与内存压力。

建议把 Daft 并发理解为“调度并发 + 算子并发 + I/O 并发 + 内存反压”的组合系统。

---

## 2. Runner 层并发

### 2.1 `daft.set_runner_native()`

```python
import daft

daft.set_runner_native()
```

含义：

- 使用本机 Native Runner（Swordfish）。
- 并发来源于本机资源和 Daft 内部执行调度。

适用：

- 单机开发、调试、轻中等规模任务。

### 2.2 `daft.set_runner_ray(...)`

```python
import daft

daft.set_runner_ray("ray://127.0.0.1:10001")
```

文档中可见的关键参数：

- `address`：连接本地/远程 Ray 集群。
- `max_task_backlog`：任务积压上限（防止任务无界堆积）。

含义：

- 并发扩展到多机多 worker。
- 与 UDF 资源请求（如 GPU）结合后，整体吞吐可显著提升。

---

## 3. 任务切分并发：Partition 与 Batch

## 3.1 `repartition`（分区并发）

```python
# 按随机策略分 16 个分区
# df = df.repartition(16)

# 按键哈希分区
# df = df.repartition(16, "user_id")
```

含义：

- 分区是固定数量的独立工作单元。
- 主要用于分布式 Runner（Ray/K8s），控制跨 worker 的并行度。

策略：

- Random：负载均衡优先。
- Hash：保证同键数据在同分区（适合 join/groupby 前控制代价）。

### 3.2 `into_batches`（批次并发）

```python
# 将后续算子处理粒度限制为每批 1000 行
# df = df.into_batches(1000)
```

含义：

- 批次按“每批行数”切分，不是固定批次数。
- Native 和 Ray 都生效。
- 是控制内存峰值和每任务负载的关键手段。

经验：

- 想控制跨机任务分发：优先 `repartition`。
- 想控制算子内存与局部吞吐：优先 `into_batches` / UDF `batch_size`。

---

## 4. UDF 并发机制

## 4.1 `@daft.func`（无状态函数 UDF）

### 支持的参数

`@daft.func` 装饰器支持以下参数：

1. **`return_dtype`** (`DataTypeLike | None`): 指定函数返回的数据类型。如果不指定，Daft 会从函数的返回类型注解中自动推断。
2. **`unnest`** (`bool`): 当设置为 `True` 时，会将返回的结构体字段展开为单独的列。返回类型必须是 `DataType.struct(..)` 时才能使用此选项。默认为 `False`。
3. **`use_process`** (`bool | None`): 控制是否在单独的进程中运行函数实例。如果不设置，Daft 会根据运行时性能自动选择。
4. **`max_retries`** (`int | None`): 设置函数失败时的最大重试次数。
5. **`on_error`** (`Literal["raise", "log", "ignore"] | None`): 指定错误处理方式 - 可以选择抛出异常、记录日志或忽略错误。

对于批处理函数 `@daft.func.batch`，还支持额外的参数：

- **`batch_size`** (`int | None`): 设置每个输入批次的最大行数。

### 如何控制并发

**重要提示：`@daft.func` 本身不支持 `max_concurrency` 参数**。并发控制只在 `@daft.cls` 装饰器中可用。

如果您需要控制并发，有以下选项：

1. **使用异步函数实现并发**
   `@daft.func` 支持异步函数（`async def`），Daft 会自动并发执行多个行，无需额外配置。

2. **使用 `@daft.cls` 控制并发**
   如果需要精确控制并发实例数量，应该改用 `@daft.cls` 装饰器，它的 `max_concurrency` 参数可以限制跨所有 worker 的最大并发实例数。

### 示例

```python
import daft
from daft import DataType, Series

# 批处理示例
@daft.func.batch(return_dtype=DataType.int64(), batch_size=1024)
def batch_process(x: Series) -> Series:
    return x * 2

# 异步并发示例
@daft.func(return_dtype=DataType.string())
async def async_fetch(url: str):
    # 自动并发执行 I/O
    return await fetch_url(url)
```

### 4.2 `@daft.cls`（有状态类 UDF）

适用场景：

- 模型加载、连接初始化等“高成本初始化”可复用场景。

并发核心参数：

- `max_concurrency`：全局最多并发实例数（上限语义）。
- `gpus`：每实例 GPU 资源请求。
- `use_process`：实例是否在独立进程执行。

示例：

```python
import daft

@daft.cls(gpus=1, max_concurrency=4, use_process=True)
class ImageClassifier:
    def __init__(self, model_path: str):
        self.model_path = model_path

    def __call__(self, image_path: str) -> str:
        return "ok"
```

机制要点：

- 类实例会在执行阶段初始化并复用。
- 与 `@daft.func` 相比，更适合把初始化成本摊薄到大量数据上。

### 4.3 `@daft.method`（类方法 UDF）

- 类中的方法默认可作为 UDF 使用。
- 可用 `@daft.method` 覆盖返回类型、错误策略等。
- 批处理方法使用 `@daft.method.batch`，并通过 `batch_size` 控制粒度。

示例：

```python
import daft
from daft import DataType, Series

@daft.cls(max_concurrency=2)
class Model:
    @daft.method.batch(return_dtype=DataType.int64(), batch_size=256)
    def infer(self, x: Series) -> Series:
        return x
```

---

## 5. 并发参数对照表（重点）

| 参数 | 主要对象 | 含义 | 常见影响 |
|---|---|---|---|
| `max_concurrency` | `@daft.cls` | 限制并发实例上限 | 降低 OOM 风险，限制并发吞吐 |
| `gpus` | `@daft.cls` | 每实例 GPU 请求 | 决定可并行实例数与资源绑定 |
| `use_process` | `@daft.func/@daft.cls/@daft.method` | 进程隔离执行 | 提升隔离性，规避 GIL，增加进程序列化开销 |
| `batch_size` | `@daft.func.batch/@daft.method.batch` 等 | 每调用最大行数 | 直接影响吞吐、延迟和内存峰值 |
| `max_retries` | `@daft.func/@daft.method` | 失败重试次数 | 提升鲁棒性，增加失败任务总时长 |
| `on_failure` | `@daft.func/@daft.method` | 失败处理策略 | 决定失败是中断、置空或其他处理 |
| `repartition(n, ...)` | DataFrame | 固定分区数（任务数） | 影响分布式负载均衡、shuffle 成本 |
| `into_batches(n)` | DataFrame | 固定每批行数 | 影响算子内存峰值和局部并行粒度 |
| `max_connections` | `download()` / I/O 配置 | 下载连接并发 | 影响网络吞吐和下载阶段内存占用 |
| `max_task_backlog` | `set_runner_ray` | Ray 积压任务上限 | 限制排队压力，稳定内存和调度 |

---

## 6. I/O 并发与内存反压

文档强调：下载类算子是 OOM 高发点之一。

关键做法：

1. 降低 `download()` 相关 `max_connections`，防止大响应并发堆积。
2. 在解码/展开前使用 `into_batches()` 控制每批规模。
3. 对内存敏感 UDF 同时降低 `batch_size` 与 `max_concurrency`。

这本质是“吞吐换稳定性”的调参过程。

---

## 7. 推荐调参顺序（实践）

1. 先选 Runner：`set_runner_native()` 或 `set_runner_ray()`。
2. 选 UDF 形态：无状态优先 `func`，重初始化优先 `cls`。
3. 先调 `batch_size`（控制内存峰值），再拉 `max_concurrency`（提吞吐）。
4. 非线程安全或 Python 密集逻辑再开启 `use_process=True`。
5. I/O OOM 场景先降 `max_connections`。
6. 最后再尝试 `daft.context.set_execution_config(...)` 的实验参数。

---

## 8. 典型配置模板

### 8.1 单机稳态模板（优先稳定）

```python
import daft
from daft import DataType, Series

daft.set_runner_native()

@daft.func.batch(return_dtype=DataType.int64(), batch_size=256, use_process=False)
def f(x: Series) -> Series:
    return x

# df = df.into_batches(512).select(f(df["x"]))
```

### 8.2 Ray + GPU 吞吐模板（优先吞吐）

```python
import daft
from daft import DataType, Series

daft.set_runner_ray("ray://127.0.0.1:10001")

@daft.cls(gpus=1, max_concurrency=8, use_process=True)
class Embedder:
    def __init__(self, model_name: str):
        self.model_name = model_name

    @daft.method.batch(return_dtype=DataType.list(DataType.float32()), batch_size=64)
    def embed(self, texts: Series):
        return [[0.1, 0.2, 0.3] for _ in range(len(texts))]
```

### 8.3 I/O 密集防 OOM 模板

```python
# 思路：降低下载并发 + 减小批大小
# df = df.into_batches(200)
# df = df.with_column("bytes", df["url"].download(...))  # 使用较低 max_connections
```

---

## 9. 新旧 UDF 并发语义差异（迁移重点）

从 legacy `@daft.udf` 迁移到新 API 时：

- 旧 `concurrency` -> 新 `max_concurrency`（从“固定并发数”转为“并发上限”语义）。
- 旧 `num_gpus` -> 新 `gpus`。
- `batch_size`、`use_process` 继续保留。
- `num_cpus`、`memory_bytes` 在新 API 中无直接等价参数，通常用 `max_concurrency` 近似控制。

---

## 10. 一句话总结

Daft 的并发能力来自“Runner 选型 + 分区/批次切分 + UDF 并发参数 + I/O 连接并发”四层联动；工程上最有效的实践是先控内存（批次/连接数），再拉并发（实例数/分区数）。

---

## 11. FAQ：Native Worker 与 `max_concurrency`

### Q1：Native Runner 会在本机启动多个 worker 进程吗？

结论：默认不会以“多个 worker 进程”的方式运行；Native Runner 的核心是本机多线程并发与流式流水线执行。

- **Rust 多线程后端**：Native Runner（Swordfish）基于 Rust 实现，默认利用本机 CPU 核心并行处理任务。
- **Tokio 异步运行时**：通过 Tokio 驱动异步 I/O 与任务调度，使 I/O 与计算可重叠执行。
- **Push-based Streaming 执行**：物理计划会以算子图方式执行，算子之间通过异步通道传递批次数据，减少全量阻塞。
- **数据并行 + 流水线化**：
  - 分区/批次可以并行处理。
  - 单个批次完成一个阶段后即可进入下一阶段，不必等待全量数据完成。
- **UDF 并发控制**：
  - 新 API（仅 `@daft.cls`）使用 `max_concurrency` 控制并发实例上限（`@daft.func` 不支持此参数）。
  - 旧 API（`@daft.udf`）使用 `concurrency` 参数。
- **与 Ray 的区别**：Ray Runner 才是跨机器、worker 进程/actor 的分布式并发模型。
- **Native 的例外**：若在 Native 下给 UDF 显式设置 `use_process=True`，会引入本地子进程执行该 UDF；这是 UDF 隔离机制，不等同于 Ray worker 模型。

### Q2：`max_concurrency` 是所有 worker 的总并发上限，还是单个 worker 上限？

结论：`max_concurrency` 是全局总上限，不是单 worker 上限。

- 在 `@daft.cls` 下，它的语义是“任意时刻最多并发实例数（at most）”。
- 在 Native Runner 中，这个“全局”范围是当前单机执行环境。
- 在 Ray Runner 中，这个“全局”范围是整个 Ray 集群（所有 worker 合计）。

因此，参数语义本身不变，变化的是全局作用域边界：Native=单机，Ray=全集群。



