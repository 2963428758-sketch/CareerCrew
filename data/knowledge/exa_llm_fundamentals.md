# exa_llm_fundamentals 知识库（Exa 搜索聚合）


## [1] LLM 算法岗| 面试常问的LLM 八股题目汇总- MoonOut

来源: https://www.cnblogs.com/moonout/p/19702578


LLM 算法岗 | 面试常问的 LLM 八股题目汇总 - MoonOut - 博客园

# 月出兮彩云归 🌙

# LLM 算法岗 | 面试常问的 LLM 八股题目汇总

发布于 2026-03-11 15:12

根据小红书和牛客网的面经总结。

---

目前整理的答案：

- LLM 算法岗 | 八股问答（1）· Transformer 与模型架构原理
- LLM 算法岗 | 八股问答（2）· 大模型训练流程与微调技术
- LLM 算法岗 | 八股问答（3）· 强化学习与 RLHF
- LLM 算法岗 | 八股问答（7）· 多模态与主流模型架构
- LLM 算法岗 | 八股题目 · 代码手撕 · 题目汇总与解析

---

### 1. Transformer 与模型架构原理

- 请介绍 Transformer 的结构组成、各部分作用及底层原理。
- Transformer 的 forward 计算包含哪些部件？非线性由什么提供？
- Transformer 为什么能替代 RNN？核心优势是什么？
- 详细介绍 Self-Attention 机制，包括本质、数学解释、具体计算步骤，及时间复杂度。
- 为什么要用 Multi-Head Attention？切分为多头的作用是什么？
- 计算 Attention 的 Softmax 之前为什么要除以根号 \(d_k\)？
- 介绍一下 Transformer 的位置编码（Positional Encoding），还了解其他位置编码吗？
- 介绍 QKV 的计算。如果在 Transformer 中去掉 K，变成 QQV，会有什么问题？（仅考虑编码器内部）
- Transformer 是 Encoder-Decoder 架构，而 GPT 是 Decoder-only 架构，为什么会演变成这种形式？为什么生成式任务（如 GPT）通常舍弃 Encoder？
- Transformer 的 FFN 层为什么会逐渐演变成 MOE（Mixture of Experts）层？
- MOE 层的负载均衡具体是怎么做的？偏置项 b 是怎么训练的？如何保证偏置项得到变换？
- 如何降低 Transformer 的计算复杂度？为降低计算复杂度，常见的稀疏注意力变体有哪些？
- 分析一下 Transformer 训练过程中显存占用和计算复杂度。
- Self-Attention 机制在多模态对齐上是否存在瓶颈？有没有实际场景里注意力权重完全偏掉的情况？
- 如何解决梯度消失和梯度爆炸问题？
- 介绍一下 LayerNorm 和 BatchNorm 的区别？
- 在 Agent 多轮对话任务中，Attention 的局限性体现在哪些方面？
- 大模型经常一张显卡放不下。为了解决此问题，有哪些模型并行策略？

### 2. 大模型训练流程与微调技术

- 详细描述从 txt 文本预处理到 SFT 训练的全流程（包括 Tokenize、Forward、Loss 计算、参数更新）。
- Pretrain、SFT、RLHF 的区别是什么？（目标、任务定位和解决的问题）
- Pretrain 和 SFT 在优化目标上的区别是什么？
- SFT 的核心流程及数据集构建策略是什么？如何保证样本多样性和质量？
- SFT 的 Loss 是什么？若 Target 有 10 或 100 个 Token，Loss 如何计算？
- SFT 样本（含 Prompt）与预训练样本在计算 Loss 时的区别？如何屏蔽 Prompt 的 Loss？
- 手写 SFT 的 loss 计算代码（注意 shift right）。
- SFT 之后常见的 Post-Training（如 RLHF）有哪些？它们的目的有何区别？
- 为什么 SFT 之后还要做 RL？为什么偏好对齐不能直接用偏好数据做 SFT，而要用 RL？

LoRA 相关：

- 介绍一下 LoRA 的核心原理。秩 r 的选择会对模型表现产生什么影响？如何选择 rank 值？
- LoRA 是否只能嵌入 Linear 层？为什么不能插在 LayerNorm 之后？对训练稳定性有什么影响？
- LoRA 微调推理的时候要挂着 Adaptor 吗？合并 Adapter 权重时有没有遇到梯度爆炸？
- 具体说说 QLoRA 是怎么降低资源成本的？常见的量化方式有哪些？为什么选 NF4 和 FP16 组合？NF4 的分布拟合逻辑是什么？
- 训练 LoRA 模型时，如何选择冻结层？依据是什么？

其他 LLM 训练相关：

- Tokenizer 是怎么做的？有哪些实现方式？
- Embedding 是怎么做的？从 ID 到 Embedding 有哪些实现方式？
- 控制模型生成多样性的参数有哪些？如何控制？
- top-k 与 top-p 的区别？除了贪心，还有哪些生成策略？
- 介绍一下常见的优化算法优缺点。为什么 Adam 不一定最优而 SGD 最优？怎么理解分析？
- 在机器学习里，怎么处理长尾数据和多峰数据？
- 怎么解决模型的冷启动问题（新模型或新系统上线时缺乏历史数据，导致无法提供有效服务，常见于推荐系统、对话系统等）？LLM 在冷启动方面能够起到什么作用（直接加 prompt）？
- 大模型幻觉是什么？怎么缓解大模型幻觉？

### 3. 强化学习与人类对齐 (RLHF)

- 介绍一下 PPO、DPO、GRPO 的定义、结构区别、优缺点及适用场景。
- PPO 的 Clip 机制是什么？为什么公式里面 Clip 了外面还要计算一次 Mean？
- Clip 可以限制分布差异，还有哪些方法可以做到？
- PPO 和 GRPO 的结构区别，各自适用场景？
- DAPO、GSPO 具体做了什么改进？
- 介绍一下奖励函数的坍缩现象和问题。
- 多目标优化奖励函数冲突怎么处理？
- 离线强化学习和在线强化学习有什么区别？RLHF 属于哪一种？
- 为什么要用 Reference Model？为了解决什么问题？
- KL 散度公式是什么？有几种估计方法？

### 4. Agent 智能体设计与应用

- 做 Agent 有哪些框架（如 AutoGen、LangChain）？开发范式有哪些？什么情况下应该选择某个框架？
- 在 Agent 多轮对话任务中，Attention 的局限性体现在哪些方面？
- 怎么设计 Agent 的记忆系统？长期记忆如何存储？
- 如果历史记录量非常大，怎么优化查询效率？如何做记忆衰退，避免旧数据干扰新任务？
- Agent 是如何实现多步规划（Multi-step Planning）的？
- 工具调用的调度策略如何设计？是否有异常 Fallback 策略？
- 如何让多个 Agent 协同工作的？举个具体的协同机制例子。
- 如果一个 Agent 误判导致策略冲突，如何处理？
- Agent 评估体系包括哪些维度？如何衡量 Planning 能力 vs Hallucination Rate？
- 高并发查询的 Agent 系统中，如何优化召回和生成阶段的延迟？
- Prompt 自动推荐模块用了哪些优化策略？有没有尝试过 Prompt 压缩或 Embedding 表示的方式？
- 如果要做电商 Agent，应该选择哪些模态的信息作为输入（文本评论、图像、视频、购买记录等）？

### 5. RAG 检索增强生成

- 什么是 RAG？完整流程是什么？它是怎么提升生成质量的？
- 标准 RAG 有什么问题？当前 RAG 的最大瓶颈在哪？
- RAG 与传统“检索 + 模型生成”的流程有何不同？
- 如何评估一个 RAG 系统是否 Work？有哪些具体的指标或框架？
- 构建向量检索库时，如何处理时间衰减对召回的影响？
- 从数据清洗到检索服务上线的完整链路是怎么搭的？Chunk 切分的具体策略是什么？
- 知识库搭建需要动态更新时，是用全量嵌入还是增量处理？如何避免新旧文档分布不一致导致的检索偏差？
- 在 RAG+ 知识图谱的 Agent 系统中，知识图谱更新的机制是怎样的？怎样保证实时性？
- 把 RAG 做成 Agent 有什么好处？
- Embedding 模型和 Rerank 模型分别是怎么处理文本语料的？用场景举一下例子。

### 6. 推理优化、部署与工程化

- 分析 Transformer 训练过程中的显存占用和计算复杂度。
- KV Cache 是什么？为什么能极大地提升推理速度？
- 在 multi-query attention 优化中，decoder 延迟高的瓶颈可能是什么？vLLM 的 KV cache 是否会成为负担？
- 训练过程中怎么去做到对激活值的显存占用控制？有什么参数可以进行控制？（如 Gradient Checkpointing）
- 是否了解 Swift？DeepSpeed 与 Megatron 的区别是什么？
- 有没有做过模型压缩？比如在车载端或低端设备上的推理加速？
- 如果量化后理解能力下降怎么办？怎么做精度补偿？
- 在高并发查询 Agent 系统中，你会如何优化召回和生成阶段的延迟？
- 大规模 Agent 系统在多线程 / 多进程场景下的资源调度策略如何设计？
- 如果你要在 GPU 资源有限的条件下同时提供推理和微调服务，如何做资源分配和任务调度以保证时延和吞吐？
- 场景题：假如一个 Agent 推理链路包含 3 个工具 + 高频请求，系统整体延迟较高，你会如何优化？
- 部署一个 MoE 架构的 2


## [2] LLM 算法岗 | 八股问答（2）· 大模型训练流程与微调技术 - MoonOut - 博客园

来源: https://www.cnblogs.com/moonout/p/19705026


LLM 算法岗 | 八股问答（2）· 大模型训练流程与微调技术 - MoonOut - 博客园

# 月出兮彩云归 🌙

# LLM 算法岗 | 八股问答（2）· 大模型训练流程与微调技术

本博客总结了与 LLM 训练流程、微调技术相关的 LLM 八股面试题。

完整题库链接： LLM 算法岗 | 面试常问的 LLM 八股题目汇总

---

## 1. 从 txt 文本预处理到 SFT 训练的全流程

步骤详解：

文本预处理：

- 清洗原始文本，去除无关字符、HTML 标签、乱码、去重等；质量过滤：基于规则（长度、乱码率）+ 基于模型（困惑度打分）筛选；
- 统一编码和格式；可能进行句子分割或段落划分；
- 对于多轮对话数据，需结构化处理，构建 JSON / Parquet 格式，比如统一为 {"instruction": "...", "input": "...", "output": "..."} 或对话格式。

Tokenization：

- 使用分词器（如 BPE、SentencePiece）将文本转换为 token IDs，添加特殊 token（如`[BOS]`、`[EOS]`、`[PAD]`）。
- 对话模板（Chat Template）：不同模型格式不同（Llama-3、Qwen、ChatGLM 等）。

构建输入：

- `max_length`截断，将 token IDs 序列进行 padding 至统一长度，`padding="max_length"`或`padding="longest"`（batch 内动态），生成`input_ids`；
- 创建`attention_mask`标识有效 token，区分 pad token（mask=0）和真实 token（mask=1）；
- 构造`labels`，其中 prompt 部分设为忽略索引（如 -100），response 部分为对应的 token IDs。

Forward：

- 将`input_ids`和`attention_mask`输入模型，得到`logits`，形状为`[batch_size, seq_len, vocab_size]`。

Loss 计算：

- 采用交叉熵损失，通常需要 shift right：用当前 token 预测下一个 token，即取`logits[:, :-1, :]`和`labels[:, 1:]`，然后计算损失，忽略`labels`中为 -100 的位置。

参数更新：

- 反向传播计算梯度，使用优化器（如 AdamW）更新模型参数，常配合学习率调度、梯度裁剪等技巧。

## 2. Pretrain、SFT、RLHF 的区别

| 维度 | Pretrain（预训练） | SFT（监督微调） | RLHF（人类反馈强化学习） |
| --- | --- | --- | --- |
| 目标 | 学习通用语言表示和世界知识 | 学习指令遵循 + 任务格式 | 对齐人类偏好（有用、无害、诚实） |
| 数据 | 海量无标注文本（网页、书籍、代码） | 高质量指令-输出对（数十万到数百万） | 偏好对/排序数据（A > B） |
| 任务定位 | 自监督学习，next token prediction；基础模型构建 | 有监督学习，条件生成；任务适配 / 对话能力培养 | 强化学习，优化奖励函数；价值观对齐 |
| 解决问题 | "模型会说话"，从海量无标注文本中获取语言能力 | "模型听指令"，让模型理解人类意图，输出符合期望的内容 | "模型说得好"，纠正模型生成中不符合人类偏好的行为 |
| Loss | 纯交叉熵（所有 token） | 交叉熵（通常只算 answer 部分） | PPO / DPO 等（基于奖励模型） |

## 3. Pretrain 和 SFT 优化目标的区别

Pretrain：优化目标是自回归语言建模损失，即最大化整个序列中每个 token 的条件概率（通常忽略部分 token 如 mask）。学习文本的统计分布。

- 目标：$ \max_\theta \sum_{t=1}^{T} \log P_\theta(x_t | x_{<t}) $
- 特点：所有 token 都算 loss，无差别对待
- 本质：无条件的概率建模，学习 \(P(X)\)

SFT：优化目标是条件语言建模损失，即在给定指令下最大化目标回答的似然，损失仅计算 response 部分，不计算 prompt 部分。本质是让模型学会“回答问题”而非“预测所有文本”。

- 目标：$ \max_\theta \sum_{t=1}^{T} \log P_\theta(y_t | x, y_{<t}) $
- 特点：通常只计算 answer / output 部分的 loss，prompt 部分 mask 掉
- 本质：条件生成，学习 \(P(Y|X)\)，优化指令遵循能力

核心差异：Pretrain 是无条件密度估计，SFT 是条件生成，且 SFT 通过 mask prompt 实现聚焦学习（不让模型浪费容量去学 prompt 的分布）。

## 4. SFT 核心流程及数据集构建策略

核心流程：

1. 收集人工标注的（指令，回答）对。
2. 清洗数据（去重、过滤低质 / 有毒内容、格式统一）。
3. 格式化拼接指令和回答，添加角色标识（应用 Chat Template）。
4. 分词（Tokenize）、构建 labels（prompt 部分设为 -100）。
5. 微调模型（通常用较小学习率，1-3 个 epoch，lr 1e-5 ~ 5e-5，冻结部分层可选）。
6. 验证 / 评测（MT-Bench、人工评估）

数据集构建策略：

平衡：控制各类别比例，防止模型偏向某类任务。

- 难度分布：简单:中等:困难 ≈ 3:5:2，避免全是难题导致收敛慢。包含简单和复杂指令，逐步提升模型能力。
- 长度分布：短（<1k）、中（1k-4k）、长（>4k）混合，防止长度偏见。

## 5. SFT 的 Loss 及多 Token 计算

SFT 的 Loss 为交叉熵损失，计算模型对每个 token 预测的概率与真实 token 的差异。若 target 有 N 个 token，则损失是这 N 个 token 的交叉熵的平均值（或求和，通常取平均）。

实现时，通过设置`ignore_index`（如 -100）忽略非 target 部分。

具体的，假设 prompt 有 \(L_p\) 个 token，answer 有 \(L_a\) 个 token（\(L_a\) = 10 或 100）：

```
Full sequence: [P1, P2, ..., P_Lp, A1, A2, ..., A_La]
               ↑ prompt部分        ↑ answer部分（只算这些的loss）

```

计算步骤：

1. Forward 得到 logits：`[batch, seq_len, vocab_size]`
2. Shift right：logits 去掉最后一个，labels 去掉第一个
3. Mask prompt：将 prompt 对应位置的 labels 设为`-100`（ignore_index）
4. 只在 answer 部分计算 CE Loss

公式：$$ \mathcal{L} = -\frac{1}{L_a} \sum_{t=L_p+1}^{L_p+L_a} \log P_\theta(a_t | x, a_{<t}) $$

注意这个 loss -平均到每个 token**，最终 loss 是标量（mean over valid tokens）。序列长只是求和的项多，但除的也是 \(L_a\)，所以不同长度样本的 loss 量级可比。

（所以在这个角度来说，SFT 是 offline 的，SFT 是 behavior cloning；RL PPO GRPO 等是 online 的）

交叉熵损失公式：

二分类交叉熵损失：

\[L = -\left[ y \cdot \log(p) + (1 - y) \cdot \log(1 - p) \right] \]

其中：

- $ y \in {0, 1} $ 是真实标签
- $ p \in (0, 1) $ 是模型预测为正类的概率

多分类交叉熵损失：

\[L = -\sum_{i=1}^{C} y_i \cdot \log(p_i) \]

其中：

- $ C $ 是类别数
- $ y_i $ 是真实标签的 one-hot 编码
- $ p_i $ 是模型预测为第 $ i $ 类的概率

## 6. SFT 与预训练样本 Loss 计算区别及屏蔽方法

- 区别：预训练样本对整个序列计算损失（所有 token 参与），SFT 仅对response部分计算损失。
- 屏蔽方法：在`labels`中将 prompt 对应位置设为特定的忽略索引（如 -100），损失函数自动忽略这些位置。

## 7. SFT Loss 计算代码（含 shift right）

```
import torch
import torch.nn.functional as F
from torch.nn import CrossEntropyLoss

def compute_sft_loss(logits, labels,


## [3] 使用 NVFP4 KV 缓存优化大批次与长上下文推理 - NVIDIA 技术博客

来源: https://developer.nvidia.cn/blog/optimizing-inference-for-long-context-and-large-batch-sizes-with-nvfp4-kv-cache/


使用 NVFP4 KV 缓存优化大批次与长上下文推理 - NVIDIA 技术博客

Related Resources

智能体/生成式 AI

English中文

# 使用 NVFP4 KV 缓存优化大批次与长上下文推理

量化是大规模推理中的关键手段之一。通过降低权重、激活值和KV缓存的精度，可以有效减少内存占用和计算开销，从而显著提升推理吞吐量、降低延迟，并支持更长的上下文长度。

本博客介绍了 NVFP4 KV 缓存量化技术，这是一种专为 NVIDIA Blackwell 架构 GPU 设计的新型 KV 格式，可显著提升推理性能。NVFP4 能将 KV 缓存的显存占用最多降低 50%，有效实现上下文容量翻倍，从而支持更大的批处理规模、更长的序列长度以及更高的缓存命中率。在代码生成、知识问答和长上下文基准测试中，该技术带来的精度损失约为 1%。

在接下来的章节中，我们将探讨这一优化如何为推理工作负载带来显著收益，并进一步强化 NVIDIA 协同设计堆栈的整体优势。

## 什么是 KV 缓存？

大语言模型（LLM）依赖于自回归机制，逐个生成token，每一步都基于之前所有已生成的token进行预测。这一机制能够充分利用序列的完整上下文信息，正是LLM在自然语言建模任务中表现优异的关键所在。然而，这种生成方式也带来了显著的计算效率问题：每次生成新token时，模型都会重复计算此前所有token对应的注意力投影（即键值张量），造成计算资源的冗余消耗。

下图1展示了使用与不使用KV缓存时注意力计算的简化示意图。由于注意力机制中先前的token无法关注未来的token，其注意力值会被屏蔽，因此所有历史token（包括原始输入序列）对应的键值向量始终保持不变。这意味着在生成每个新token时，若重复计算这些固定的键值向量并重新执行相关的矩阵乘加（MMA）运算，将造成不必要的计算开销，是一种冗余操作。 ```
# configure fp8 quantization and fp4 for KV cache
quant_cfg = mtq.FP8_DEFAULT_CFG
quant_cfg["quant_cfg"].update(mtq.NVFP4_KV_CFG["quant_cfg"])

# Define forward loop for calibration with
def forward_loop(model):
    for data in calib_set:
        model(data)

# Quantize the modelmodel = mtq.quantize(model, quant_cfg, forward_loop)

# Model is ready for Post Training Quantization (PTQ) deployment

# (Optional) Quantization-aware training (QAT)
Train quantized model further for improving accuracy
# adjust training parameters, e.g., lr, schedule, epochs
# HuggingFace and Megatron models supported
train(model, train_loader, optimizer, scheduler, ...)

```


## [4] 大模型面试100问02：训练与优化篇

来源: https://www.80aj.com/2026/01/04/llm-interview-training-optimization/


大模型面试100问02：训练与优化篇

 



#大模型面试100问

目录

## TL;DR

全参数微调一个7B模型要14GB显存，65B模型要130GB——普通人根本玩不起。但LoRA只需要0.1%的参数，QLoRA更狠，单张24GB显卡就能训65B模型。本文从10个高频面试题入手，带你搞懂大模型训练的核心技术：LoRA为什么有效、RLHF和DPO怎么选、并行策略如何搭配、训练稳定性怎么保证。读完这篇，你能回答”为什么QLoRA用NF4量化”、”PPO和DPO的本质区别是什么”这种深度问题。

---

## 一、LLM训练的三阶段：预训练 → SFT → RLHF

### 三阶段流程

```
阶段1: 预训练 (Pretraining)
[海量无标注文本] → [下一词预测] → [基座模型]

阶段2: 监督微调 (SFT)
[高质量指令数据] → [监督学习] → [指令遵循模型]

阶段3: 人类反馈强化学习 (RLHF)
[人类偏好数据] → [强化学习] → [对齐模型]

```

### 各阶段详解

| 阶段 | 数据量 | 目标 | 成本 |
| --- | --- | --- | --- |
| 预训练 | 数万亿tokens | 学习语言知识 | 极高（数百万美元） |
| SFT | 1万-10万条 | 学会遵循指令 | 中等 |
| RLHF | 3万-10万条偏好对 | 对齐人类价值观 | 高（需要4个模型） |

### InstructGPT的数据规模

- SFT阶段：~13K条高质量指令数据
- RM阶段：~33K条人类偏好标注
- PPO阶段：持续优化

关键洞察：预训练是”读万卷书”，SFT是”学会答题格式”，RLHF是”学会讨人喜欢”。

参考资料：InstructGPT论文 (arXiv:2203.02155)

---

## 二、并行策略对比：数据并行 vs 模型并行 vs 管道并行 vs ZeRO

### 四种并行策略

#### 1. 数据并行 (Data Parallelism, DP)

原理：每个GPU持有完整模型副本，处理不同的数据batch

```
GPU 1: 模型副本1 + Batch 1
GPU 2: 模型副本2 + Batch 2
GPU 3: 模型副本3 + Batch 3
→ 梯度同步 → 参数更新

```

优势：实现简单，通信开销小 劣势：模型必须能放进单GPU显存

#### 2. 模型并行 (Model Parallelism, MP)

原理：把模型切分到多个GPU

张量并行（Tensor Parallelism）：切分单层内的矩阵

```
Attention层: GPU1处理前半部分头，GPU2处理后半部分头

```

流水线并行（Pipeline Parallelism）：按层切分

```
GPU 1: Layer 1-10
GPU 2: Layer 11-20
GPU 3: Layer 21-30

```

优势：能训练超大模型 劣势：通信开销大，GPU利用率低（流水线气泡）

#### 3. ZeRO (Zero Redundancy Optimizer)

核心思想：消除数据并行中的冗余存储

| ZeRO阶段 | 分片内容 | 显存节约 | 通信开销 |
| --- | --- | --- | --- |
| ZeRO-1 | 优化器状态 | 4倍 | 最低 |
| ZeRO-2 | 优化器+梯度 | 8倍 | 中等 |
| ZeRO-3 | 优化器+梯度+参数 | N倍（N=GPU数） | 最高 |

实战建议： – 单机多卡：ZeRO-2 – 多机多卡：ZeRO-3 – 显存极度受限：ZeRO-3 + CPU Offload

参考资料：ZeRO论文 (arXiv:1910.02054)、DeepSpeed官方文档

---

## 三、LoRA原理：为什么低秩矩阵能有效微调？

### 核心思想

假设：预训练模型已经学到了丰富的知识，微调时的参数更新是低秩的（可以用低秩矩阵近似）。

### 数学表达

原始全参数微调：

```
W' = W + ΔW  （ΔW是全秩矩阵）

```

LoRA微调：

```
W' = W + BA  （B和A是低秩矩阵）
其中 B ∈ R^(d×r), A ∈ R^(r×k), r << min(d,k)

```

### 参数量对比

假设原始权重矩阵是 4096×4096： – 全参数微调：16,777,216个参数 – LoRA (r=16)：4096×16 + 16×4096 = 131,072个参数（减少99.2%）

### 为什么有效？

1. 低秩假设成立：实验证明微调时的参数更新确实是低秩的
2. 保留预训练知识：冻结原始权重W，只训练BA
3. 推理时无开销：可以把BA合并到W中

生活比喻：全参数微调像重新装修整个房子，LoRA像只换家具——效果差不多，但成本低得多。

参考资料：LoRA论文 (arXiv:2106.09685)

---

## 四、LoRA vs QLoRA vs 全参数微调

### 显存占用对比

| 方法 | 7B模型显存 | 65B模型显存 | 可训练参数 | 性能 |
| --- | --- | --- | --- | --- |
| 全参数微调(FP16) | ~14GB | >130GB | 100% | 100% |
| LoRA (FP16基座) | ~20GB | ~100GB | 0.1%-1% | 98-99% |
| QLoRA (4-bit基座) | ~8-10GB | ~48GB | 0.1%-1% | 97-99% |

### QLoRA的三大创新（NeurIPS 2023）

#### 1. 4-bit NormalFloat (NF4)

核心思想：针对正态分布权重设计的量化数据类型

为什么不用INT4： – 模型权重通常服从正态分布 – NF4在[-1, 1]区间内分布更密集 – 信息理论上对正态分布最优

#### 2. Double Quantization

原理：量化量化常数本身

```
原始：每64个参数共享1个FP32量化常数 = 0.5 bits/参数
优化：量化常数也用8-bit量化 = 0.127 bits/参数
节省：每参数节省0.37 bits

```

#### 3. Paged Optimizers

原理：使用NVIDIA统一内存管理内存峰值，避免OOM

### 性能验证

Guanaco模型（QLoRA训练的LLaMA 65B）： – 达到ChatGPT 99.3%性能水平 – 单GPU 24小时完成训练 – 显存占用仅48GB

参考资料：QLoRA论文 (arXiv:2305.14314)

---

## 五、RLHF详解：PPO算法在对齐中的作用

### RLHF三阶段流程

| 阶段 | 输入 | 输出 | 数据量 |
| --- | --- | --- | --- |
| 1. SFT | 指令-回复对 | 指令遵循模型 | ~13K |
| 2. RM训练 | 回复排序对 | 奖励模型 | ~33K |
| 3. PPO优化 | Prompt | 对齐模型 | 持续 |

### PPO目标函数

```
L(φ) = E[r_θ(x,y) - β·KL(π_φ(y|x) || π_SFT(y|x))]

```

三个关键组件： – r_θ(x,y)：奖励模型评分（人类偏好代理） – KL惩罚：防止模型偏离原始SFT模型太远 – β：KL惩罚系数（平衡探索与保守）

### 为什么需要4个模型？

1. Policy Model：正在训练的模型
2. Reference Policy：SFT模型副本（计算KL散度）
3. Reward Model：预测人类偏好
4. Value Function：估计状态价值（PPO算法需要）

内存需求：训练7B模型需要约80GB显存（4个模型×20GB）

参考资料：InstructGPT论文 (arXiv:2203.02155)

---

## 六、DPO vs PPO：哪个更适合对齐？

### 核心区别

| 维度 | PPO | DPO |
| --- | --- | --- |
| 是否需要RM | 需要训练奖励模型 | 不需要 |
| 训练复杂度 | 高（4个模型） | 低（1个模型） |
| 稳定性 | 需要调参 | 更稳定 |
| 性能 | 理论上限更高 | 接近PPO |

### DPO的核心创新

直接优化偏好：跳过奖励模型，直接从偏好数据学习

目标函数：

```
L(π) = -E[log σ(β log π(y_w|x)/π_ref(y_w|x) - β log π(y_l|x)/π_ref(y_l|x))]

```

其中 y_w 是偏好回复，y_l 是非偏好回复

### 2025年共识

DPO适用场景： – 资源受限（单GPU可训练） – 快速迭代 – 偏好数据充足

PPO适用场景： – 追求极致性能 – 有充足计算资源 – 需要在线学习

参考资料：DPO论文 (arXiv:2305.18290)

---

## 七、知识蒸馏在LLM中的应用

### 核心思想

Teacher-Student框架：用大模型（Teacher）的知识训练小模型（S
