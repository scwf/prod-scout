# Daft User-Defined Functions (UDFs) 完整指南

Daft 提供了强大的用户自定义函数（UDF）机制，允许用户灵活地扩展数据处理能力。Daft 的 UDF 主要分为两大类：**无状态函数 (`@daft.func`)** 和 **有状态类 (`@daft.cls`)**。

本文档详细解析了 Daft 中定义 UDF 的各种方式、适用场景及代码示例。

---

## 1. 无状态函数 (`@daft.func`)

适用于无需维护状态、无需昂贵初始化（如加载大模型）的通用数据处理逻辑。

### 1.1 Row-wise Functions (默认)

这是最基础的 UDF 形式，用于处理单行数据。Daft 会自动将 Python 函数应用于每一行。

*   **适用场景**: 通用的数学运算、字符串处理、简单的逻辑判断。
*   **特点**: 输入和输出都是针对单行数据的标量。
*   **💡 类比**: 相当于 Spark/Flink 的 **`Map`** 或 SQL 中的 **`Scalar UDF`**。

**示例代码**:

```python
import daft

@daft.func
def calculate_score(priority: int, impact: float) -> float:
    """计算加权分数"""
    return priority * impact + 10.0

# 使用示例
df = daft.from_pydict({"priority": [1, 2, 3], "impact": [0.5, 1.5, 2.0]})
df = df.with_column("score", calculate_score(df["priority"], df["impact"]))
df.show()
```

### 1.2 Async Row-wise Functions (异步)

当您的处理逻辑涉及 I/O 操作（如网络请求、数据库查询）时，使用 `async` 关键字可以显著提高性能。

*   **适用场景**: 调用外部 API、抓取网页内容、数据库查询等 I/O 密集型任务。
*   **特点**: Daft 会利用 Python 的 Event Loop 并发调度这些异步任务，在单个线程内重叠 I/O 等待时间。
*   **💡 为什么需要 Async?**: 虽然 Daft 本身有并行（多进程/多节点），但普通的同步函数会阻塞 Worker 线程等待 I/O。使用 `async` 可以让单个 Worker 线程在等待网络响应时处理其他数据，极大地提高 I/O 吞吐量。

!!! warning "风险提示：并发控制"
    如果不加限制，Async 函数可能会瞬间发起成千上万个请求，导致 **IP 被封** 或 **本地连接耗尽**。
    强烈建议配合 **`asyncio.Semaphore`** 使用有状态类 (`@daft.cls`) 来控制并发度。

**示例代码 (带并发控制)**:

```python
import daft
import aiohttp
import asyncio

@daft.cls
class RateLimitedFetcher:
    def __init__(self, limit: int = 10):
        # 限制该实例内部同时进行的请求数不超过 10
        self.semaphore = asyncio.Semaphore(limit)
        
    async def __call__(self, url: str) -> str:
        async with self.semaphore:  # 获取令牌
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    return await response.text()

# 使用示例
fetcher = RateLimitedFetcher(limit=10)
df = daft.from_pydict({"url": ["https://example.com/1"] * 100})
df = df.with_column("body", fetcher(df["url"]))
```

**简单示例 (如果不需控制并发)**:

**示例代码**:

```python
import daft
import aiohttp
import asyncio

@daft.func
async def fetch_url_title(url: str) -> str:
    """异步获取网页标题"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            html = await response.text()
            # 简单提取 title 标签 (伪代码)
            return html.split("<title>")[1].split("</title>")[0]

# 使用示例
df = daft.from_pydict({"url": ["https://example.com/1", "https://example.com/2"]})
df = df.with_column("title", fetch_url_title(df["url"]))
```

### 1.3 Generator Functions (FlatMap / 1对N)

使用 `yield` 关键字的生成器函数。它允许一行输入产生多行输出（类似于 Spark/Flink 中的 FlatMap）。

*   **适用场景**: 文本分词、将数组展开为多行、数据爆炸（Explode）。
*   **特点**: 输入一行，输出零行、一行或多行。其他列的数据会自动复制（Broadcast）以匹配生成的行数。
*   **💡 类比**: 相当于 Spark/Flink 的 **`FlatMap`**。

**示例代码**:

```python
import daft
from typing import Iterator

@daft.func
def split_tags(tags_str: str) -> Iterator[str]:
    """将逗号分隔的标签字符串拆分为多行"""
    if not tags_str:
        return
    for tag in tags_str.split(","):
        yield tag.strip()

# 使用示例
df = daft.from_pydict({
    "id": [1, 2],
    "tags": ["apple, banana", "orange"]
})
# id=1 的行会变成两行：apple 和 banana
df = df.select(df["id"], split_tags(df["tags"]).alias("tag"))
df.show()
```

### 1.4 Batch Functions (批量/向量化)

使用 `@daft.func.batch` 装饰器。这种方式一次性接收和返回一批数据（通常是 `daft.Series`），而不是单行数据。

*   **适用场景**: 高性能计算，利用 NumPy、PyArrow 进行向量化运算。
*   **特点**: 极高的处理速度，避免了 Python 循环的开销。
*   **💡 类比**: 相当于 Spark 的 **`MapPartitions`** 或 **`Pandas UDF` (Vectorized)**。

**示例代码**:

```python
import daft
from daft import Series, DataType
import pyarrow.compute as pc

@daft.func.batch(return_dtype=DataType.int64())
def fast_add(a: Series, b: Series) -> Series:
    """使用 PyArrow 进行向量化加法"""
    # 转换为 PyArrow 数组进行计算
    return pc.add(a.to_arrow(), b.to_arrow())

# 使用示例
df = daft.from_pydict({"a": [1, 2, 3] * 1000, "b": [4, 5, 6] * 1000})
df = df.with_column("sum", fast_add(df["a"], df["b"]))
```

---

## 2. 有状态类 (`@daft.cls`)

适用于需要昂贵初始化操作（Initialize-once）的场景。Daft 会在每个 Worker 进程上初始化一次类实例，并在该 Worker 处理的所有行中复用该实例。

### 2.1 Standard Stateful Class (标准有状态类)

*   **适用场景**: 加载机器学习模型、建立数据库连接、加载大型查找表。
*   **特点**: `__init__` 方法只执行一次，`__call__` 方法对每一行执行。

**示例代码**:

```python
import daft

@daft.cls
class SentimentAnalyzer:
    def __init__(self, model_name: str):
        # 昂贵的初始化操作：只执行一次
        print(f"Loading model: {model_name}...")
        self.model_data = {"hello": 0.8, "bad": 0.1} # 模拟模型

    def __call__(self, text: str) -> float:
        # 对每一行数据执行
        return self.model_data.get(text, 0.5)

# 使用示例
# 初始化时传入参数
analyzer = SentimentAnalyzer("my-bert-model")
df = daft.from_pydict({"text": ["hello", "bad", "unknown"]})
df = df.with_column("sentiment", analyzer(df["text"]))
df.show()
```

### 2.2 GPU Resource Management (GPU 资源管理)

Daft 允许在定义类时声明所需的资源（如 GPU）。Daft 的调度器会自动将这些任务调度到拥有 GPU 的节点上。

*   **适用场景**: 深度学习推理（PyTorch, TensorFlow, HuggingFace）。
*   **配置**: 使用 `gpus=N` 参数。

**示例代码**:

```python
import daft

# 声明每个实例需要 1 个 GPU
@daft.cls(gpus=1)
class GPUClassifier:
    def __init__(self):
        # 这里可以安全地加载 CUDA 模型
        # import torch
        # self.model = torch.load("model.pth").cuda()
        pass

    def __call__(self, image_data):
        # return self.model(image_data)
        return "cat"

# 使用示例
classifier = GPUClassifier()
```

### 2.3 Batch Method (批量有状态方法)

结合了**状态保持**和**批量处理**的优势。这对于现代深度学习推理至关重要，因为批量推理（Batch Inference）通常比单条推理快得多。

*   **适用场景**: 高吞吐量的 AI 模型推理。
*   **特点**: 使用 `@daft.method.batch` 装饰类方法。

**示例代码**:

```python
import daft
from daft import Series, DataType

@daft.cls
class BatchInferenceModel:
    def __init__(self):
        # self.model = load_model()
        pass

    @daft.method.batch(return_dtype=DataType.string())
    def predict_batch(self, features: Series) -> Series:
        # 将输入序列转换为适合模型输入的批量格式 (如 numpy array)
        numpy_batch = features.to_arrow().to_numpy()
        
        # 执行批量推理
        # options = self.model.predict(numpy_batch)
        results = [f"pred_{x}" for x in numpy_batch] # 模拟结果
        
        return Series.from_pylist(results)

# 使用示例
model = BatchInferenceModel()
df = daft.from_pydict({"features": [1, 2, 3, 4]})
# 注意调用的是 predict_batch 方法
df = df.with_column("prediction", model.predict_batch(df["features"]))
```

---

## 3. 其他定义方式

### 3.1 `.apply()`

类似于 Pandas 的 apply。

*   **适用场景**: 快速原型开发，非常简单的单列处理。
*   **限制**: 性能较差（纯 Python 循环），无法处理多列输入。

```python
df.with_column("new_col", df["old_col"].apply(lambda x: x * 2))
```

### 3.2 Legacy `@daft.udf`

Daft 的旧版 API。

*   **注意**: 功能已被上述的新 API (`@daft.func`, `@daft.cls`) 覆盖。建议在新代码中避免使用，以确保未来的兼容性。

---

## 总结 cheat sheet

| 需求 | 推荐方法 | 关键装饰器/方法 |
| :--- | :--- | :--- |
| **通用简单逻辑** | Stateless Function | `@daft.func` |
| **API 调用 / 爬虫** | Async Function | `@daft.func` (on `async def`) |
| **文本分词 / 展开** | Generator Function | `@daft.func` (with `yield`) |
| **高性能数值计算** | Batch Function | `@daft.func.batch` |
| **AI 模型推理 (CPU/GPU)** | Stateful Class | `@daft.cls` |
| **批量 AI 推理** | Batch Method | `@daft.cls` + `@daft.method.batch` |

## 附录：大数据框架概念映射表

如果您熟悉 Spark 或 Flink，可以参考下表快速理解 Daft 的概念：

| Daft UDF 类型 | Spark 对应概念 | Flink 对应概念 | 输入->输出 |
| :--- | :--- | :--- | :--- |
| **Row-wise (`@daft.func`)** | `map()` / `udf()` | `map()` / Scalar Function | 1 -> 1 |
| **Generator (`@daft.func` yield)** | `flatMap()` / `explode()` | `flatMap()` / Table Function | 1 -> N |
| **Batch (`@daft.func.batch`)** | `mapPartitions()` / Pandas UDF | - | 1 Batch -> 1 Batch |
| **Stateful Class (`@daft.cls`)** | (无直接对应，需在 `mapPartitions` 手动实现) | RichFunction (`open()` 方法) | (有状态复用) |
