# exa_java_llm 知识库（Exa 搜索聚合）


## [1] Spring AI 与 LangChain4j 从入门到精通：Java 后端开发者的 AI 实战手册Java AI 开发 - 掘金

来源: https://juejin.cn/post/7619885691574845482


Spring AI 与 LangChain4j 从入门到精通：Java 后端开发者的 AI 实战手册Java AI 开发 - 掘金

# Spring AI 与 LangChain4j 从入门到精通：Java 后端开发者的 AI 实战手册

2026-03-23 12 阅读14分钟

## 前言：Java AI 开发的新时代

### 为什么需要这份手册？

在 2026 年的今天，生成式人工智能已经不再是实验室里的玩具，而是企业级应用的核心竞争力。作为 Java 后端开发者，你可能已经感受到了来自 Python 生态的压力——LangChain、LlamaIndex 等框架让 Python 开发者能够快速构建智能应用，而 Java 开发者却常常感到无从下手。

然而，情况已经彻底改变。Spring AI 和 LangChain4j 这两个框架的出现，标志着 Java 生态正式进入了 AI 开发的黄金时代。根据最新的市场调研，超过 75% 的企业级 AI 应用正在采用 Java 技术栈构建，这得益于 Java 在稳定性、可维护性和生态系统方面的传统优势。

本手册专为以下人群设计：

- 初学者：对 AI 开发感兴趣但不知从何入手的 Java 开发者
- Spring AI 用户：已经使用 Spring AI 但希望深入理解最佳实践的开发者
- LangChain4j 用户：希望系统掌握 LangChain4j 高级特性的开发者
- 架构师和技术负责人：需要在企业中规划和落地 AI 解决方案的技术决策者

## 第一篇：基础篇

### 第 1 章：AI 开发基础概念与大模型原理

#### 1.1 大语言模型（LLM）基础

##### 1.1.1 什么是大语言模型？

大语言模型（Large Language Model, LLM）是一种基于深度学习的人工智能模型，通过在海量文本数据上进行训练，能够理解、生成和处理自然语言。截至 2026 年，主流的 LLM 包括：

- GPT 系列（OpenAI）：GPT-5.4
- Claude 系列（Anthropic）：Claude 4.6
- Gemini 系列（Google）：Gemini
- 通义千问系列（阿里云）：Qwen
- 开源模型：Llama

##### 1.1.2 LLM 的工作原理

LLM 的核心是 Transformer 架构，其工作原理可以简化为以下步骤：

1. 分词（Tokenization）：将输入文本切分成 token（可以是单词、子词或字符）
2. 嵌入（Embedding）：将每个 token 转换为高维向量表示
3. 注意力机制（Attention）：计算 token 之间的关联权重
4. 前馈网络（Feed-forward）：进行非线性变换
5. 输出预测：生成下一个 token 的概率分布

```
// 概念示例：Token 化过程
String input = "Hello, world!";
// Tokenizer 会将上述文本转换为：["Hello", ",", " world", "!"]
// 每个 token 对应一个唯一的 ID

```

##### 1.1.3 关键概念解析

Token（令牌）

- LLM 处理文本的基本单位
- 英文中约 1 token ≈ 4 个字符或 0.75 个单词
- 中文中 1 个汉字通常对应 1-2 个 token
- 模型的上下文窗口以 token 数量衡量

Context Window（上下文窗口）

- 模型一次能处理的 maximum token 数量
- 包括输入 prompt 和输出 response 的总和
- 超出限制会导致信息丢失或错误

Temperature（温度）

- 控制输出随机性的参数（0-2 之间）
- Temperature = 0：确定性输出，总是选择概率最高的 token
- Temperature = 1：标准随机性
- Temperature > 1：增加创造性，但可能降低连贯性

Top-p / Nucleus Sampling

- 另一种控制随机性的方法
- 只从累积概率达到 p 的最小 token 集合中采样
- 通常与 temperature 配合使用

#### 1.2 AI 应用开发范式

##### 1.2.1 Prompt Engineering（提示工程）

提示工程是通过精心设计输入 prompt 来引导 LLM 产生期望输出的艺术和科学。核心技巧包括：

Zero-shot Prompting

```
直接提问，不提供示例：
"请解释量子纠缠的概念。"

```

Few-shot Prompting

```
提供少量示例：
"将以下句子翻译成法语：
English: Hello, how are you? -> French: Bonjour, comment allez-vous?
English: Thank you very much. -> French: Merci beaucoup.
English: Good morning! -> French:"

```

Chain-of-Thought (CoT)

```
引导模型逐步推理：
"问题：小明有 5 个苹果，他给了小红 2 个，又买了 3 个，现在有多少个？
让我们一步步思考：
1. 小明最初有 5 个苹果
2. 给了小红 2 个后，剩下 5 - 2 = 3 个
3. 又买了 3 个，现在有 3 + 3 = 6 个
答案：6 个"

```

System Message（系统消息）

```
设置模型的行为准则：
"你是一个专业的医疗助手。请提供准确、安全的医疗建议，
但始终提醒用户咨询专业医生。"

```

##### 1.2.2 RAG（检索增强生成）

RAG 是解决 LLM 知识滞后和幻觉问题的关键技术：

```
用户查询 → 查询向量化 → 向量数据库检索 → 相关文档片段 
→ 构建增强 prompt → LLM 生成 → 最终回答

```

RAG 的优势：

- 实时知识更新（无需重新训练模型）
- 减少幻觉（基于真实文档生成）
- 可追溯性（提供信息来源）
- 成本效益（比微调更经济）

##### 1.2.3 Function Calling（函数调用）

Function Calling 让 LLM 能够调用外部工具和 API：

```
用户请求 → LLM 识别需要调用工具 → 生成工具调用参数 
→ 执行工具 → 返回结果给 LLM → LLM 生成最终响应

```

典型应用场景：

- 数据库查询
- API 调用
- 代码执行
- 文件操作
- 第三方服务集成

##### 1.2.4 Agent（智能代理）

Agent 是能够自主规划、执行任务并与环境交互的智能系统：

```
目标 → 规划 → 执行动作 → 观察结果 → 调整策略 → 重复直到完成

```

Agent 的核心能力：

- 任务分解与规划
- 工具使用
- 记忆管理
- 自我反思与修正

#### 1.3 Java AI 开发生态概览

##### 1.3.1 为什么选择 Java？

尽管 Python 在 AI 研究领域占据主导地位，但在企业级应用开发中，Java 具有独特优势：

1. 成熟的生态系统：Spring、Hibernate 等成熟框架
2. 高性能：JVM 优化、并发处理能力
3. 类型安全：编译时检查，减少运行时错误
4. 可维护性：清晰的代码结构，便于团队协作
5. 企业级支持：长期支持版本、商业支持选项

##### 1.3.2 Spring AI 与 LangChain4j 的定位

Spring AI

- 由 Spring 官方团队开发
- 深度集成 Spring 生态系统
- 强调约定优于配置
- 适合 Spring Boot 项目快速集成

LangChain4j

- LangChain 的 Java 实现
- 高度灵活和可扩展
- 丰富的组件和工具
- 适合复杂 AI 应用定制开发

---

### 第 2 章：Spring AI 快速入门

#### 2.1 Spring AI 简介

##### 2.1.1 什么是 Spring AI？

Spring AI 是由 Spring 官方团队（现属 Broadcom）主导开发的开源项目，旨在为 Java/Spring 生态系统提供一个统一、模块化、企业级友好的 AI 应用开发框架。它让开发者能够像使用 RestTemplate 或 WebClient 一样，以惯用的 Spring 风格集成大语言模型（LLM）、向量数据库、RAG、Function Calling 等现代 AI 能力。

核心特性（2026 年 v1.0.2 版本）：

- 统一的 ChatClient API
- 自动配置和 Starter 依赖
- 流式响应支持
- 结构化输出
- 向量存储抽象
- 函数调用框架
- 多模态支持（图像、音频）
- Micrometer 监控集成

##### 2.1.2 Spring AI 的设计哲学

1. Spring 风格：遵循 Spring 的设计模式，如依赖注入、自动配置
2. 可移植性：轻松切换不同的 LLM 提供商
3. 模块化：按需引入功能模块
4. 生产就绪：内置监控、日志、错误处理等企业级特性

#### 2.2 环境搭建

##


## [2] 构建基于Java的AI智能体：使用LangChain4j与Spring AI实现RAG应用-阿里云开发者社区

来源: https://developer.aliyun.com/article/1683341


构建基于Java的AI智能体：使用LangChain4j与Spring AI实现RAG应用-阿里云开发者社区

# 构建基于Java的AI智能体：使用LangChain4j与Spring AI实现RAG应用

简介： 当大模型需要处理私有、实时的数据时，检索增强生成（RAG）技术成为了核心解决方案。本文深入探讨如何在Java生态中构建具备RAG能力的AI智能体。我们将介绍新兴的Spring AI项目与成熟的LangChain4j框架，详细演示如何从零开始构建一个能够查询私有知识库的智能问答系统。内容涵盖文档加载与分块、向量数据库集成、语义检索以及与大模型的最终合成，并提供完整的代码实现，为Java开发者开启构建复杂AI智能体的大门。

一、 引言：从调用API到构建智能体单纯调用大模型API只能解决通用问题。真正的企业级AI应用需要模型能够理解和处理外部知识，如公司内部文档、数据库记录等。这就是AI智能体的用武之地——它能感知环境、使用工具（如数据库）、并执行复杂任务。

RAG是构建此类智能体的关键技术栈。其核心思想是：在向大模型提问前，先从私有知识库中检索出最相关的信息片段，并将其作为上下文与问题一同提交给模型，从而得到基于特定知识的精准回答。

本文将对比介绍两个Java领域的AI框架：Spring AI（Spring官方新项目，提供抽象层）和LangChain4j（灵感源于Python的LangChain，功能丰富），并分别展示如何用它们实现RAG流水线。

二、 技术选型与项目初始化

1. 框架简介

Spring AI（选学）：致力于为AI应用开发提供熟悉的Spring范式（如AIClient抽象、PromptTemplate）。目前仍在早期阶段，但背靠Spring生态，前景可观。

LangChain4j（主打）：一个功能强大、设计优雅的Java库，提供了大量现成的组件（文档加载器、工具、链），用于构建AI应用，是目前Java生态中最接近Python LangChain成熟度的选择。

1. 项目依赖

本例我们以LangChain4j为主进行构建。在pom.xml中引入以下依赖：

xml

0.29.0

org.springframework.boot spring-boot-starter-web

```
<!-- LangChain4j 核心 -->
<dependency>
    <groupId>dev.langchain4j</groupId>
    <artifactId>langchain4j</artifactId>
    <version>${langchain4j.version}</version>
</dependency>

<!-- LangChain4j 用于OpenAI集成 -->
<dependency>
    <groupId>dev.langchain4j</groupId>
    <artifactId>langchain4j-open-ai</artifactId>
    <version>${langchain4j.version}</version>
</dependency>

<!-- LangChain4j 本地向量库（暂存嵌入向量） -->
<dependency>
    <groupId>dev.langchain4j</groupId>
    <artifactId>langchain4j-embeddings-all-minilm-l6-v2</artifactId>
    <version>${langchain4j.version}</version>
</dependency>

<!-- 用于从文件系统加载文档 -->
<dependency>
    <groupId>dev.langchain4j</groupId>
    <artifactId>langchain4j-document-parser-apache-poi</artifactId>
    <version>${langchain4j.version}</version>
</dependency>

```

1. 配置信息（application.yml）

yamllangchain4j: openai: chat-model: api-key: ${OPENAI_API_KEY} model-name: "gpt-3.5-turbo" embedding-model: api-key: ${OPENAI_API_KEY} model-name: "text-embedding-ada-002"

# 知识库文档路径

app: knowledge-base-path: "./knowledge-base"三、 核心实现：四步构建RAG流水线一个完整的RAG系统包含四个关键步骤：文档摄入、向量化与存储、检索和生成。

1. 文档摄入与分块（Ingestion）

首先，我们需要将原始文档（如PDF、Word、TXT）加载进来，并切割成适合处理的小片段（chunks）。

javaimport dev.langchain4j.data.document.Document;import dev.langchain4j.data.document.DocumentParser;import dev.langchain4j.data.document.DocumentSplitter;import dev.langchain4j.data.document.loader.FileSystemDocumentLoader;import dev.langchain4j.data.document.parser.TextDocumentParser;import dev.langchain4j.data.document.splitter.DocumentSplitters;import dev.langchain4j.data.segment.TextSegment;import dev.langchain4j.model.embedding.EmbeddingModel;import dev.langchain4j.store.embedding.EmbeddingStore;import dev.langchain4j.store.embedding.EmbeddingStoreIngestor;import dev.langchain4j.store.embedding.inmemory.InMemoryEmbeddingStore;import org.springframework.context.annotation.Bean;import org.springframework.context.annotation.Configuration;import java.nio.file.Paths;import java.util.List;

@Configurationpublic class DocumentIngestionConfig {

```
@Bean
public EmbeddingStore<TextSegment> embeddingStore() {
    // 使用内存向量库作为示例。生产环境可换为ChromaDB、PgVector等持久化方案。
    return new InMemoryEmbeddingStore<>();
}

@Bean
public EmbeddingStoreIngestor embeddingStoreIngestor(EmbeddingStore<TextSegment> embeddingStore, EmbeddingModel embeddingModel) {
    // EmbeddingStoreIngestor 是一个工具类，封装了分块、向量化、存储的流水线
    return EmbeddingStoreIngestor.builder()
            .documentSplitter(DocumentSplitters.recursive(500, 100)) // 递归分块，最大500字符，重叠100字符
            .embeddingModel(embeddingModel)
            .embeddingStore(embeddingStore)
            .build();
}

// 应用启动时加载知识库的Bean
@Bean
public Boolean loadKnowledgeBase(EmbeddingStoreIngestor ingestor, @Value("${app.knowledge-base-path}") String path) {
    List<Document> documents = FileSystemDocumentLoader.loadDocuments(Paths.get(path), new TextDocumentParser());
    ingestor.ingest(documents);
    System.out.println("知识库文档加载完毕！");
    return true;
}

```

}

1. 创建AI服务（智能体）

接下


## [3] 使用LangChain4j构建Java AI智能体：让大模型学会使用工具-阿里云开发者社区

来源: https://developer.aliyun.com/article/1683612


使用LangChain4j构建Java AI智能体：让大模型学会使用工具-阿里云开发者社区

# 使用LangChain4j构建Java AI智能体：让大模型学会使用工具

简介： AI智能体是大模型技术的重要演进方向，它使模型能够主动使用工具、与环境交互，以完成复杂任务。本文详细介绍如何在Java应用中，借助LangChain4j框架构建一个具备工具使用能力的AI智能体。我们将创建一个能够进行数学计算和实时信息查询的智能体，涵盖工具定义、智能体组装、记忆管理以及Spring Boot集成等关键步骤，并展示如何通过简单的对话界面与智能体交互。

一、 引言：从被动问答到主动工具使用大模型在知识问答和文本生成方面表现出色，但在处理实时信息、精确计算或访问私有系统时存在局限。AI智能体通过赋予模型使用工具的能力，突破了这一限制。例如，当用户询问“今天北京的天气怎么样？”时，智能体可以自动调用天气查询工具，获取实时天气并生成回答。

在Java生态中，LangChain4j提供了强大的智能体构建能力。通过将工具（Tools）与模型（Model）结合，并引入推理逻辑，我们可以创建出能够自主规划、执行动作的AI应用。

二、 项目搭建与依赖配置

1. 项目依赖

我们使用Spring Boot和LangChain4j来构建智能体。在pom.xml中引入以下依赖：

xml

0.29.0

org.springframework.boot spring-boot-starter-web

```
<!-- LangChain4j 核心 -->
<dependency>
    <groupId>dev.langchain4j</groupId>
    <artifactId>langchain4j</artifactId>
    <version>${langchain4j.version}</version>
</dependency>

<!-- LangChain4j 用于OpenAI集成 -->
<dependency>
    <groupId>dev.langchain4j</groupId>
    <artifactId>langchain4j-open-ai</artifactId>
    <version>${langchain4j.version}</version>
</dependency>

<!-- 用于工具调用（例如：HTTP请求） -->
<dependency>
    <groupId>dev.langchain4j</groupId>
    <artifactId>langchain4j-tool-spring</artifactId>
    <version>${langchain4j.version}</version>
</dependency>

<!-- Spring Boot Configuration Processor -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-configuration-processor</artifactId>
    <optional>true</optional>
</dependency>

```

1. 配置信息（application.yml）

yamllangchain4j: openai: chat-model: api-key: ${OPENAI_API_KEY} model-name: "gpt-3.5-turbo" # 或 "gpt-4"三、 核心实现：定义工具与组装智能体

1. 定义工具（Tools）

工具是智能体与环境交互的接口。我们定义两个工具：一个计算器和一个网络搜索工具。

javaimport org.springframework.stereotype.Component;import dev.langchain4j.agent.tool.Tool;import org.springframework.web.client.RestTemplate;import java.util.Map;

@Componentpublic class CalculatorTool {

```
@Tool("用于计算两个数字的加法、减法、乘法和除法")
public double calculate(double a, double b, String operator) {
    switch (operator) {
        case "+": return a + b;
        case "-": return a - b;
        case "*": return a * b;
        case "/": 
            if (b == 0) throw new IllegalArgumentException("除数不能为零");
            return a / b;
        default: throw new IllegalArgumentException("不支持的操作符: " + operator);
    }
}

```

}java@Componentpublic class WebSearchTool {

```
private final RestTemplate restTemplate = new RestTemplate();

@Tool("在互联网上搜索实时信息，例如当前新闻、天气等")
public String searchWeb(String query) {
    // 这里我们使用一个模拟的搜索API，实际应用中可以使用SerpApi、DuckDuckGo等
    // 为了演示，我们返回一个固定的字符串，实际中应该调用真实的搜索API
    return "根据搜索查询'" + query + "'，这里是模拟的搜索结果：今天北京晴，气温20-25摄氏度。";
}

```

}

1. 组装智能体

我们使用LangChain4j的AiServices来组装智能体，将工具和模型结合起来。

javaimport dev.langchain4j.service.AiServices;import dev.langchain4j.service.SystemMessage;import dev.langchain4j.service.UserMessage;import org.springframework.context.annotation.Bean;import org.springframework.context.annotation.Configuration;

// 定义智能体接口interface Assistant { String chat(String userMessage);}

@Configurationpublic class AgentConfiguration {

```
@Bean
public Assistant assistant(CalculatorTool calculatorTool, WebSearchTool webSearchTool) {
    return AiServices.builder(Assistant.class)
            .chatLanguageModel(OpenAiChatModel.builder()
                    .apiKey(System.getenv("OPENAI_API_KEY"))
                    .modelName("gpt-3.5-turbo")
                    .temperature(0.1) // 降低随机性，使工具调用更稳定
                    .build())
            .tools(calculatorTool, webSearchTool)
            .build();
}

```

}

1. 创建REST控制器

javaimport org.springframework.web.bind.annotation.*;

@RestController@RequestMapping("/api/agent")public class AgentController {

```
private final Assistant assistant;

public AgentController(Assistant assistant) {
    this.assistant = assistant;
}

@PostMapping("/chat")
public String chat(@RequestBody String userMessage) {
    return assistant.chat(userMessage);
}

```

}四、 测试与进阶功能

1. 测试智能体

启动应用后，我们可以通过curl或Postman发送请求：

bashcurl -X POST http://lo


## [4] Java 微服务AI 集成：LangChain4j 与SpringAI-腾讯云开发者社区

来源: https://cloud.tencent.com/developer/article/2654441


Java 微服务 AI 集成：LangChain4j 与 SpringAI-腾讯云开发者社区-腾讯云

## Java 微服务 AI 集成：LangChain4j 与 SpringAI

关注作者

登录/注册

学习

活动

专区

圈层

工具

文章/答案/技术大牛搜索

搜索关闭

发布

果酱带你啃java

社区首页>专栏>Java 微服务 AI 集成：LangChain4j 与 SpringAI

# Java 微服务 AI 集成：LangChain4j 与 SpringAI

果酱带你啃java

关注

发布于 2026-04-14 12:34:51

发布于 2026-04-14 12:34:51

6310

举报

### 引言：AI 驱动的 Java 微服务新纪元

在大语言模型 (LLM) 技术爆发的今天，将 AI 能力集成到 Java 微服务架构中已成为企业数字化转型的关键路径。根据 Gartner 最新报告，到 2025 年，75% 的企业应用将嵌入生成式 AI 功能，而 Java 作为企业级应用的主流开发语言，亟需成熟的框架支持 AI 集成。

本文聚焦当前最受关注的两个 Java AI 集成框架：LangChain4j 和 SpringAI，通过实战对比的方式，为 Java 开发者提供从入门到精通的 AI 集成指南。无论你是希望为现有微服务添加智能问答功能，还是计划构建全新的 AI 驱动型应用，本文都将为你提供权威、实用的技术参考。

### 一、框架全景解析：LangChain4j 与 SpringAI 核心架构

#### 1.1 框架起源与定位

LangChain4j：由 LangChain 社区推出的 Java 版本实现，旨在为 Java 开发者提供与 Python 版 LangChain 相似的功能体验。官方定位为 "Java ecosystem for working with LLMs"，专注于提供灵活的 LLM 交互抽象和链式调用能力（来源：LangChain4j 官方文档）。

SpringAI：Spring 生态官方推出的 AI 集成框架，定位为 "Apply AI principles to Spring applications"，致力于将 AI 能力无缝融入 Spring 生态，提供与 Spring Boot、Spring Cloud 等组件的自然集成（来源：SpringAI 官方 GitHub 仓库）。

#### 1.2 核心架构对比

#### 1.3 生态系统与集成能力

LangChain4j 的优势在于：

- 与主流 LLM 提供商的广泛兼容性
- 灵活的链式处理机制
- 丰富的记忆实现策略
- 轻量级设计，可集成到任何 Java 应用

SpringAI 的优势在于：

- 与 Spring 生态（Spring Boot、Spring Cloud 等）深度集成
- 基于 Spring 的依赖注入和自动配置机制
- 统一的客户端抽象，简化多模型切换
- 与 Spring Data 等组件的自然融合

### 二、环境搭建：从零开始的 AI 集成准备

#### 2.1 开发环境要求

- JDK 17+（推荐 Amazon Corretto 17 或 Oracle JDK 17）
- Maven 3.8 + 或 Gradle 7.5+
- Spring Boot 3.2+（如使用 Spring 生态）
- 一个或多个 LLM API 密钥（如 OpenAI、Anthropic 等）

#### 2.2 项目初始化与依赖配置

##### 2.2.1 LangChain4j 项目配置

代码语言：javascript

```javascript
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <groupId>com.example</groupId>
    <artifactId>langchain4j-demo</artifactId>
    <version>1.0-SNAPSHOT</version>

    <properties>
        <maven.compiler.source>17</maven.compiler.source>
        <maven.compiler.target>17</maven.compiler.target>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
        <langchain4j.version>0.24.0</langchain4j.version>
        <lombok.version>1.18.30</lombok.version>
        <commons-lang3.version>3.14.0</commons-lang3.version>
    </properties>

    <dependencies>
        <!-- LangChain4j核心依赖 -->
        <dependency>
            <groupId>dev.langchain4j</groupId>
            <artifactId>langchain4j-core</artifactId>
            <version>${langchain4j.version}</version>
        </dependency>

        <!-- OpenAI集成 -->
        <dependency>
            <groupId>dev.langchain4j</groupId>
            <artifactId>langchain4j-openai</artifactId>
            <version>${langchain4j.version}</version>
        </dependency>

        <!-- 内存存储 -->
        <dependency>
            <groupId>dev.langchain4j</groupId>
            <artifactId>langchain4j-memory</artifactId>
            <version>${langchain4j.version}</version>
        </dependency>

        <!-- Lombok -->
        <dependency>
            <groupId>org.projectlombok</groupId>
            <artifactId>lombok</artifactId>
            <version>${lombok.version}</version>
            <scope>provided</scope>
        </dependency>

        <!-- Apache Commons Lang -->
        <dependency>
            <groupId>org.apache.commons</groupId>
            <artifactId>commons-lang3</artifactId>
            <version>${commons-lang3.version}</version>
        </dependency>

        <!-- Spring Context (可选，用于依赖注入) -->
        <dependency>
            <groupId>org.springframework</groupId>
            <artifactId>spring-context</artifactId>
            <version>6.1.2</version>
        </dependency>
    </dependencies>
</project>
```

##### 2.2.2 SpringAI 项目配置

代码语言：javascript

```javascript
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.
